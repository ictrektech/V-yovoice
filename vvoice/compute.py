"""V-Voice 主实例的跨节点转写入口。"""
from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
import re
from contextlib import asynccontextmanager
from pathlib import Path
from time import monotonic
from typing import Callable, Literal
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from .admission import configuration
from .catalog import find_model, model_root, resolve_files, shared_files_for
from .config import settings
from .dialogue import Identity, _admin, _verify_user
from .modelhub import list_models
from .scheduling_options import operator_headers
from .worker import MODE
from .worker_execution import MAX_AUDIO_BYTES, TASK_TYPE, SpeechParameters
from .worker_models import EMBED, MAX_OUTPUT_BYTES, MODELS, SENSEVOICE, SYNTHESIZE, model_ids, model_spec, workbench_models
from .speakers import DEFAULT_IDENTIFY_THRESHOLD, SpeakerStore, open_speaker_store
from .worker_weights import CHUNK_BYTES, write_json

router = APIRouter(prefix="/api/v1/compute")
DEPLOYMENT_ID = r"^[a-f0-9]{32}$"
ID = r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,95}$"
WeightMode = Literal["auto", "shared", "copy"]
_preparations: dict[tuple[str, str], asyncio.Task] = {}
_mutating: set[str] = set()
_shared_errors = {"BACKEND_SHARED_MODEL_HUB_UNAVAILABLE", "BACKEND_TRANSFER_CONFLICT",
                  "BACKEND_TRANSFER_NOT_FOUND"}


def client() -> httpx.AsyncClient:
    config = configuration()
    return httpx.AsyncClient(base_url=config["url"].rstrip("/") + "/",
                             headers={"Authorization": "Bearer " + config["token"]},
                             timeout=25, follow_redirects=False)


async def scheduler(connection: httpx.AsyncClient, method: str, path: str, **kwargs):
    try:
        response = await connection.request(method, path, **kwargs)
        body = response.json()
    except (httpx.HTTPError, ValueError):
        raise HTTPException(503, "VOICE_COMPUTE_SCHEDULER_UNAVAILABLE") from None
    if response.is_error:
        code = body.get("code") if isinstance(body, dict) else None
        if not isinstance(code, str):
            code = "VOICE_COMPUTE_SCHEDULER_REJECTED"
        raise HTTPException(response.status_code, code)
    if not isinstance(body, dict) or body.get("code") != "OK":
        raise HTTPException(503, "VOICE_COMPUTE_SCHEDULER_UNAVAILABLE")
    return body["data"]


def worker_deployment(row: dict) -> bool:
    return row.get("app_id") == settings.app_id and row.get("config", {}).get("mode") == MODE


async def require_admin(identity: Identity = Depends(_verify_user)) -> None:
    if not _admin(identity):
        raise HTTPException(403, "VOICE_COMPUTE_ADMIN_REQUIRED")


async def node_names(connection: httpx.AsyncClient) -> dict[tuple[str, str], str]:
    # 仅附加显示名。节点目录暂不可读时仍保留可调用的部署和节点 ID。
    try:
        inventory = await scheduler(connection, "GET", "managed-nodes")
    except HTTPException:
        return {}
    return {
        (kind, row["id"]): name
        for kind, field in (("ssh", "items"), ("cluster", "cluster_nodes"))
        for row in inventory.get(field, [])
        if (name := row.get("name") or row.get("hostname"))
    }


@router.get("/placements")
async def placements(task_type: Literal["voice.transcribe", "voice.synthesize", "voice.speaker_embedding", "voice.workbench"] = TASK_TYPE,
                     identity: Identity = Depends(_verify_user)):
    async with client() as connection:
        records = await scheduler(connection, "GET", "backend-deployments")
        placements_with_targets = []
        for row in records["items"]:
            if worker_deployment(row) and row["state"] == "running":
                try:
                    selected = await scheduler(connection, "GET", f"backend-deployments/{row['id']}/models")
                except HTTPException as error:
                    if error.status_code == 409:
                        continue
                    raise
                target = (row["target_kind"], row["target_id"])
                placements_with_targets.extend((item, target) for item in selected["items"]
                                               if item["task_type"] == task_type)
        names = await node_names(connection) if placements_with_targets else {}
        return {"items": [{**item, "node_name": names.get(target)} for item, target in placements_with_targets],
                "can_force_admission": _admin(identity)}


