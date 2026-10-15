"""大模型的后台校验不得阻塞目录，也不能提前向网关公开。"""
import asyncio
import hashlib
import os
from threading import Event
import time
from types import SimpleNamespace

from vvoice import catalog as catalog_module, main, modelhub
import httpx
import pytest


def test_import_only_pull_never_contacts_model_hub(monkeypatch):
    item = {"key": "audiocpp-import-only", "import_required": True}
    monkeypatch.setattr(modelhub, "catalog", lambda: [item])
    def unexpected_client(*args, **kwargs):
        raise AssertionError("import-only model contacted Model Hub")
    monkeypatch.setattr(modelhub.httpx, "AsyncClient", unexpected_client)
    for force in (False, True):
        with pytest.raises(modelhub.ImportRequiredError):
            asyncio.run(modelhub.pull_model(item["key"], force))


def test_shared_download_cancellation_only_matches_selected_files(monkeypatch):
    item = {"key": "selected", "modelscope_repo": "vivibit/shared", "shared_files": [{"path": "selected.gguf"}]}
    tasks = [
        {"task_id": "match", "model_id": "ms://vivibit/shared", "phase": "DOWNLOADING", "files": ["selected.gguf"]},
        {"task_id": "other-model", "model_id": "ms://vivibit/shared", "phase": "DOWNLOADING", "files": ["other.gguf"]},
        {"task_id": "unknown-files", "model_id": "ms://vivibit/shared", "phase": "DOWNLOADING"},
        {"task_id": "finished", "model_id": "ms://vivibit/shared", "phase": "COMPLETED", "files": ["selected.gguf"]},
        {"task_id": "other-repo", "model_id": "ms://vivibit/other", "phase": "DOWNLOADING", "files": ["selected.gguf"]},
    ]
    cancelled = []
    async def lists(client):
        return [], tasks
    async def post(request):
        cancelled.append(request.url.path)
        return httpx.Response(200, json={"status": "cancelled"})
    client_class = httpx.AsyncClient
    monkeypatch.setattr(modelhub, "catalog", lambda: [item])
    monkeypatch.setattr(modelhub, "_modelhub_lists", lists)
    monkeypatch.setattr(modelhub.httpx, "AsyncClient", lambda **kwargs: client_class(transport=httpx.MockTransport(post)))
    assert asyncio.run(modelhub.cancel_model("selected"))["tasks"] == ["match"]
    assert cancelled == ["/api/v1/tasks/match/cancel"]


def test_ready_repository_does_not_make_missing_model_files_ready(monkeypatch, tmp_path):
    item = {"key": "not-downloaded", "backend": "audio.cpp", "modelscope_repo": "vivibit/shared",
            "shared_files": [{"path": "missing.gguf", "size": 4, "sha256": "0" * 64}]}

    async def states():
        return {"vivibit/shared": {"status": "ready"}}

    monkeypatch.setattr(modelhub, "model_root", lambda _: tmp_path)
    monkeypatch.setattr(modelhub, "states", states)
    assert asyncio.run(modelhub.list_models([item]))[0]["status"] == "not_installed"


def test_download_state_is_scoped_to_selected_model_files(monkeypatch, tmp_path):
    item = {"key": "other-model", "backend": "audio.cpp", "modelscope_repo": "vivibit/shared",
            "shared_files": [{"path": "other.gguf", "size": 4, "sha256": "0" * 64}]}

    async def states():
        return {"vivibit/shared": {"status": "downloading", "files": ["selected.gguf"]}}

    monkeypatch.setattr(modelhub, "model_root", lambda _: tmp_path)
    monkeypatch.setattr(modelhub, "states", states)
    assert asyncio.run(modelhub.list_models([item]))[0]["status"] == "not_installed"


def test_atomic_export_change_does_not_reuse_another_revision_hash(monkeypatch, tmp_path):
    monkeypatch.setattr(catalog_module, "settings", SimpleNamespace(modelhub_root=tmp_path))
    repo = tmp_path / "export/ms/vivibit/test"
    repo.mkdir(parents=True)
    for revision, data in [("one", b"good"), ("two", b"evil")]:
        root = repo / revision
        root.mkdir()
        file = root / "model.gguf"
        file.write_bytes(data)
        os.utime(file, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
    current = repo / "current"
    current.symlink_to(repo / "one")
    item = {"modelscope_repo": "vivibit/test", "runtime": {"files": {"model": "model.gguf"}},
            "shared_files": [{"path": "model.gguf", "size": 4, "sha256": hashlib.sha256(b"good").hexdigest()}]}
    assert catalog_module.model_files_ready(item)[0]
    current.unlink()
    current.symlink_to(repo / "two")
    assert not catalog_module.model_files_ready(item)[0]


def test_large_model_verification_is_nonblocking_coalesced_and_fail_closed(monkeypatch, tmp_path):
    path = tmp_path / "model.gguf"
    path.write_bytes(b"good")
    item = {"key": "test-background-model", "name": "Test", "kind": "tts", "backend": "audio.cpp",
            "family": "kokoro_tts", "modelscope_repo": "vivibit/test",
            "shared_files": [{"path": path.name, "size": 4, "sha256": hashlib.sha256(b"good").hexdigest()}]}
    release = Event()
    calls = []

    async def states():
        return {}

    def verify(_):
        calls.append(True)
        assert release.wait(5)
        return (True, "") if path.read_bytes() == b"good" else (False, "checksum mismatch")

    monkeypatch.setattr(modelhub, "catalog", lambda: [item])
    monkeypatch.setattr(modelhub, "model_root", lambda _: tmp_path)
    monkeypatch.setattr(modelhub, "states", states)
    monkeypatch.setattr(modelhub, "model_files_ready", verify)
    monkeypatch.setattr(main, "list_models", modelhub.list_models)
    try:
        assert asyncio.run(modelhub.list_models())[0]["status"] == "verifying"
        assert asyncio.run(main.discovery())["models"] == []
        release.set()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if asyncio.run(modelhub.list_models())[0]["status"] == "ready":
                break
            time.sleep(0.01)
        assert len(asyncio.run(main.discovery())["models"]) == 1
        assert len(calls) == 1
        path.write_bytes(b"evil")
        os.utime(path, ns=(path.stat().st_atime_ns, path.stat().st_mtime_ns + 1_000_000_000))
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if asyncio.run(modelhub.list_models())[0]["status"] == "failed":
                break
            time.sleep(0.01)
        assert asyncio.run(main.discovery())["models"] == []
        assert len(calls) == 2
    finally:
        release.set()
