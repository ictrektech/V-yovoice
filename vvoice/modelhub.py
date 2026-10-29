from __future__ import annotations

# V-Scheduler 内置模型仓库客户端；模块名和配置键保留兼容，不依赖独立 Model Hub 应用。

from typing import Any
import asyncio
from concurrent.futures import Future
from itertools import count
from queue import PriorityQueue
from threading import Lock, Thread

import httpx

from .catalog import catalog, model_files_ready, model_root, shared_files_for
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
        for file in shared_files_for(item, root):
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


def _error_detail(response) -> str:
    try:
        body = response.json() or {}
    except ValueError:
        return ""
    if not isinstance(body, dict):
        return ""
    error = body.get("error")
    message = error.get("message") if isinstance(error, dict) else ""
    return str(body.get("detail") or message or "")


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


async def list_models(items: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    items = catalog() if items is None else items
    hub = await states()
    result = []
    # 小模型优先，避免一个大权重阻塞旧 ASR 目录和所有其他已安装模型。
    checks = {item["key"]: _shared_status(item) for item in sorted(
        (row for row in items if row.get("backend") == "audio.cpp"),
        key=lambda row: sum(file["size"] for file in row["shared_files"]))}
    for item in items:
        repo = item["modelscope_repo"]
        root = model_root(item)
        state = hub.get(repo, {})
        descriptor_installed = (root / "vvoice-model.json").is_file() or (
            item.get("backend") == "audio.cpp" and any((root / f["path"]).is_file() for f in item.get("shared_files", []))
        )
        ready, validation_error = (checks[item["key"]] if item.get("backend") == "audio.cpp"
                                   else await asyncio.to_thread(model_files_ready, item)) if descriptor_installed else (False, "")
        hub_status = str(state.get("status") or "not_installed").lower()
        # 一个共享仓库含多个模型，不能把其他已下载文件或其他任务的状态当成本模型就绪。
        selected = state.get("files")
        paths = {file["path"] for file in item.get("shared_files", [])}
        # 整仓任务未记录文件范围时会下载仓库内全部模型；但失败无法归因到某个精度，
        # 只有本地已有该模型文件或任务明确包含其文件时才报告未完成。
        active_task = not selected or bool(set(selected) & paths)
        failed_task = descriptor_installed or (hub_status == "failed" and bool(selected) and bool(set(selected) & paths))
        if ready:
            status = "ready"
        elif ready is None:
            status = "verifying"
        elif hub_status in {"downloading", "pending", "verifying"} and active_task:
            status = "downloading"
        elif failed_task:
            status = "failed"
        else:
            status = "not_installed"
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


class ImportRequiredError(ValueError):
    """仅导入模型不能生成一个不存在的远程下载任务。"""


def management_catalog():
    from .creative import models as creative_models
    speech = catalog()
    keys = {row['key'] for row in speech}
    return [*speech, *(row for row in creative_models(include_non_speech=True) if row['key'] not in keys)]


async def pull_model(key: str, force: bool = False) -> dict[str, Any]:
    item = next((row for row in management_catalog() if row["key"] == key), None)
    if item is None:
        raise KeyError(key)
    if item.get("import_required"):
        raise ImportRequiredError("Model requires administrator-provided weights in V-Scheduler")
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
        pull_url = f"{settings.model_hub_api_url}/api/v1/models/pull"
        if item.get("shared_files") and force:
            # 更新保留整个仓库已下载的文件范围，不以一个精度替换其他已安装模型。
            response = await client.post(f"{settings.model_hub_api_url}/api/v1/models/update", params={"model_id": f"ms://{item['modelscope_repo']}"})
            if response.status_code == 400 and "only ready models can be updated" in _error_detail(response):
                # 上次失败后整个仓库不是 ready，无法更新；改为只补下载当前模型文件。
                response = await client.post(pull_url, json={key: value for key, value in payload.items() if key != "append"})
        else:
            response = await client.post(pull_url, json=payload)
            if response.status_code == 400 and payload.get("append") and "append requires a ready model" in _error_detail(response):
                # 共享仓库上次失败后不能追加；改为只下载当前模型文件，让失败可以重试。
                response = await client.post(pull_url, json={key: value for key, value in payload.items() if key != "append"})
    if response.status_code == 409:
        return {"status": "active", "detail": response.json().get("detail", "")}
    response.raise_for_status()
    return response.json()


async def cancel_model(key: str) -> dict[str, Any]:
    item = next((row for row in management_catalog() if row["key"] == key), None)
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
            if item.get("shared_files") and not ({file["path"] for file in item["shared_files"]} & set(task.get("files") or [])):
                continue
            response = await client.post(f"{settings.model_hub_api_url}/api/v1/tasks/{task['task_id']}/cancel")
            response.raise_for_status()
            cancelled.append(task["task_id"])
    return {"status": "cancelled" if cancelled else "not_running", "tasks": cancelled}
