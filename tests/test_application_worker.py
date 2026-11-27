import asyncio
import base64
import hashlib
import json

from fastapi.testclient import TestClient
from fastapi import HTTPException
import pytest

from vvoice.worker import build_worker
from vvoice.worker_models import SENSEVOICE_LIMITS


def test_model_preparation_route_reaches_the_registration_handler(monkeypatch, tmp_path):
    from contextlib import asynccontextmanager
    from dataclasses import replace

    from fastapi import FastAPI

    from vvoice import compute
    from vvoice.dialogue import Identity

    deployment = "1" * 32
    model = "audiocpp-generaluser-gs-sf2"
    pending = []

    @asynccontextmanager
    async def deployment_change(deployment_id):
        assert deployment_id == deployment
        yield None, f"backend-deployments/{deployment}"

    async def scheduler(_connection, method, path):
        assert method == "GET"
        return {"items": []} if path.endswith("/models") else {"state": "running"}

    async def prepare(key, _path, _status_path, record):
        pending.append((key, record["weight_mode"]))
        compute._preparations.pop(key, None)

    monkeypatch.setattr(compute, "settings", replace(compute.settings, data_dir=tmp_path))
    monkeypatch.setattr(compute, "deployment_change", deployment_change)
    monkeypatch.setattr(compute, "scheduler", scheduler)
    monkeypatch.setattr(compute, "run_preparation", prepare)
    app = FastAPI()
    app.include_router(compute.router)
    app.dependency_overrides[compute._verify_user] = lambda: Identity(subject="fixture", role="system_admin")
    with TestClient(app) as client:
        response = client.post(f"/api/v1/compute/deployments/{deployment}/models",
                               json={"model_id": model, "weight_mode": "shared"})
        assert response.status_code == 202
        assert response.json()["model_id"] == model
    assert pending == [((deployment, model), "shared")]


def test_workbench_copied_model_keeps_native_sidecars_adjacent(monkeypatch, tmp_path):
    from pathlib import Path

    from vvoice import worker_execution

    files = {}
    for role, name in enumerate(("phonon-31m-en-q8_0.gguf", "default-voice.safetensors")):
        source = tmp_path / f"file_{role}" / name
        source.parent.mkdir()
        source.write_bytes(name.encode())
        files[f"mirrors/gradium/phonon-31m-en-audiocpp/{name}"] = str(source)
    operation = tmp_path / "operation.json"
    operation.write_text(json.dumps({"model_id": "audiocpp-gradium-phonon-31m-en-q8", "packages": files}))

    def run(arguments, *, env, check):
        base = Path(env["MODEL_HUB_SHARED_MODELS_PATH"]) / "export/ms/vivibit/v-voice-audiocpp-gguf/current"
        for relative, source in files.items():
            target = base / relative
            assert not target.is_symlink()
            assert target.samefile(source)
        Path(arguments[-1]).write_bytes(b"fixture output")

    monkeypatch.setattr(worker_execution.subprocess, "run", run)
    worker_execution.execute_operation(operation)
    assert (tmp_path / "workbench.zip").read_bytes() == b"fixture output"


def test_worker_copy_verification_and_cancellation(tmp_path, monkeypatch):
    token = "a" * 64
    monkeypatch.setenv("V_SCHEDULER_BACKEND_CHANNEL_TOKEN", token)
    monkeypatch.setenv("VVOICE_DATA_DIR", str(tmp_path))
    encoded = base64.b64encode(json.dumps({
        "mode": "application-backend-v1", "profile": "amd-cpu",
    }).encode()).decode()
    headers = {"Authorization": f"Bearer {token}"}
    channel = "/scheduler"
    data = {"model": ("model.int8.onnx", b"model-bytes"), "tokens": ("tokens.txt", b"1 token")}
    with TestClient(build_worker(encoded)) as client:
        assert client.get("/health").json()["profile"] == "amd-cpu"
        assert client.get("/v1/models", headers=headers).status_code == 404
        assert client.get(channel + "/capabilities").status_code == 401
        assert client.get(channel + "/capabilities", headers=headers).json()["async_models"] == []
        manifest = {"model_id": "sensevoice-int8", "files": [
            {"file_id": role, "path": name, "size_bytes": len(blob), "sha256": hashlib.sha256(blob).hexdigest()}
            for role, (name, blob) in data.items()
        ]}
        response = client.post(channel + "/transfers", json=manifest, headers=headers)
        assert response.status_code == 200
        transfer = channel + "/transfers/" + response.json()["transfer_id"]
        assert client.post(transfer + "/complete", headers=headers).status_code == 409
        for role, (_, blob) in data.items():
            result = client.put(transfer + f"/files/{role}?offset=0", content=blob,
                                headers={**headers, "Content-Type": "application/octet-stream"})
            assert result.json()["received_bytes"] == len(blob)
        assert client.post(transfer + "/complete", headers=headers).json()["verified"] is True
        assert client.get(channel + "/capabilities", headers=headers).json()["async_models"] == [
            {"id": "sensevoice-int8", "task_type": "voice.transcribe", "model_limits": SENSEVOICE_LIMITS},
        ]
        command = {"task_id": "task-one", "fence": 1}
        endpoint = channel + "/executions/attempt-one"
        cancelled = client.post(endpoint + "/cancel", json=command, headers=headers)
        assert cancelled.json()["status"] == "cancelled"
        assert cancelled.json()["stopped"] is True
        assert client.post(endpoint + "/start", json=command, headers=headers).json() == cancelled.json()
        assert client.post(endpoint + "/inspect", json={**command, "fence": 2}, headers=headers).status_code == 409
        assert client.delete(channel + "/transfers/models/sensevoice-int8", headers=headers).json() == {
            "deleted_transfers": 1,
        }


