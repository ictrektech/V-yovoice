"""大模型的后台校验不得阻塞目录，也不能提前向网关公开。"""
import asyncio
import hashlib
import os
from threading import Event
import time
from types import SimpleNamespace

from vvoice import catalog as catalog_module, main, modelhub


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
