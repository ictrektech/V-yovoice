"""V-Voice 主实例的跨节点转写入口。"""
from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from time import monotonic
from typing import Literal
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from .admission import configuration
from .catalog import find_model, resolve_files
from .config import settings
from .dialogue import Identity, _admin, _verify_user
from .worker import MODE, SENSEVOICE, SENSEVOICE_FILES
from .worker_execution import MAX_AUDIO_BYTES, TASK_TYPE
from .worker_weights import CHUNK_BYTES

router = APIRouter(prefix="/api/v1/compute")
DEPLOYMENT_ID = r"^[a-f0-9]{32}$"
ID = r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,95}$"


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


@router.get("/placements", dependencies=[Depends(_verify_user)])
async def placements():
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
                                               if item["task_type"] == TASK_TYPE)
        names = await node_names(connection) if placements_with_targets else {}
        return {"items": [{**item, "node_name": names.get(target)} for item, target in placements_with_targets]}


@router.get("/deployments", dependencies=[Depends(require_admin)])
async def deployments():
    async with client() as connection:
        access, rows, names = await asyncio.gather(
            scheduler(connection, "GET", f"backend-deployment-access/{settings.app_id}"),
            scheduler(connection, "GET", "backend-deployments"),
            node_names(connection),
        )
    targets = [{**target, "node_name": names.get((target["kind"], target["id"]))}
               for target in access.get("targets", [])]
    return {"targets": targets, "images": access.get("images", {}),
            "deployments": [{**row, "node_name": names.get((row["target_kind"], row["target_id"]))}
                            for row in rows["items"] if worker_deployment(row)]}


class Deploy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["ssh", "cluster"]
    node_id: str = Field(pattern=ID)
    request_key: str = Field(pattern=ID)


@router.post("/deployments", dependencies=[Depends(require_admin)])
async def deploy(data: Deploy):
    async with client() as connection:
        access = await scheduler(connection, "GET", f"backend-deployment-access/{settings.app_id}")
        target = next((row for row in access.get("targets", [])
                       if (row["kind"], row["id"]) == (data.kind, data.node_id)), None)
        image = access.get("images", {}).get(target["profile"]) if target else None
        if not image:
            raise HTTPException(403, "VOICE_COMPUTE_TARGET_UNAVAILABLE")
        return await scheduler(connection, "POST", "backend-deployments", json={
            "request_key": data.request_key, "target": target, "image": image, "container_port": 7070,
            "config": {"mode": MODE, "profile": target["profile"]},
        })


async def require_deployment(connection, deployment_id: str) -> str:
    if len(deployment_id) != 32 or any(char not in "0123456789abcdef" for char in deployment_id):
        raise HTTPException(422, "VOICE_COMPUTE_DEPLOYMENT_INVALID")
    path = f"backend-deployments/{deployment_id}"
    row = await scheduler(connection, "GET", path)
    if not worker_deployment(row):
        raise HTTPException(404, "VOICE_COMPUTE_DEPLOYMENT_NOT_FOUND")
    return path


@router.post("/deployments/{deployment_id}/{action}", dependencies=[Depends(require_admin)])
async def lifecycle(deployment_id: str, action: Literal["start", "stop", "prepare"]):
    async with client() as connection:
        path = await require_deployment(connection, deployment_id)
        if action == "prepare":
            return await prepare(connection, path)
        return await scheduler(connection, "POST", f"{path}/{action}")


@router.delete("/deployments/{deployment_id}", dependencies=[Depends(require_admin)])
async def delete_deployment(deployment_id: str):
    async with client() as connection:
        return await scheduler(connection, "DELETE", await require_deployment(connection, deployment_id))


@router.delete("/deployments/{deployment_id}/models/sensevoice-int8", dependencies=[Depends(require_admin)])
async def delete_model(deployment_id: str):
    async with client() as connection:
        path = await require_deployment(connection, deployment_id)
        return await scheduler(connection, "DELETE", f"{path}/models/{SENSEVOICE}")


def source_files() -> tuple[list[dict], dict[str, Path]]:
    try:
        paths = {role: Path(path) for role, path in resolve_files(find_model(SENSEVOICE, "asr")).items()}
        if {role: path.name for role, path in paths.items()} != SENSEVOICE_FILES:
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


