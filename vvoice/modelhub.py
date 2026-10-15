from __future__ import annotations

from typing import Any
import asyncio

import httpx

from .catalog import catalog, model_files_ready, model_root
from .config import settings


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
    for item in catalog():
        repo = item["modelscope_repo"]
        root = model_root(item)
        state = hub.get(repo, {})
        descriptor_installed = (root / "vvoice-model.json").is_file() or (
            item.get("backend") == "audio.cpp" and any((root / f["path"]).is_file() for f in item.get("shared_files", []))
        )
        ready, validation_error = await asyncio.to_thread(model_files_ready, item) if descriptor_installed else (False, "")
        hub_status = str(state.get("status") or "not_installed").lower()
        if ready:
            status = "ready"
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
    if item.get("shared_files") and all((root / file["path"]).is_file() for file in item["shared_files"]):
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
