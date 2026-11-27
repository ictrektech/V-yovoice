"""同一 V-Voice 镜像的私有 Scheduler worker 入口。"""
from __future__ import annotations

import base64
import hmac
import json
import os
import re
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from .worker_execution import ComputeWorker
from .worker_models import model_ids, model_spec
from .worker_weights import CHUNK_BYTES, MANIFEST_BYTES, Manifest, WeightStore

MODE = "application-backend-v1"
PROFILES = {
    "amd-cpu": "amd",
    "amd-cuda": "amd-cuda",
    "arm-cpu": "arm",
    "arm-cuda": "arm-cuda",
    "jetson-orin": "l4t",
    "jetson-thor": "thor",
    "dgx-spark": "thor",
}


async def bounded_body(request: Request, maximum: int) -> bytes:
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > maximum:
            raise HTTPException(413, "WORKER_REQUEST_TOO_LARGE")
        data.extend(chunk)
    if not data:
        raise HTTPException(422, "WORKER_REQUEST_EMPTY")
    return bytes(data)


def build_worker(encoded: str) -> FastAPI:
    config = json.loads(base64.b64decode(encoded, validate=True))
    token = os.environ.get("V_SCHEDULER_BACKEND_CHANNEL_TOKEN", "")
    if (
        not isinstance(config, dict) or config.get("mode") != MODE
        or config.get("profile") not in PROFILES or not re.fullmatch(r"[a-f0-9]{64}", token)
    ):
        raise ValueError("invalid V-Voice worker settings")
    profile = PROFILES[config["profile"]]
    provider = "cpu" if profile in {"amd", "arm"} else "cuda"
    threads = 4
    root = Path(os.getenv("VVOICE_DATA_DIR", "/data")) / "worker"
    store = WeightStore(root / "weights", Path("/modelhub-shared"))
    executions = ComputeWorker(root / "attempts", store, provider, threads)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=executions.lifespan)

    def authorized(authorization: str = Header(default="")) -> None:
        if not hmac.compare_digest(authorization.encode(), ("Bearer " + token).encode()):
            raise HTTPException(401, "WORKER_CHANNEL_REQUIRED")

    channel = [Depends(authorized)]

    @app.get("/health")
    def health():
        return {"status": "ok", "mode": MODE, "profile": config["profile"]}

    @app.get("/scheduler/model-hub", dependencies=channel)
    def model_hub():
        return {"state": "ready" if store.shared_available() else "unavailable"}

    @app.get("/scheduler/capabilities", dependencies=channel)
    def capabilities():
        return {
            "protocol_version": 1,
            "execution_settings": {"provider": provider, "num_threads": threads},
            "async_models": [
                {"id": model_id, "task_type": task_type, "model_limits": limits}
                for model_id in model_ids() if store.ready(model_id)
                for task_type, _, limits in (model_spec(model_id),)
            ],
            "weight_model_delete": True,
        }

    @app.post("/scheduler/transfers", dependencies=channel)
    async def begin(request: Request):
        try:
            manifest = Manifest.model_validate_json(await bounded_body(request, MANIFEST_BYTES))
        except ValidationError:
            raise HTTPException(422, "INVALID_WEIGHT_MANIFEST") from None
        files = {row.file_id: row.path for row in manifest.files}
        try:
            expected = model_spec(manifest.model_id)[1]
        except KeyError:
            expected = {}
        if files != expected:
            raise HTTPException(422, "WORKER_MODEL_UNSUPPORTED")
        return await run_in_threadpool(store.begin, manifest)

    @app.get("/scheduler/transfers/{transfer_id}", dependencies=channel)
    def transfer(transfer_id: str):
        return store.status(transfer_id)

    @app.put("/scheduler/transfers/{transfer_id}/files/{file_id}", dependencies=channel)
    async def append(transfer_id: str, file_id: str, offset: Annotated[int, Query(ge=0)], request: Request):
        if request.headers.get("content-type") != "application/octet-stream":
            raise HTTPException(415, "INVALID_WEIGHT_CONTENT_TYPE")
        data = await bounded_body(request, CHUNK_BYTES)
        return await run_in_threadpool(store.write, transfer_id, file_id, offset, data)

    @app.post("/scheduler/transfers/{transfer_id}/complete", dependencies=channel)
    def complete(transfer_id: str):
        return store.complete(transfer_id)

    @app.delete("/scheduler/transfers/models/{model_id}", dependencies=channel)
    def delete(model_id: str):
        return store.delete(model_id)

    @app.post("/scheduler/executions/{attempt_id}/{action}", dependencies=channel)
    async def command(attempt_id: str, action: Literal["start", "inspect", "cancel"], request: Request):
        try:
            body = json.loads(await bounded_body(request, MANIFEST_BYTES))
            if not isinstance(body, dict):
                raise ValueError()
        except (ValueError, UnicodeError):
            raise HTTPException(422, "INVALID_WORKER_COMMAND") from None
        return await run_in_threadpool(executions.command, attempt_id, action, body)

    @app.put("/scheduler/executions/{attempt_id}/inputs/reference", dependencies=channel)
    async def reference(attempt_id: str, offset: Annotated[int, Query(ge=0)], request: Request):
        if request.headers.get("content-type") != "application/octet-stream":
            raise HTTPException(415, "INVALID_WORKER_INPUT_CONTENT_TYPE")
        data = await bounded_body(request, CHUNK_BYTES)
        return await run_in_threadpool(executions.write_input, attempt_id, offset, data)

    @app.get("/scheduler/executions/{attempt_id}/outputs/{file_id}", dependencies=channel)
    def output(attempt_id: str, file_id: Literal["speech.mp3", "embedding.json", "workbench.zip"],
               offset: Annotated[int, Query(ge=0)]):
        return executions.read_output(attempt_id, file_id, offset)

    return app
