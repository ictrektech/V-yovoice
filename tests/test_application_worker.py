import base64
import hashlib
import json

from fastapi.testclient import TestClient

from vvoice.worker import SENSEVOICE_LIMITS, build_worker


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
    assert observed == ["queued", "assign", "upload", "queued", "assign", "upload"]