def test_remote_transcription_returns_only_the_selected_execution(monkeypatch):
    import httpx
    from fastapi import FastAPI

    from vvoice import compute
    from vvoice.dialogue import Identity

    deployment = "1" * 32
    executor = "app-remote-fixture"
    attempt = "attempt-one"
    audio = b"test audio bytes"
    model = {
        "deployment_id": deployment, "model_id": "sensevoice-int8",
        "executor_id": executor, "node_id": "selected-orin",
        "profile": "jetson-orin", "task_type": "voice.transcribe",
    }
    observed = []
    actual_node = ["selected-orin"]
    forced = []

    def exchange(request):
        path = request.url.path
        record = {"task_id": "scheduler-task", "executor_id": executor,
                  "attempt_id": attempt, "fence": 1, "node_id": actual_node[0]}
        if path == f"/backend-deployments/{deployment}":
            result = {"app_id": "com.ictrek.v-voice", "state": "running", "config": {"mode": compute.MODE}}
        elif path == f"/backend-deployments/{deployment}/models":
            result = {"items": [model]}
        elif path == "/tasks":
            task = json.loads(request.content)
            assert task["executor"]["id"] == executor
            assert task["parameters"]["sha256"] == hashlib.sha256(audio).hexdigest()
            if task["scheduling"].get("force_admission"):
                assert request.headers["X-VScheduler-Admin-Authorization"] == "Bearer fixture-admin"
                forced.append(True)
            else:
                assert "X-VScheduler-Admin-Authorization" not in request.headers
            observed.append("queued")
            result = {**record, "status": "queued", "attempt_id": None}
        elif path == f"/backend-deployments/{deployment}/executions/{attempt}/inputs/reference":
            assert request.content == audio
            assert request.headers["X-Scheduler-Fence"] == "1"
            observed.append("upload")
            result = {"received_bytes": len(audio)}
        else:
            assert path == "/tasks/scheduler-task"
            result = ({**record, "status": "succeeded", "result": {"text": "fixture transcript"}}
                      if observed[-1] == "upload"
                      else {**record, "status": "assigned"})
            if result["status"] == "assigned":
                observed.append("assign")
        return httpx.Response(200, json={"code": "OK", "data": result})

    monkeypatch.setattr(compute, "client", lambda: httpx.AsyncClient(
        base_url="http://scheduler.test/", transport=httpx.MockTransport(exchange),
    ))
    app = FastAPI()
    app.include_router(compute.router)
    app.dependency_overrides[compute._verify_user] = lambda: Identity(subject="fixture", role="user")
    with TestClient(app) as client:
        for node, code in [("selected-orin", 200), ("other-node", 502)]:
            actual_node[0] = node
            response = client.post("/api/v1/compute/transcriptions",
                                   data={"deployment_id": deployment, "executor_id": executor},
                                   files={"file": ("sample.wav", audio)})
            assert response.status_code == code
            if code == 200:
                assert response.json()["node_id"] == "selected-orin"
                assert response.json()["executor_id"] == executor
            else:
                assert response.json()["detail"] == "VOICE_COMPUTE_PLACEMENT_MISMATCH"
        form = {"deployment_id": deployment, "executor_id": executor, "force_admission": "true"}
        files = {"file": ("sample.wav", audio)}
        response = client.post("/api/v1/compute/transcriptions", data=form, files=files)
        assert response.status_code == 403
        assert response.json()["detail"] == "VOICE_COMPUTE_ADMIN_REQUIRED"
        app.dependency_overrides[compute._verify_user] = lambda: Identity(subject="admin", role="system_admin")
        actual_node[0] = "selected-orin"
        approved = client.post("/api/v1/compute/transcriptions", data=form, files=files,
                               headers={"Authorization": "Bearer fixture-admin"})
        assert approved.status_code == 200
    assert forced == [True]
    assert observed == ["queued", "assign", "upload"] * 3