@router.get("/deployments", dependencies=[Depends(require_admin)])
async def deployments():
    async with client() as connection:
        access, rows, names = await asyncio.gather(
            scheduler(connection, "GET", f"backend-deployment-access/{settings.app_id}"),
            scheduler(connection, "GET", "backend-deployments"),
            node_names(connection),
        )
        async def describe(row):
            registered = []
            if row["state"] == "running" and not row.get("last_error"):
                try:
                    result = await scheduler(connection, "GET", f"backend-deployments/{row['id']}/models")
                    registered = [item["model_id"] for item in result["items"]]
                except HTTPException as error:
                    if error.status_code != 409:
                        raise
            return {**row, "node_name": names.get((row["target_kind"], row["target_id"])),
                    "registered_models": registered,
                    "preparations": [record for key in model_ids() if (record := read_preparation(row["id"], key))]}
        descriptions = await asyncio.gather(*(describe(row) for row in rows["items"]
                                              if worker_deployment(row) and row["state"] != "removed"))
    targets = [{**target, "node_name": names.get((target["kind"], target["id"]))}
               for target in access.get("targets", [])]
    models = await preparation_models()
    return {"targets": targets, "images": access.get("images", {}), "models": models,
            "deployments": descriptions}


async def preparation_models():
    rows = await list_models([*(find_model(key) for key in MODELS), *workbench_models().values()])
    return [{"model_id": item["key"], "name": item["name"], "kind": item["kind"],
             "status": item["status"], "ready": item["status"] == "ready", "progress": item.get("progress"),
             "error": item.get("error")} for item in rows]


class Deploy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["ssh", "cluster"]
    node_id: str = Field(pattern=ID)
    request_key: str = Field(pattern=ID)
    cpu_millicores: int | None = Field(None, strict=True, ge=100, le=128_000)
    memory_mib: int | None = Field(None, strict=True, ge=16, le=1_048_576)


@router.post("/deployments", dependencies=[Depends(require_admin)])
async def deploy(data: Deploy):
    async with client() as connection:
        access = await scheduler(connection, "GET", f"backend-deployment-access/{settings.app_id}")
        target = next((row for row in access.get("targets", [])
                       if (row["kind"], row["id"]) == (data.kind, data.node_id)), None)
        image = access.get("images", {}).get(target["profile"]) if target else None
        if not image:
            raise HTTPException(403, "VOICE_COMPUTE_TARGET_UNAVAILABLE")
        budgets = {key: value for key, value in data.model_dump().items()
                   if key in {"cpu_millicores", "memory_mib"} and value is not None}
        return await scheduler(connection, "POST", "backend-deployments", json={
            "request_key": data.request_key, "target": target, "image": image, "container_port": 7070,
            "config": {"mode": MODE, "profile": target["profile"]},
            **budgets,
        })


async def require_deployment(connection, deployment_id: str) -> str:
    if len(deployment_id) != 32 or any(char not in "0123456789abcdef" for char in deployment_id):
        raise HTTPException(422, "VOICE_COMPUTE_DEPLOYMENT_INVALID")
    path = f"backend-deployments/{deployment_id}"
    row = await scheduler(connection, "GET", path)
    if not worker_deployment(row):
        raise HTTPException(404, "VOICE_COMPUTE_DEPLOYMENT_NOT_FOUND")
    return path


@router.delete("/deployments/{deployment_id}", dependencies=[Depends(require_admin)])
async def delete_deployment(deployment_id: str):
    async with deployment_change(deployment_id) as (connection, path):
        receipt = await scheduler(connection, "DELETE", path)
        for model_id in model_ids():
            preparation_path(deployment_id, model_id).unlink(missing_ok=True)
        return receipt


@router.delete("/deployments/{deployment_id}/models/{model_id}", dependencies=[Depends(require_admin)])
async def delete_model(deployment_id: str, model_id: str):
    if model_id not in model_ids():
        raise HTTPException(404, "VOICE_COMPUTE_MODEL_UNSUPPORTED")
    async with deployment_change(deployment_id) as (connection, path):
        receipt = await scheduler(connection, "DELETE", f"{path}/models/{model_id}")
        preparation_path(deployment_id, model_id).unlink(missing_ok=True)
        return receipt


@asynccontextmanager
async def deployment_change(deployment_id: str):
    if any(key[0] == deployment_id for key in _preparations) or deployment_id in _mutating:
        raise HTTPException(409, "VOICE_COMPUTE_PREPARATION_ACTIVE")
    _mutating.add(deployment_id)
    try:
        async with client() as connection:
            yield connection, await require_deployment(connection, deployment_id)
    finally:
        _mutating.discard(deployment_id)


