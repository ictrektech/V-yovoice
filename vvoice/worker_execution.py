"""为通道任务持有本地进程，直到计算确认停止。"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from threading import RLock
from time import monotonic, time

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .worker_weights import CHUNK_BYTES, DIGEST, WeightStore, write_json
from .worker_models import (
    EMBED, MAX_OUTPUT_BYTES, SYNTHESIZE, TRANSCRIBE, WORKBENCH, WORKBENCH_BUNDLE_LIMIT,
    model_spec, workbench_models,
)

ATTEMPT = r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,95}$"
TASK_TYPE = TRANSCRIBE
MAX_AUDIO_BYTES = 20 << 20
OUTPUT_RETENTION_SECONDS = 600


class AudioParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    size_bytes: int = Field(strict=True, gt=0, le=MAX_AUDIO_BYTES)
    sha256: str = Field(pattern=DIGEST)
    format: str = Field(pattern=r"^(wav|flac|mp3|ogg|m4a)$")
    language: str = Field(default="", pattern=r"^[a-zA-Z0-9_-]{0,24}$")


class SpeechParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input: str = Field(min_length=1, max_length=500)
    voice: str = Field(default="default", max_length=96)


class WorkbenchParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    size_bytes: int = Field(strict=True, gt=0, le=WORKBENCH_BUNDLE_LIMIT)
    sha256: str = Field(pattern=DIGEST)
    models: list[str] = Field(min_length=1, max_length=16)


def failure(code: str) -> dict:
    return {"status": "failed", "stopped": True, "result": {"code": code}}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ComputeWorker:
    def __init__(self, root: Path, store: WeightStore, provider: str, threads: int):
        self.root = root
        self.store = store
        self.provider = provider
        self.threads = threads
        self.lock = RLock()
        self.active: dict[str, tuple[subprocess.Popen, float]] = {}
        self.next_output_sweep = 0.0

    def path(self, attempt: str) -> Path:
        if not re.fullmatch(ATTEMPT, attempt):
            raise HTTPException(422, "INVALID_WORKER_ATTEMPT")
        return self.root / attempt

    @asynccontextmanager
    async def lifespan(self, _app):
        # 容器 PID 1 退出后，之前的子进程不能跨容器实例存活。
        for metadata in self.root.glob("*/attempt.json"):
            if not (metadata.parent / "receipt.json").exists():
                write_json(metadata.parent / "receipt.json", failure("WORKER_RESTARTED"))
        task = asyncio.create_task(self.watchdog())
        try:
            yield
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            with self.lock:
                for attempt in list(self.active):
                    self.stop(attempt, failure("WORKER_STOPPED"))

    async def watchdog(self) -> None:
        while True:
            await asyncio.sleep(0.5)
            await asyncio.to_thread(self.reap)

    def reap(self) -> None:
        with self.lock:
            now = monotonic()
            for attempt, (process, deadline) in list(self.active.items()):
                if process.poll() is not None:
                    self.receipt(attempt)
                elif deadline <= now:
                    self.stop(attempt, failure("WORKER_LEASE_EXPIRED"))
            if now >= self.next_output_sweep:
                self.next_output_sweep = now + 60
                self.sweep_embeddings()

    def sweep_embeddings(self):
        cutoff = time() - OUTPUT_RETENTION_SECONDS
        for pattern, age in (("*/embedding.json", cutoff), ("*/workbench.zip", time() - 86400)):
            for path in self.root.glob(pattern):
                if path.parent.name not in self.active and path.stat().st_mtime < age:
                    path.unlink(missing_ok=True)

    def stop(self, attempt: str, result: dict) -> dict:
        run = self.active.get(attempt)
        if run:
            process, _ = run
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=5)
        directory = self.path(attempt)
        (directory / "reference").unlink(missing_ok=True)
        shutil.rmtree(directory / "workbench", ignore_errors=True)
        write_json(directory / "receipt.json", result)
        self.active.pop(attempt, None)
        return result

    def receipt(self, attempt: str) -> dict:
        directory = self.path(attempt)
        saved = directory / "receipt.json"
        if saved.is_file():
            return json.loads(saved.read_bytes())
        run = self.active.get(attempt)
        if run is None:
            return {"status": "running", "stopped": False, "stage": "waiting_for_audio"}
        code = run[0].poll()
        if code is None:
            return {"status": "running", "stopped": False, "stage": "running"}
        output = directory / "transcription.json"
        result = failure("WORKER_TRANSCRIPTION_FAILED")
        if code == 0 and output.is_file() and output.stat().st_size <= 40 * 1024:
            result = {"status": "succeeded", "stopped": True, "result": json.loads(output.read_bytes())}
        return self.stop(attempt, result)

    def read_output(self, attempt: str, file_id: str, offset: int) -> dict:
        with self.lock:
            directory = self.path(attempt)
            receipt = self.receipt(attempt)
            output = receipt.get("result", {}).get("output")
            if receipt["status"] != "succeeded" or not isinstance(output, dict) or output["file_id"] != file_id:
                raise HTTPException(404, "WORKER_OUTPUT_NOT_FOUND")
            if not 0 <= offset < output["size_bytes"]:
                raise HTTPException(422, "WORKER_OUTPUT_OFFSET_INVALID")
            try:
                with (directory / file_id).open("rb") as stream:
                    stream.seek(offset)
                    chunk = stream.read(CHUNK_BYTES)
            except FileNotFoundError:
                raise HTTPException(404, "WORKER_OUTPUT_NOT_FOUND") from None
            return {**output, "offset": offset, "data_b64": base64.b64encode(chunk).decode("ascii")}

    def write_input(self, attempt: str, offset: int, data: bytes) -> dict:
        directory = self.path(attempt)
        with self.lock:
            path = directory / "reference"
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            size = path.stat().st_size if path.is_file() else 0
            end = offset + len(data)
            limit_file = directory / "input-limit"
            limit = int(limit_file.read_text()) if limit_file.is_file() else MAX_AUDIO_BYTES
            if end > limit or offset > size:
                raise HTTPException(409, "WORKER_INPUT_OFFSET_MISMATCH")
            if offset < size:
                with path.open("rb") as stream:
                    stream.seek(offset)
                    if end > size or stream.read(len(data)) != data:
                        raise HTTPException(409, "WORKER_INPUT_OFFSET_MISMATCH")
                return {"received_bytes": size}
            if attempt in self.active or (directory / "receipt.json").is_file():
                raise HTTPException(409, "WORKER_INPUT_SEALED")
            with path.open("ab") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            return {"received_bytes": end}

    def command(self, attempt: str, action: str, body: dict) -> dict:
        directory = self.path(attempt)
        key = {"task_id": body.get("task_id"), "fence": body.get("fence")}
        if not isinstance(key["task_id"], str) or not key["task_id"] or type(key["fence"]) is not int or key["fence"] <= 0:
            raise HTTPException(422, "INVALID_WORKER_COMMAND")
        with self.lock:
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            metadata = directory / "attempt.json"
            if metadata.is_file():
                if json.loads(metadata.read_bytes()) != key:
                    raise HTTPException(409, "STALE_WORKER_ATTEMPT")
            elif action in {"start", "cancel"}:
                write_json(metadata, key)
            else:
                return {"status": "running", "stopped": False, "stage": "waiting_for_start"}
            status = self.receipt(attempt)
            if status["stopped"]:
                return status
            if action == "cancel":
                return self.stop(attempt, {"status": "cancelled", "stopped": True, "result": {}})
            if action == "inspect":
                return status
            lease = body.get("lease_seconds")
            if type(lease) is not int or not 1 <= lease <= 60:
                return self.stop(attempt, failure("INVALID_WORKER_LEASE"))
            if attempt in self.active:
                process, deadline = self.active[attempt]
                if deadline <= monotonic():
                    return self.stop(attempt, failure("WORKER_LEASE_EXPIRED"))
                self.active[attempt] = (process, monotonic() + lease)
                return status
            return self.start(attempt, directory, body, lease)

    def start(self, attempt: str, directory: Path, body: dict, lease: int) -> dict:
        try:
            model_id = body.get("model_id")
            task, _, _ = model_spec(model_id)
            limits = body.get("model_limits")
            expected = {
                SYNTHESIZE: {"text_characters"}, WORKBENCH: {"bundle_bytes"},
            }.get(task, {"input_bytes", "sample_rate", "duration_seconds"})
            if not isinstance(limits, dict) or not expected.issubset(limits) or any(
                type(limits[name]) not in (float, int) or not math.isfinite(limits[name]) or limits[name] <= 0
                for name in expected
            ):
                raise ValueError()
            if task == SYNTHESIZE:
                parameters = SpeechParameters.model_validate(body.get("parameters"))
                if len(parameters.input) > limits["text_characters"]:
                    raise ValueError()
            else:
                parameters = (WorkbenchParameters if task == WORKBENCH else AudioParameters).model_validate(body.get("parameters"))
                limit = limits["bundle_bytes"] if task == WORKBENCH else limits["input_bytes"]
                if parameters.size_bytes > limit:
                    raise ValueError()
                if task == WORKBENCH:
                    (directory / "input-limit").write_text(str(parameters.size_bytes))
                audio = directory / "reference"
                if not audio.is_file() or audio.stat().st_size < parameters.size_bytes:
                    if (directory / "attempt.json").stat().st_mtime + (900 if task == WORKBENCH else 120) < time():
                        return self.stop(attempt, failure("WORKER_INPUT_TIMEOUT"))
                    return self.receipt(attempt)
                if audio.stat().st_size != parameters.size_bytes:
                    raise ValueError()
                if file_sha256(audio) != parameters.sha256:
                    raise ValueError()
            paths = self.store.verified_files(body.get("transfer_id", ""), model_id)
            packages = {}
            if task == WORKBENCH:
                if model_id not in parameters.models or len(set(parameters.models)) != len(parameters.models):
                    raise ValueError()
                for key in parameters.models:
                    item = workbench_models()[key]
                    verified = paths if key == model_id else self.store.verified_files(self.store.ready_transfer(key) or "", key)
                    for field, target in item["runtime"]["files"].items():
                        if target in packages and packages[target] != str(verified[field]):
                            raise ValueError()
                        packages[target] = str(verified[field])
        except (KeyError, OSError, TypeError, ValueError, HTTPException):
            return self.stop(attempt, failure("WORKER_INPUT_OR_WEIGHTS_INVALID"))
        if self.active:
            return self.stop(attempt, failure("WORKER_EXECUTOR_BUSY"))
        operation = directory / "operation.json"
        write_json(operation, {"model_id": model_id, "files": {name: str(path) for name, path in paths.items()},
                               "parameters": parameters.model_dump(), "limits": limits, "packages": packages})
        env = {**os.environ, "VVOICE_SCHEDULER_REQUIRED": "false",
               "VVOICE_PROVIDER": self.provider, "VVOICE_NUM_THREADS": str(self.threads)}
        env.pop("V_SCHEDULER_BACKEND_CHANNEL_TOKEN", None)
        try:
            process = subprocess.Popen([sys.executable, "-m", "vvoice.worker_execution", str(operation)],
                                       env=env, start_new_session=True, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL)
        except OSError:
            return self.stop(attempt, failure("WORKER_PROCESS_START_FAILED"))
        self.active[attempt] = (process, monotonic() + lease)
        return self.receipt(attempt)


def execute_operation(operation: Path):
    from .audio import decode_calibrated_audio, encode_audio
    from .catalog import worker_files
    from .runtime import extract_embedding, synthesize, transcribe

    descriptor = json.loads(operation.read_bytes())
    model_id = descriptor["model_id"]
    task = model_spec(model_id)[0]
    if task == WORKBENCH:
        from .creative import REPOSITORY

        root = operation.parent / "workbench"
        modelhub = root / "modelhub"
        base = modelhub / "export" / "ms" / REPOSITORY / "current"
        for relative, path in descriptor["packages"].items():
            target = base / relative
            if not target.resolve().is_relative_to(base.resolve()):
                raise ValueError("invalid catalog path")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(path)
        output = operation.parent / "workbench.zip"
        subprocess.run(
            ["/opt/vvoice/vvoice-studio", "node-job", str(root / "state"), str(operation.parent / "reference"), str(output)],
            env={**os.environ, "MODEL_HUB_SHARED_MODELS_PATH": str(modelhub), "VVOICE_SHARED_MODELS": "true"},
            check=True,
        )
        size = output.stat().st_size
        if not 0 < size <= WORKBENCH_BUNDLE_LIMIT:
            raise ValueError("invalid workbench result size")
        write_json(operation.parent / "transcription.json", {
            "output": {"file_id": output.name, "size_bytes": size, "sha256": file_sha256(output)},
        })
        return
    worker_files.set({model_id: descriptor["files"]})
    if task == SYNTHESIZE:
        parameters = SpeechParameters.model_validate(descriptor["parameters"])
        samples, rate = synthesize(model_id, parameters.input, parameters.voice, 1.0)
        content, _ = encode_audio(samples, rate, "mp3")
        name = "speech.mp3"
    else:
        parameters = AudioParameters.model_validate(descriptor["parameters"])
        reference = operation.parent / "reference"
        data = reference.read_bytes()
        reference.unlink(missing_ok=True)
        decoded, rate = decode_calibrated_audio(data, "input." + parameters.format, descriptor["limits"])
        if task == TRANSCRIBE:
            result = transcribe(model_id, decoded, rate, language=parameters.language)
            write_json(operation.parent / "transcription.json", result)
            return
        if task != EMBED:
            raise ValueError("unsupported compute task")
        content = json.dumps(extract_embedding(model_id, decoded, rate).tolist(), allow_nan=False).encode()
        name = "embedding.json"
    if not 0 < len(content) <= MAX_OUTPUT_BYTES:
        raise ValueError("invalid compute result size")
    (operation.parent / name).write_bytes(content)
    result = {"output": {"file_id": name, "size_bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}}
    write_json(operation.parent / "transcription.json", result)


if __name__ == "__main__":
    execute_operation(Path(sys.argv[1]))
