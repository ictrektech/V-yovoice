"""为通道任务持有本地进程，直到计算确认停止。"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
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

ATTEMPT = r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,95}$"
TASK_TYPE = "voice.transcribe"
MAX_AUDIO_BYTES = 20 << 20


class AudioParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    size_bytes: int = Field(strict=True, gt=0, le=MAX_AUDIO_BYTES)
    sha256: str = Field(pattern=DIGEST)
    format: str = Field(pattern=r"^(wav|flac|mp3|ogg|m4a)$")
    language: str = Field(default="", pattern=r"^[a-zA-Z0-9_-]{0,24}$")


def failure(code: str) -> dict:
    return {"status": "failed", "stopped": True, "result": {"code": code}}


class TranscriptionWorker:
    def __init__(self, root: Path, store: WeightStore, model_id: str, provider: str, threads: int):
        self.root = root
        self.store = store
        self.model_id = model_id
        self.provider = provider
        self.threads = threads
        self.lock = RLock()
        self.active: dict[str, tuple[subprocess.Popen, float]] = {}

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
            for attempt, (process, deadline) in list(self.active.items()):
                if process.poll() is not None:
                    self.receipt(attempt)
                elif deadline <= monotonic():
                    self.stop(attempt, failure("WORKER_LEASE_EXPIRED"))

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
        write_json(self.path(attempt) / "receipt.json", result)
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
            return {"status": "running", "stopped": False, "stage": "transcribing"}
        output = directory / "transcription.json"
        result = failure("WORKER_TRANSCRIPTION_FAILED")
        if code == 0 and output.is_file() and output.stat().st_size <= 40 * 1024:
            result = {"status": "succeeded", "stopped": True, "result": json.loads(output.read_bytes())}
        return self.stop(attempt, result)

    def write_input(self, attempt: str, offset: int, data: bytes) -> dict:
        directory = self.path(attempt)
        with self.lock:
            path = directory / "reference"
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            size = path.stat().st_size if path.is_file() else 0
            end = offset + len(data)
            if end > MAX_AUDIO_BYTES or offset > size:
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
            if body.get("model_id") != self.model_id:
                raise ValueError()
            parameters = AudioParameters.model_validate(body.get("parameters"))
            limits = body.get("model_limits")
            expected = {"input_bytes", "sample_rate", "duration_seconds"}
            if not isinstance(limits, dict) or not expected.issubset(limits) or any(
                type(limits[name]) not in (float, int) or not math.isfinite(limits[name]) or limits[name] <= 0
                for name in expected
            ) or parameters.size_bytes > limits["input_bytes"]:
                raise ValueError()
            audio = directory / "reference"
            if not audio.is_file() or audio.stat().st_size < parameters.size_bytes:
                if (directory / "attempt.json").stat().st_mtime + 120 < time():
                    return self.stop(attempt, failure("WORKER_INPUT_TIMEOUT"))
                return self.receipt(attempt)
            if audio.stat().st_size != parameters.size_bytes:
                raise ValueError()
            digest = hashlib.sha256()
            with audio.open("rb") as stream:
                for chunk in iter(lambda: stream.read(CHUNK_BYTES), b""):
                    digest.update(chunk)
            if digest.hexdigest() != parameters.sha256:
                raise ValueError()
            paths = self.store.verified_files(body.get("transfer_id", ""), self.model_id)
        except (TypeError, ValueError, HTTPException):
            return self.stop(attempt, failure("WORKER_INPUT_OR_WEIGHTS_INVALID"))
        if self.active:
            return self.stop(attempt, failure("WORKER_EXECUTOR_BUSY"))
        operation = directory / "operation.json"
        write_json(operation, {"model_id": self.model_id, "files": {name: str(path) for name, path in paths.items()},
                               "parameters": parameters.model_dump(), "limits": limits})
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


if __name__ == "__main__":
    from .audio import decode_calibrated_audio
    from .catalog import worker_files
    from .runtime import transcribe

    operation = Path(sys.argv[1])
    descriptor = json.loads(operation.read_bytes())
    parameters = AudioParameters.model_validate(descriptor["parameters"])
    limits = descriptor["limits"]
    data = (operation.parent / "reference").read_bytes()
    decoded, rate = decode_calibrated_audio(data, "input." + parameters.format, limits)
    worker_files.set({descriptor["model_id"]: descriptor["files"]})
    result = transcribe(descriptor["model_id"], decoded, rate, language=parameters.language)
    write_json(operation.parent / "transcription.json", result)