def preparation_path(deployment_id: str, model_id: str) -> Path:
    return settings.data_dir / "compute-preparations" / f"{deployment_id}-{model_id}.json"


def read_preparation(deployment_id: str, model_id: str) -> dict | None:
    if not re.fullmatch(DEPLOYMENT_ID, deployment_id):
        return None
    try:
        record = json.loads(preparation_path(deployment_id, model_id).read_bytes())
    except FileNotFoundError:
        return None
    if record["state"] == "preparing" and (deployment_id, model_id) not in _preparations:
        return {**record, "state": "interrupted", "error": "VOICE_COMPUTE_PREPARATION_INTERRUPTED"}
    return record


class PrepareModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_id: str = SENSEVOICE
    weight_mode: WeightMode


@router.post("/deployments/{deployment_id}/models", status_code=202, dependencies=[Depends(require_admin)])
async def prepare_model(deployment_id: str, data: PrepareModel):
    if data.model_id not in model_ids():
        raise HTTPException(404, "VOICE_COMPUTE_MODEL_UNSUPPORTED")
    key = (deployment_id, data.model_id)
    if key in _preparations:
        previous = read_preparation(*key)
        if previous and previous["weight_mode"] == data.weight_mode:
            return previous
        raise HTTPException(409, "VOICE_COMPUTE_PREPARATION_ACTIVE")
    async with deployment_change(deployment_id) as (connection, path):
        row = await scheduler(connection, "GET", path)
        if row["state"] != "running" or row.get("last_error"):
            raise HTTPException(409, "VOICE_COMPUTE_BACKEND_NOT_RUNNING")
        models = await scheduler(connection, "GET", f"{path}/models")
        if any(model["model_id"] == data.model_id for model in models["items"]):
            raise HTTPException(409, "VOICE_COMPUTE_MODEL_ALREADY_REGISTERED")
        record = {
            "model_id": data.model_id, "weight_mode": data.weight_mode, "weight_source": None,
            "state": "preparing", "phase": "source_check", "received_bytes": 0,
            "total_bytes": 0, "error": None,
        }
        status_path = preparation_path(*key)
        status_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(status_path, record)
        _preparations[key] = asyncio.create_task(run_preparation(key, path, status_path, record))
        return record


@router.post("/deployments/{deployment_id}/{action}", dependencies=[Depends(require_admin)])
async def lifecycle(deployment_id: str, action: Literal["start", "stop", "prepare"]):
    async with deployment_change(deployment_id) as (connection, path):
        return await prepare(connection, path) if action == "prepare" else await scheduler(connection, "POST", f"{path}/{action}")


async def run_preparation(key: tuple[str, str], path: str, status_path: Path, record: dict):
    last_write = 0.0

    def progress(phase: str, source: str | None, received: int, total: int):
        nonlocal last_write
        now = monotonic()
        changed = (phase, source) != (record["phase"], record["weight_source"])
        record.update(phase=phase, weight_source=source, received_bytes=received, total_bytes=total)
        if changed or received == total or now - last_write >= 1:
            write_json(status_path, record)
            last_write = now

    try:
        async with client() as connection:
            await prepare(connection, path, record["weight_mode"], progress, model_id=key[1])
        record.update(state="registered")
    except HTTPException as error:
        record.update(state="failed", error=error.detail)
    except (KeyError, OSError, ValueError):
        record.update(state="failed", error="VOICE_COMPUTE_PREPARATION_FAILED")
    except asyncio.CancelledError:
        record.update(state="interrupted", error="VOICE_COMPUTE_PREPARATION_INTERRUPTED")
        raise
    finally:
        try:
            write_json(status_path, record)
        finally:
            _preparations.pop(key, None)


