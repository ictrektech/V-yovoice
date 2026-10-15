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
