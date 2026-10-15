from __future__ import annotations

from typing import Any
import asyncio
from concurrent.futures import Future
from itertools import count
from queue import PriorityQueue
from threading import Lock, Thread

import httpx

from .catalog import catalog, model_files_ready, model_root
from .config import settings


_verification_jobs = PriorityQueue()
_verification_futures = {}
_verification_lock = Lock()
_verification_order = count()
_verification_started = False


def _verify_worker():
    while True:
        _, _, item, future = _verification_jobs.get()
        if not future.set_running_or_notify_cancel():
            _verification_jobs.task_done()
            continue
        try:
            future.set_result(model_files_ready(item))
        except Exception:
            future.set_result((False, "Shared model verification failed"))
        finally:
            _verification_jobs.task_done()


def _shared_status(item):
    """目录立即返回校验中；后台最多两个读者，验证成功前绝不公开模型。"""
    global _verification_started
    root = model_root(item)
    fingerprint = []
    try:
        for file in item["shared_files"]:
            path = (root / file["path"]).resolve()
            stat = path.stat()
            if not path.is_file() or stat.st_size != file["size"]:
                return False, "shared model file size mismatch"
            fingerprint.append((str(path), stat.st_size, stat.st_mtime_ns, file["sha256"]))
    except (FileNotFoundError, OSError):
        return False, "shared model files are incomplete"
    fingerprint = tuple(fingerprint)
    with _verification_lock:
        cached = _verification_futures.get(item["key"])
        if cached is None or cached[0] != fingerprint:
            if cached is not None:
                cached[1].cancel()
            if not _verification_started:
                for _ in range(2):
                    Thread(target=_verify_worker, daemon=True).start()
                _verification_started = True
            future = Future()
            _verification_futures[item["key"]] = (fingerprint, future)
            _verification_jobs.put((sum(file["size"] for file in item["shared_files"]), next(_verification_order), item, future))
        else:
            future = cached[1]
    return future.result() if future.done() else (None, "")


def _clean_id(value: Any) -> str:
    return str(value or "").removeprefix("ms://").removeprefix("hf://")


async def states() -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            models, tasks = await _modelhub_lists(client)
    except httpx.HTTPError:
        return result
    for row in models:
        result[_clean_id(row.get("model_id"))] = dict(row)
    for task in tasks:
        repo = _clean_id(task.get("model_id"))
        current = result.setdefault(repo, {})
        phase = str(task.get("phase") or "").upper()
        if phase in {"PENDING", "DOWNLOADING", "VERIFYING", "FAILED"}:
            current.update(task)
            current["status"] = "failed" if phase == "FAILED" else "downloading"
    return result


async def _modelhub_lists(client: httpx.AsyncClient) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    models_response = await client.get(f"{settings.model_hub_api_url}/api/v1/models", params={"status": "all"})
    models_response.raise_for_status()
    tasks_response = await client.get(f"{settings.model_hub_api_url}/api/v1/tasks")
    tasks_response.raise_for_status()
    return models_response.json(), tasks_response.json()


async def list_models() -> list[dict[str, Any]]:
    hub = await states()
    result = []
    # 小模型优先，避免一个大权重阻塞旧 ASR 目录和所有其他已安装模型。
    checks = {item["key"]: _shared_status(item) for item in sorted(
        (row for row in catalog() if row.get("backend") == "audio.cpp"),
        key=lambda row: sum(file["size"] for file in row["shared_files"]))}
    for item in catalog():
        repo = item["modelscope_repo"]
        root = model_root(item)
        state = hub.get(repo, {})
        descriptor_installed = (root / "vvoice-model.json").is_file() or (
            item.get("backend") == "audio.cpp" and any((root / f["path"]).is_file() for f in item.get("shared_files", []))
        )
        ready, validation_error = (checks[item["key"]] if item.get("backend") == "audio.cpp"
                                   else await asyncio.to_thread(model_files_ready, item)) if descriptor_installed else (False, "")
        hub_status = str(state.get("status") or "not_installed").lower()
        if ready:
            status = "ready"
        elif ready is None:
            status = "verifying"
        elif descriptor_installed and hub_status not in {"downloading", "pending", "verifying"}:
            status = "failed"
        else:
            status = hub_status
        result.append({
            **{key: value for key, value in item.items() if key != "runtime"},
            "status": status,
            "progress": state.get("progress"),
            "downloaded_bytes": state.get("downloaded_bytes"),
            "total_bytes": state.get("total_bytes") or state.get("size"),
            "error": state.get("error_msg") or validation_error,
            "path": str(root),
        })
    return result


async def pull_model(key: str, force: bool = False) -> dict[str, Any]:
    item = next((row for row in catalog() if row["key"] == key), None)
    if item is None:
        raise KeyError(key)
    root = model_root(item)
    if not force and item.get("shared_files") and all((root / file["path"]).is_file() for file in item["shared_files"]):
        ready, _ = await asyncio.to_thread(model_files_ready, item)
        force = force or not ready
    if not force and (root / "vvoice-model.json").is_file():
        ready, _ = await asyncio.to_thread(model_files_ready, item)
        force = not ready
    payload = {"source": "ms", "model_id": item["modelscope_repo"], "name": item["name"], "force": force}
    if item.get("shared_files"):
        payload.update(files=[file["path"] for file in item["shared_files"]], append=True, force=False)
    async with httpx.AsyncClient(timeout=30) as client:
        if item.get("shared_files") and force:
            # 更新保留整个仓库已下载的文件范围，不以一个精度替换其他已安装模型。
            response = await client.post(f"{settings.model_hub_api_url}/api/v1/models/update", params={"model_id": f"ms://{item['modelscope_repo']}"})
        else:
            response = await client.post(f"{settings.model_hub_api_url}/api/v1/models/pull", json=payload)
    if response.status_code == 409:
        return {"status": "active", "detail": response.json().get("detail", "")}
    response.raise_for_status()
    return response.json()


async def cancel_model(key: str) -> dict[str, Any]:
    item = next((row for row in catalog() if row["key"] == key), None)
    if item is None:
        raise KeyError(key)
    async with httpx.AsyncClient(timeout=30) as client:
        _, tasks = await _modelhub_lists(client)
        cancelled = []
        for task in tasks:
            if _clean_id(task.get("model_id")) != item["modelscope_repo"]:
                continue
            if str(task.get("phase") or "").upper() not in {"PENDING", "DOWNLOADING", "VERIFYING"}:
                continue
            response = await client.post(f"{settings.model_hub_api_url}/api/v1/tasks/{task['task_id']}/cancel")
            response.raise_for_status()
            cancelled.append(task["task_id"])
    return {"status": "cancelled" if cancelled else "not_running", "tasks": cancelled}