async def prepare(connection: httpx.AsyncClient, path: str):
    files, paths = await asyncio.to_thread(source_files)
    manifest = {"model_id": SENSEVOICE, "files": files}
    base = f"{path}/transfers"
    share = await scheduler(connection, "GET", f"{path}/model-hub")
    if share.get("state") == "ready":
        try:
            shared = [
                {**row, "shared_path": paths[row["file_id"]].relative_to(settings.modelhub_root.resolve()).as_posix()}
                for row in files
            ]
            receipt = await scheduler(connection, "POST", base, json={**manifest, "files": shared, "source": "shared"})
            transfer = receipt["transfer_id"]
            await scheduler(connection, "POST", f"{base}/{transfer}/complete", timeout=310)
            return await scheduler(connection, "POST", f"{path}/models", json={"model_id": SENSEVOICE, "transfer_id": transfer})
        except ValueError:
            pass
        except HTTPException as error:
            if error.detail not in {"BACKEND_SHARED_MODEL_HUB_UNAVAILABLE", "BACKEND_TRANSFER_CONFLICT",
                                    "BACKEND_TRANSFER_NOT_FOUND"}:
                raise
    receipt = await scheduler(connection, "POST", base, json=manifest)
    transfer = receipt["transfer_id"]
    offsets = {item["file_id"]: item["received_bytes"] for item in receipt["files"]}
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
    await scheduler(connection, "POST", f"{base}/{transfer}/complete", timeout=310)
    return await scheduler(connection, "POST", f"{path}/models", json={"model_id": SENSEVOICE, "transfer_id": transfer})


@router.post("/transcriptions", dependencies=[Depends(_verify_user)])
async def transcriptions(
    request: Request,
    deployment_id: str = Form(pattern=DEPLOYMENT_ID),
    executor_id: str = Form(pattern=ID),
    language: str = Form(default="", pattern=r"^[a-zA-Z0-9_-]{0,24}$"),
    file: UploadFile = File(),
):
    data = await file.read(MAX_AUDIO_BYTES + 1)
    fmt = Path(file.filename or "").suffix.lower().lstrip(".")
    if not data or len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "VOICE_COMPUTE_AUDIO_SIZE")
    if fmt not in {"wav", "flac", "mp3", "ogg", "m4a"}:
        raise HTTPException(422, "VOICE_COMPUTE_AUDIO_FORMAT")
    async with client() as connection:
        path = await require_deployment(connection, deployment_id)
        available = await scheduler(connection, "GET", f"{path}/models")
        chosen = next((item for item in available["items"]
                       if item["executor_id"] == executor_id and item["task_type"] == TASK_TYPE), None)
        if not chosen:
            raise HTTPException(409, "VOICE_COMPUTE_PLACEMENT_UNAVAILABLE")
        key = uuid4().hex
        job = await scheduler(connection, "POST", "tasks", headers={"Idempotency-Key": key}, json={
            "protocol_version": 1, "app_task_id": key,
            "executor": {"id": executor_id, "contract_version": "1", "task_type": TASK_TYPE},
            "parameters": {"size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                           "format": fmt, "language": language},
        })
        task_path = f"tasks/{job['task_id']}"
        deadline = monotonic() + 180
        uploaded = False
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
                    return {"deployment_id": deployment_id, "task_id": job["task_id"],
                            "node_id": job["node_id"], "executor_id": executor_id, "transcription": job["result"]}
                if job.get("attempt_id") and state in {"assigned", "running"} and not uploaded:
                    payload_path = f"{path}/executions/{job['attempt_id']}/inputs/reference"
                    for offset in range(0, len(data), CHUNK_BYTES):
                        chunk = data[offset:offset + CHUNK_BYTES]
                        reply = await scheduler(connection, "PUT", payload_path, params={"offset": offset}, content=chunk,
                                                headers={"Content-Type": "application/octet-stream",
                                                         "X-Scheduler-Fence": str(job["fence"])})
                        if reply.get("received_bytes") != offset + len(chunk):
                            raise HTTPException(409, "VOICE_COMPUTE_INPUT_TRANSFER_FAILED")
                    uploaded = True
                await asyncio.sleep(0.5)
                job = await scheduler(connection, "GET", task_path)
            raise HTTPException(504, "VOICE_COMPUTE_TRANSCRIPTION_TIMEOUT")
        finally:
            if not completed:
                try:
                    await asyncio.shield(scheduler(connection, "POST", f"{task_path}/cancel", timeout=5))
                except HTTPException:
                    pass