@pytest.mark.parametrize(('mode', 'shared_ready', 'expected'), [
    ('copy', True, 'copy'),
    ('shared', True, 'shared'),
    ('shared', False, None),
    ('auto', False, 'copy'),
])
def test_weight_mode_is_honored(monkeypatch, tmp_path, mode, shared_ready, expected):
    from dataclasses import replace
    from vvoice import compute

    source = tmp_path / 'model.int8.onnx'
    source.write_bytes(b'fixture')
    manifest = {'file_id': 'model', 'path': source.name, 'size_bytes': 7, 'sha256': '0' * 64}
    monkeypatch.setattr(compute, 'settings', replace(compute.settings, modelhub_root=tmp_path))
    monkeypatch.setattr(compute, 'source_files', lambda _model_id: ([manifest], {'model': source}))
    calls = []

    async def request(_client, method, path, **kwargs):
        calls.append((method, path, kwargs))
        if path.endswith('/model-hub'):
            return {'state': 'ready' if shared_ready else 'unavailable'}
        if path.endswith('/transfers'):
            return {'transfer_id': 'receipt', 'files': [{'file_id': 'model', 'received_bytes': 3}]}
        if method == 'PUT':
            assert kwargs['params'] == {'offset': 3}
            assert kwargs['content'] == b'ture'
            return {'received_bytes': 7}
        if path.endswith('/models'):
            return {'model_id': 'sensevoice-int8'}
        return {}

    monkeypatch.setattr(compute, 'scheduler', request)
    if expected is None:
        with pytest.raises(HTTPException, match='BACKEND_SHARED_MODEL_HUB_UNAVAILABLE'):
            asyncio.run(compute.prepare(None, 'deployment', mode))
        assert len(calls) == 1
        return
    assert asyncio.run(compute.prepare(None, 'deployment', mode))['model_id'] == 'sensevoice-int8'
    transfer = next(kw['json'] for _, path, kw in calls if path.endswith('/transfers'))
    assert transfer.get('source', 'copy') == expected
    assert any(method == 'PUT' for method, _, _ in calls) == (expected == 'copy')
    if mode == 'copy':
        assert all(not path.endswith('/model-hub') for _, path, _ in calls)


def test_speech_output_is_bound_to_selected_node_and_verified(monkeypatch):
    import httpx
    from fastapi import FastAPI
    from vvoice import compute
    from vvoice.dialogue import Identity

    deployment = "2" * 32
    audio = b"test mp3 output"
    digest = hashlib.sha256(audio).hexdigest()
    actual = ["spark-two"]
    reads = []

    def exchange(request):
        path = request.url.path
        if path == f"/backend-deployments/{deployment}":
            result = {"app_id": "com.ictrek.v-voice", "config": {"mode": compute.MODE}}
        elif path.endswith("/models"):
            result = {"items": [{"executor_id": "tts-second", "model_id": "vits-zh",
                                 "node_id": "spark-two", "task_type": "voice.synthesize"}]}
        elif path == "/tasks":
            body = json.loads(request.content)
            assert body["executor"] == {"id": "tts-second", "contract_version": "1", "task_type": "voice.synthesize"}
            assert body["parameters"] == {"input": "测试", "voice": "default"}
            result = {"task_id": "speech-job", "executor_id": "tts-second", "status": "succeeded",
                      "node_id": actual[0], "attempt_id": "attempt", "fence": 1,
                      "result": {"output": {"file_id": "speech.mp3", "size_bytes": len(audio), "sha256": digest}}}
        else:
            assert path == f"/backend-deployments/{deployment}/executions/attempt/outputs/speech.mp3"
            assert request.headers["X-Scheduler-Fence"] == "1"
            reads.append(request.url.params["offset"])
            result = {"offset": 0, "data_b64": base64.b64encode(audio).decode()}
        return httpx.Response(200, json={"code": "OK", "data": result})

    monkeypatch.setattr(compute, "client", lambda: httpx.AsyncClient(
        base_url="http://scheduler.test/", transport=httpx.MockTransport(exchange),
    ))
    app = FastAPI()
    app.include_router(compute.router)
    app.dependency_overrides[compute._verify_user] = lambda: Identity(subject="fixture", role="user")
    body = {"deployment_id": deployment, "executor_id": "tts-second", "input": "测试"}
    with TestClient(app) as client:
        response = client.post("/api/v1/compute/speech", json=body)
        assert response.status_code == 200 and response.content == audio
        assert response.headers["X-Execution-Node"] == "spark-two"
        actual[0] = "spark-other"
        assert client.post("/api/v1/compute/speech", json=body).status_code == 502
    assert reads == ["0"]