def source_files(model_id: str = SENSEVOICE) -> tuple[list[dict], dict[str, Path]]:
    try:
        creative = workbench_models().get(model_id)
        item = creative or find_model(model_id)
        root = model_root(item).resolve()
        if creative:
            files = shared_files_for(item, root)
            paths = {f"file_{i}": (root / row["path"]).resolve() for i, row in enumerate(files)}
            if not all(path.is_relative_to(root) for path in paths.values()):
                raise ValueError()
        else:
            paths = {role: Path(path) for role, path in resolve_files(item).items()}
        for name in item["runtime"].get("rule_fsts", []):
            rule = (root / name).resolve()
            if not rule.is_relative_to(root):
                raise ValueError()
            paths[f"fst-{rule.stem}"] = rule
        if {role: path.name for role, path in paths.items()} != model_spec(model_id)[1]:
            raise ValueError()
        records = []
        for role, path in paths.items():
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(CHUNK_BYTES), b""):
                    digest.update(chunk)
            records.append({"file_id": role, "path": path.name, "size_bytes": path.stat().st_size,
                            "sha256": digest.hexdigest()})
        return records, paths
    except (KeyError, OSError, ValueError):
        raise HTTPException(409, "VOICE_COMPUTE_SOURCE_MODEL_UNAVAILABLE") from None


async def prepare(connection: httpx.AsyncClient, path: str, mode: WeightMode = "auto",
                  progress: Callable[[str, str | None, int, int], None] | None = None, *,
                  model_id: str = SENSEVOICE):
    report = progress or (lambda *_: None)
    files, paths = await asyncio.to_thread(source_files, model_id)
    manifest = {"model_id": model_id, "files": files}
    base = f"{path}/transfers"
    total = sum(row["size_bytes"] for row in files)
    if mode != "copy":
        try:
            shared = [
                {**row, "shared_path": paths[row["file_id"]].relative_to(settings.modelhub_root.resolve()).as_posix()}
                for row in files
            ]
            report("mounting", "shared", 0, 0)
            share = await scheduler(connection, "GET", f"{path}/model-hub")
            if share.get("state") != "ready":
                raise HTTPException(409, "BACKEND_SHARED_MODEL_HUB_UNAVAILABLE")
            receipt = await scheduler(connection, "POST", base, json={**manifest, "files": shared, "source": "shared"})
            transfer = receipt["transfer_id"]
            report("target_check", "shared", 0, 0)
            await scheduler(connection, "POST", f"{base}/{transfer}/complete", timeout=310)
        except ValueError:
            if mode == "shared":
                raise HTTPException(409, "VOICE_COMPUTE_SOURCE_NOT_SHARED") from None
        except HTTPException as error:
            if mode == "shared" or error.detail not in _shared_errors:
                raise
        else:
            report("registering", "shared", total, total)
            return await scheduler(connection, "POST", f"{path}/models", json={"model_id": model_id, "transfer_id": transfer})
    report("copying", "copy", 0, total)
    receipt = await scheduler(connection, "POST", base, json=manifest)
    transfer = receipt["transfer_id"]
    offsets = {item["file_id"]: item["received_bytes"] for item in receipt["files"]}
    copied = sum(offsets.values())
    report("copying", "copy", copied, total)
    for row in files:
        role = row["file_id"]
        offset = offsets[role]
        with paths[role].open("rb") as stream:
            stream.seek(offset)
            while offset < row["size_bytes"]:
                chunk = await asyncio.to_thread(stream.read, min(CHUNK_BYTES, row["size_bytes"] - offset))
                if not chunk:
                    raise HTTPException(409, "VOICE_COMPUTE_SOURCE_MODEL_CHANGED")
                reply = await scheduler(connection, "PUT", f"{base}/{transfer}/files/{role}",
                                        params={"offset": offset}, content=chunk,
                                        headers={"Content-Type": "application/octet-stream"})
                if reply.get("received_bytes") != offset + len(chunk):
                    raise HTTPException(409, "VOICE_COMPUTE_TRANSFER_RETRY")
                offset += len(chunk)
                copied += len(chunk)
                report("copying", "copy", copied, total)
    report("target_check", "copy", 0, 0)
    await scheduler(connection, "POST", f"{base}/{transfer}/complete", timeout=310)
    report("registering", "copy", total, total)
    return await scheduler(connection, "POST", f"{path}/models", json={"model_id": model_id, "transfer_id": transfer})


@router.post("/transcriptions")
async def transcriptions(
    request: Request,
    deployment_id: str = Form(pattern=DEPLOYMENT_ID),
    executor_id: str = Form(pattern=ID),
    language: str = Form(default="", pattern=r"^[a-zA-Z0-9_-]{0,24}$"),
    file: UploadFile = File(),
    force_admission: bool = Form(False),
    identity: Identity = Depends(_verify_user),
):
    data, parameters = await audio_input(file, language)
    receipt, result = await execute_at(request, identity, deployment_id, executor_id, TASK_TYPE,
                                       parameters, data, force_admission)
    receipt.pop("model_id")
    return {**receipt, "transcription": result}


