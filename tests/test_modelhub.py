from __future__ import annotations

import asyncio

from vvoice import modelhub


def test_list_does_not_report_incomplete_cached_model_as_ready(monkeypatch, tmp_path) -> None:
    item = {
        "key": "zipformer-en",
        "name": "Zipformer",
        "kind": "asr",
        "modelscope_repo": "vivibit/v-voice-zipformer-en-int8",
    }
    (tmp_path / "vvoice-model.json").touch()

    async def fake_states():
        return {item["modelscope_repo"]: {"status": "ready"}}

    monkeypatch.setattr(modelhub, "catalog", lambda: [item])
    monkeypatch.setattr(modelhub, "states", fake_states)
    monkeypatch.setattr(modelhub, "model_root", lambda _: tmp_path)
    monkeypatch.setattr(modelhub, "model_files_ready", lambda _: (False, "missing bpe.vocab"))

    rows = asyncio.run(modelhub.list_models())

    assert rows[0]["status"] == "failed"
    assert rows[0]["error"] == "missing bpe.vocab"


def test_pull_forces_refresh_when_installed_model_is_incomplete(monkeypatch, tmp_path) -> None:
    item = {
        "key": "zipformer-en",
        "name": "Zipformer",
        "modelscope_repo": "vivibit/v-voice-zipformer-en-int8",
    }
    (tmp_path / "vvoice-model.json").touch()
    captured = {}

    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"status": "queued"}

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, json):
            captured.update(json)
            return Response()

    monkeypatch.setattr(modelhub, "catalog", lambda: [item])
    monkeypatch.setattr(modelhub, "model_root", lambda _: tmp_path)
    monkeypatch.setattr(modelhub, "model_files_ready", lambda _: (False, "missing bpe.vocab"))
    monkeypatch.setattr(modelhub.httpx, "AsyncClient", Client)

    result = asyncio.run(modelhub.pull_model("zipformer-en"))

    assert result == {"status": "queued"}
    assert captured["force"] is True


def test_shared_repair_keeps_other_installed_precisions(monkeypatch, tmp_path) -> None:
    item = {"key": "creative-q8", "name": "Creative", "modelscope_repo": "vivibit/creative",
            "shared_files": [{"path": "creative-q8.gguf"}]}
    (tmp_path / "creative-q8.gguf").touch()
    captured = {}

    class Response:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"status": "queued"}

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, **kwargs):
            captured.update(url=url, **kwargs)
            return Response()

    monkeypatch.setattr(modelhub, "catalog", lambda: [item])
    monkeypatch.setattr(modelhub, "model_root", lambda _: tmp_path)
    monkeypatch.setattr(modelhub, "model_files_ready", lambda _: (False, "checksum mismatch"))
    monkeypatch.setattr(modelhub.httpx, "AsyncClient", Client)

    assert asyncio.run(modelhub.pull_model("creative-q8")) == {"status": "queued"}
    assert captured["url"].endswith("/api/v1/models/update")
    assert captured["params"] == {"model_id": "ms://vivibit/creative"}
    assert "json" not in captured


def _repo_items() -> list[dict]:
    return [
        {"key": "voice-q8", "name": "Voice Q8", "modelscope_repo": "vivibit/voice",
         "shared_files": [{"path": "voice-q8.gguf", "size": 2}]},
        {"key": "voice-q4", "name": "Voice Q4", "modelscope_repo": "vivibit/voice",
         "shared_files": [{"path": "voice-q4.gguf", "size": 1}]},
    ]


def test_failed_whole_repo_task_does_not_claim_variants_never_downloaded(monkeypatch, tmp_path) -> None:
    async def fake_states():
        return {"vivibit/voice": {"status": "failed", "files": None, "error_msg": "network reset"}}

    monkeypatch.setattr(modelhub, "states", fake_states)
    monkeypatch.setattr(modelhub, "model_root", lambda _: tmp_path)

    rows = asyncio.run(modelhub.list_models(_repo_items()))

    assert [row["status"] for row in rows] == ["not_installed", "not_installed"]


def test_failed_task_scoped_to_another_variant_only_marks_its_files(monkeypatch, tmp_path) -> None:
    async def fake_states():
        return {"vivibit/voice": {"status": "failed", "files": ["voice-q4.gguf"], "error_msg": "network reset"}}

    monkeypatch.setattr(modelhub, "states", fake_states)
    monkeypatch.setattr(modelhub, "model_root", lambda _: tmp_path)

    rows = asyncio.run(modelhub.list_models(_repo_items()))

    assert [row["status"] for row in rows] == ["not_installed", "failed"]


def test_whole_repo_download_reports_every_variant_as_downloading(monkeypatch, tmp_path) -> None:
    async def fake_states():
        return {"vivibit/voice": {"status": "downloading", "files": None}}

    monkeypatch.setattr(modelhub, "states", fake_states)
    monkeypatch.setattr(modelhub, "model_root", lambda _: tmp_path)

    rows = asyncio.run(modelhub.list_models(_repo_items()))

    assert [row["status"] for row in rows] == ["downloading", "downloading"]


class _Response:
    def __init__(self, status_code: int = 200, body: dict | None = None):
        self.status_code = status_code
        self._body = body or {"status": "queued"}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError("fallback should have replaced the failed response")

    def json(self):
        return self._body


def _client(monkeypatch, responses):
    calls = []

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, **kwargs):
            calls.append((url, kwargs))
            return responses.pop(0)

    monkeypatch.setattr(modelhub.httpx, "AsyncClient", Client)
    return calls


def test_pull_retries_without_append_when_shared_repository_failed(monkeypatch, tmp_path) -> None:
    item = {"key": "creative-q8", "name": "Creative", "modelscope_repo": "vivibit/creative",
            "shared_files": [{"path": "creative-q8.gguf"}]}
    responses = [_Response(400, {"detail": "append requires a ready model"}), _Response()]
    calls = _client(monkeypatch, responses)
    monkeypatch.setattr(modelhub, "catalog", lambda: [item])
    monkeypatch.setattr(modelhub, "model_root", lambda _: tmp_path)
    monkeypatch.setattr(modelhub, "model_files_ready", lambda _: (True, ""))

    assert asyncio.run(modelhub.pull_model("creative-q8")) == {"status": "queued"}
    assert len(calls) == 2
    assert calls[0][1]["json"]["append"] is True
    assert "append" not in calls[1][1]["json"]
    assert calls[1][1]["json"]["files"] == ["creative-q8.gguf"]


def test_pull_retries_without_update_when_shared_repository_failed(monkeypatch, tmp_path) -> None:
    item = {"key": "creative-q8", "name": "Creative", "modelscope_repo": "vivibit/creative",
            "shared_files": [{"path": "creative-q8.gguf"}]}
    (tmp_path / "creative-q8.gguf").touch()
    responses = [_Response(400, {"detail": "only ready models can be updated"}), _Response()]
    calls = _client(monkeypatch, responses)
    monkeypatch.setattr(modelhub, "catalog", lambda: [item])
    monkeypatch.setattr(modelhub, "model_root", lambda _: tmp_path)
    monkeypatch.setattr(modelhub, "model_files_ready", lambda _: (False, "checksum mismatch"))

    assert asyncio.run(modelhub.pull_model("creative-q8")) == {"status": "queued"}
    assert len(calls) == 2
    assert calls[0][0].endswith("/api/v1/models/update")
    assert calls[1][0].endswith("/api/v1/models/pull")
    assert "append" not in calls[1][1]["json"]