async def audio_input(file: UploadFile, language: str = "") -> tuple[bytes, dict]:
    data = await file.read(MAX_AUDIO_BYTES + 1)
    fmt = Path(file.filename or "").suffix.lower().lstrip(".")
    if not data or len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "VOICE_COMPUTE_AUDIO_SIZE")
    if fmt not in {"wav", "flac", "mp3", "ogg", "m4a"}:
        raise HTTPException(422, "VOICE_COMPUTE_AUDIO_FORMAT")
    return data, {"size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                  "format": fmt, "language": language}


class RemoteSpeech(SpeechParameters):
    deployment_id: str = Field(pattern=DEPLOYMENT_ID)
    executor_id: str = Field(pattern=ID)


@router.post("/speech")
async def speech(request: Request, data: RemoteSpeech, identity: Identity = Depends(_verify_user)):
    receipt, audio = await execute_at(request, identity, data.deployment_id, data.executor_id, SYNTHESIZE,
                                     data.model_dump(exclude={"deployment_id", "executor_id"}))
    return Response(audio, media_type="audio/mpeg", headers={
        "X-Execution-Node": receipt["node_id"], "X-Execution-Executor": receipt["executor_id"],
        "X-Execution-Deployment": receipt["deployment_id"],
    })


@router.post("/speakers/{action}")
async def compute_speaker(
    action: Literal["enroll", "identify", "verify"], request: Request, file: UploadFile = File(),
    deployment_id: str = Form(pattern=DEPLOYMENT_ID), executor_id: str = Form(pattern=ID),
    threshold: float = Form(DEFAULT_IDENTIFY_THRESHOLD, ge=0, le=1),
    name: str = Form("", max_length=64), speaker: str = Form("", max_length=96),
    identity: Identity = Depends(_verify_user),
):
    if action == "enroll":
        await require_admin(identity)
    store = open_speaker_store(settings.data_dir)
    enrolled = store.find(speaker) if action == "verify" else None
    if action == "verify" and enrolled is None:
        raise HTTPException(404, "VOICE_COMPUTE_SPEAKER_NOT_FOUND")
    audio, parameters = await audio_input(file)
    receipt, content = await execute_at(request, identity, deployment_id, executor_id, EMBED, parameters, audio)
    try:
        embedding = json.loads(content)
        model = receipt["model_id"]
        if action == "enroll":
            result = store.create(name, embedding, model)
        elif action == "identify":
            ranked = store.rank(embedding, limit=5)
            best = ranked[0] if ranked else None
            identified = bool(best and best["score"] >= threshold)
            result = {"object": "speaker.identification", "model": model, "threshold": threshold,
                      "identified": identified, "speaker": best if identified else None,
                      "score": best["score"] if best else 0.0, "ranked": ranked}
        else:
            match = next((row for row in store.rank(embedding) if row["id"] == enrolled["id"]), None)
            score = match["score"] if match else 0.0
            result = {"object": "speaker.verification", "model": model, "threshold": threshold,
                      "score": score, "verified": score >= threshold, "speaker": SpeakerStore.describe(enrolled)}
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    return {**receipt, "result": result}


async def read_output(connection, path: str, job: dict, file_id: str) -> bytes:
    output = job.get("result", {}).get("output")
    if (not isinstance(output, dict) or output.get("file_id") != file_id
            or type(output.get("size_bytes")) is not int or not 0 < output["size_bytes"] <= MAX_OUTPUT_BYTES
            or not isinstance(output.get("sha256"), str) or not re.fullmatch(r"[a-f0-9]{64}", output["sha256"])):
        raise HTTPException(502, "VOICE_COMPUTE_OUTPUT_INVALID")
    attempt_id = job.get("attempt_id")
    fence = job["fence"]
    if not attempt_id:
        attempts = await scheduler(connection, "GET", f"tasks/{job['task_id']}/attempts")
        attempt_id = next((row["attempt_id"] for row in attempts
                           if row["status"] == "succeeded" and row["fence"] == fence), None)
    if not isinstance(attempt_id, str) or not re.fullmatch(ID, attempt_id):
        raise HTTPException(502, "VOICE_COMPUTE_OUTPUT_INVALID")
    result = bytearray()
    size = output["size_bytes"]
    for offset in range(0, size, CHUNK_BYTES):
        data = await scheduler(connection, "GET", f"{path}/executions/{attempt_id}/outputs/{file_id}",
                               params={"offset": offset}, headers={"X-Scheduler-Fence": str(fence)})
        try:
            chunk = base64.b64decode(data["data_b64"], validate=True)
        except (KeyError, TypeError, binascii.Error):
            raise HTTPException(502, "VOICE_COMPUTE_OUTPUT_INVALID") from None
        if len(chunk) != min(CHUNK_BYTES, size - offset) or data.get("offset") != offset:
            raise HTTPException(502, "VOICE_COMPUTE_OUTPUT_INVALID")
        result.extend(chunk)
    if hashlib.sha256(result).hexdigest() != output["sha256"]:
        raise HTTPException(502, "VOICE_COMPUTE_OUTPUT_INVALID")
    return bytes(result)


async def execute_at(request: Request, identity: Identity, deployment_id: str, executor_id: str,
                     task_type: str, parameters: dict, data: bytes = b"", force_admission: bool = False):
    if force_admission and not _admin(identity):
        raise HTTPException(403, "VOICE_COMPUTE_ADMIN_REQUIRED")
    async with client() as connection:
        path = await require_deployment(connection, deployment_id)
        available = await scheduler(connection, "GET", f"{path}/models")
        chosen = next((item for item in available["items"]
                       if item["executor_id"] == executor_id and item["task_type"] == task_type), None)
        if not chosen:
            raise HTTPException(409, "VOICE_COMPUTE_PLACEMENT_UNAVAILABLE")
        key = uuid4().hex
        scheduling = {"force_admission": True} if force_admission else {}
        headers = {"Idempotency-Key": key, **operator_headers(scheduling, request.headers.get("authorization", ""))}
        job = await scheduler(connection, "POST", "tasks", headers=headers, json={
            "protocol_version": 1, "app_task_id": key, "scheduling": scheduling,
            "executor": {"id": executor_id, "contract_version": "1", "task_type": task_type},
            "parameters": parameters,
        })
        task_path = f"tasks/{job['task_id']}"
        deadline = monotonic() + 180
        uploaded_attempt = None
        completed = False
        try:
            while monotonic() < deadline:
                if await request.is_disconnected():
                    raise HTTPException(499, "VOICE_COMPUTE_CALLER_DISCONNECTED")
                state = job["status"]
                if state in {"succeeded", "failed", "cancelled"}:
                    completed = True
                    if state != "succeeded":
                        raise HTTPException(409, "VOICE_COMPUTE_TRANSCRIPTION_FAILED")
                    if job["executor_id"] != executor_id or job["node_id"] != chosen["node_id"]:
                        raise HTTPException(502, "VOICE_COMPUTE_PLACEMENT_MISMATCH")
                    file_id = {SYNTHESIZE: "speech.mp3", EMBED: "embedding.json"}.get(task_type)
                    result = await read_output(connection, path, job, file_id) if file_id else job["result"]
                    return ({"deployment_id": deployment_id, "task_id": job["task_id"],
                             "node_id": job["node_id"], "executor_id": executor_id,
                             "model_id": chosen.get("model_id")}, result)
                if data and job.get("attempt_id") and state in {"assigned", "running"} and job["attempt_id"] != uploaded_attempt:
                    payload_path = f"{path}/executions/{job['attempt_id']}/inputs/reference"
                    for offset in range(0, len(data), CHUNK_BYTES):
                        chunk = data[offset:offset + CHUNK_BYTES]
                        reply = await scheduler(connection, "PUT", payload_path, params={"offset": offset}, content=chunk,
                                                headers={"Content-Type": "application/octet-stream",
                                                         "X-Scheduler-Fence": str(job["fence"])})
                        if reply.get("received_bytes") != offset + len(chunk):
                            raise HTTPException(409, "VOICE_COMPUTE_INPUT_TRANSFER_FAILED")
                    uploaded_attempt = job["attempt_id"]
                await asyncio.sleep(0.5)
                job = await scheduler(connection, "GET", task_path)
            raise HTTPException(504, "VOICE_COMPUTE_TRANSCRIPTION_TIMEOUT")
        finally:
            if not completed:
                try:
                    await asyncio.shield(scheduler(connection, "POST", f"{task_path}/cancel", timeout=5))
                except HTTPException:
                    pass
