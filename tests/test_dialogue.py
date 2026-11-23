from __future__ import annotations

import asyncio
import base64
import contextlib
import dataclasses
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from vvoice.config import settings
from vvoice.dialogue import (
    MODEL_KEY,
    DialogueError,
    DialogueManager,
    DialogueSession,
    ResidentLease,
    Ticket,
    TicketStore,
    _process_start_ticks,
)


def _worker(tmp_path: Path) -> Path:
    path = tmp_path / "speech"
    path.write_text(
        f"""#!{sys.executable}
import base64
import json
import sys

print(json.dumps({{"type":"ready","protocol":4,"model":{{"name":"haru-4b","task":"dialogue","sample_rate":24000,"frame_samples":3200}}}}), flush=True)
for line in sys.stdin:
    value = json.loads(line)
    if value.get("type") == "dialogue":
        print(json.dumps({{"type":"chunk","id":value["id"],"seq":0,"pcm":base64.b64encode(b"\\0" * 6400).decode(),"text":"hello"}}), flush=True)
    elif value.get("type") == "hang_up":
        print(json.dumps({{"type":"end","id":value["id"],"frames":1,"samples":3200}}), flush=True)
""",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def _manager(tmp_path: Path, seconds: int = 120) -> DialogueManager:
    worker = _worker(tmp_path)
    model = tmp_path / "Haru-4B-Q8_0.gguf"
    with model.open("wb") as handle:
        handle.truncate(6623102720)
    config = dataclasses.replace(
        settings,
        profile="l4t",
        data_dir=tmp_path / "data",
        haru_worker_path=worker,
        haru_model_path=model,
        dialogue_idle_unload_seconds=seconds,
    )
    return DialogueManager(config)


@pytest.mark.parametrize("profile", ["amd-cuda", "l4t", "thor"])
def test_dialogue_is_supported_on_cuda_profiles(tmp_path, profile):
    manager = _manager(tmp_path)
    manager.config = dataclasses.replace(manager.config, profile=profile)

    assert manager.supported


@pytest.mark.parametrize("profile", ["amd", "arm", "arm-cuda", "local"])
def test_dialogue_is_not_supported_on_cpu_profiles(tmp_path, profile):
    manager = _manager(tmp_path)
    manager.config = dataclasses.replace(manager.config, profile=profile)

    assert not manager.supported


def test_ticket_is_single_use_and_bound_to_user():
    store = TicketStore()
    ticket, _ = store.issue("alice", "en", "companion", 180)
    with pytest.raises(DialogueError):
        store.consume(ticket, "bob")
    with pytest.raises(DialogueError):
        store.consume(ticket, "alice")


@pytest.mark.asyncio
async def test_worker_loads_once_and_serves_sequential_sessions(tmp_path, monkeypatch):
    monkeypatch.setenv("VVOICE_SCHEDULER_REQUIRED", "false")
    manager = _manager(tmp_path)
    try:
        first = await manager.open_session(Ticket("alice", "en", "companion", 180))
        await first.hang_up()
        events = [await asyncio.wait_for(first.events.get(), 2) for _ in range(3)]
        assert [event[0] for event in events] == ["text", "audio", "end"]
        assert events[1][1] == b"\0" * 6400

        second = await manager.open_session(Ticket("alice", "en", "study", 180))
        await second.hang_up()
        events = [await asyncio.wait_for(second.events.get(), 2) for _ in range(3)]
        assert [event[0] for event in events] == ["text", "audio", "end"]
        assert manager.state == "ready_idle"
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_overload_monitor_waits_for_worker_output():
    class Worker:
        async def send(self, value):
            return None

    failed = []

    async def failed_session(session):
        failed.append(session)

    manager = SimpleNamespace(
        config=SimpleNamespace(dialogue_idle_session_seconds=15),
        worker=Worker(),
        _session_failed=failed_session,
    )
    session = DialogueSession(manager, "session", "en", "companion", 180)
    monitor = asyncio.create_task(session._monitor())
    try:
        await session.push(b"\0" * 6400)
        await asyncio.sleep(1.2)
        assert session.events.empty()
        assert not failed

        await session.on_chunk({"pcm": base64.b64encode(b"\0" * 6400).decode()})
        await asyncio.sleep(1.2)
        kind, value = await asyncio.wait_for(session.events.get(), 2)
        assert kind == "audio"
        kind, value = await asyncio.wait_for(session.events.get(), 2)
        assert kind == "error"
        assert value[0] == "dialogue_overloaded"
        assert failed == [session]
    finally:
        monitor.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await monitor


@pytest.mark.asyncio
async def test_confirmed_worker_exit_releases_residency(tmp_path, monkeypatch):
    monkeypatch.setenv("VVOICE_SCHEDULER_REQUIRED", "false")
    manager = _manager(tmp_path)

    class Worker:
        async def stop(self):
            return True

    class Lease:
        def __init__(self):
            self.calls = []

        async def release(self, stopped, evidence):
            self.calls.append((stopped, evidence))

    lease = Lease()
    manager.worker = Worker()
    manager.lease = lease

    await manager._stop_worker(True, "dialogue_failed")

    assert lease.calls == [(True, "dialogue_failed")]
    assert manager.state == "unloaded"


@pytest.mark.asyncio
async def test_zero_idle_seconds_unloads_after_session(tmp_path, monkeypatch):
    monkeypatch.setenv("VVOICE_SCHEDULER_REQUIRED", "false")
    manager = _manager(tmp_path, seconds=0)
    try:
        session = await manager.open_session(Ticket("alice", "zh", "companion", 180))
        await session.hang_up()
        for _ in range(3):
            await asyncio.wait_for(session.events.get(), 2)
        for _ in range(30):
            if manager.state == "unloaded":
                break
            await asyncio.sleep(0.05)
        assert manager.state == "unloaded"
        assert manager.worker is None
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_residency_state_releases_permit_after_restart(tmp_path, monkeypatch):
    manager = _manager(tmp_path)
    state = manager._state_path()
    state.parent.mkdir(parents=True)
    state.write_text(
        json.dumps(
            {
                "permit_id": "permit-restart",
                "executor_id": "haru-executor",
                "upstream_url": "http://v-voice-backend:7070/v1",
                "model_id": MODEL_KEY,
                "worker_pid": 0,
            }
        )
    )
    os.chmod(state, 0o600)
    calls = []

    def controller(config, path, body, *args, **kwargs):
        calls.append((path, body))
        return {}

    monkeypatch.setattr("vvoice.dialogue.admission.configuration", lambda: {"url": "http://scheduler", "token": "x" * 32})
    monkeypatch.setattr("vvoice.dialogue.admission.controller", controller)

    await manager.recover()

    assert calls == [
        (
            "/permits/permit-restart/release",
            {"stopped": True, "evidence": "haru_orphan_recovered"},
        )
    ]
    assert not state.exists()


@pytest.mark.asyncio
async def test_residency_lease_persists_worker_and_clears_after_release(tmp_path, monkeypatch):
    manager = _manager(tmp_path)
    manager.config = dataclasses.replace(
        manager.config,
        data_dir=tmp_path / "data",
    )
    lease = ResidentLease(
        manager,
        {
            "dialogue_models": {MODEL_KEY: "haru-executor"},
            "upstream_url": "http://v-voice-backend:7070/v1",
        },
    )
    calls = []

    def controller(config, path, body, *args, **kwargs):
        calls.append((path, body))
        if path == "/permits":
            return {"permit_id": "permit-lease"}
        return {"state": "active", "lease_seconds": 30}

    monkeypatch.setattr("vvoice.dialogue.admission.controller", controller)

    await lease.acquire()
    state = manager._state_path()
    assert state.is_file()
    assert (state.stat().st_mode & 0o777) == 0o600
    assert json.loads(state.read_text())["permit_id"] == "permit-lease"

    lease.set_worker(os.getpid())
    assert json.loads(state.read_text())["worker_pid"] == os.getpid()

    await lease.release(True, "test_release")
    assert not state.exists()
    assert calls[-1][0] == "/permits/permit-lease/release"


@pytest.mark.skipif(not Path("/proc/self/stat").exists(), reason="Linux process recovery")
@pytest.mark.asyncio
async def test_recovery_stops_orphaned_worker_before_releasing_permit(tmp_path, monkeypatch):
    manager = _manager(tmp_path)
    speech = tmp_path / "speechcpp"
    speech.mkdir()
    worker = speech / "speech"
    worker.write_text(
        f"""#!{sys.executable}
import time
time.sleep(60)
""",
        encoding="utf-8",
    )
    worker.chmod(0o755)
    process = await asyncio.create_subprocess_exec(
        str(worker),
        "worker",
        str(manager.config.haru_model_path),
        start_new_session=True,
    )
    try:
        state = manager._state_path()
        state.parent.mkdir(parents=True)
        state.write_text(
            json.dumps(
                {
                    "permit_id": "permit-orphan",
                    "worker_pid": process.pid,
                    "worker_start_ticks": _process_start_ticks(process.pid),
                }
            )
        )
        os.chmod(state, 0o600)
        calls = []

        def controller(config, path, body, *args, **kwargs):
            calls.append((path, body))
            return {}

        monkeypatch.setattr(
            "vvoice.dialogue.admission.configuration",
            lambda: {"url": "http://scheduler", "token": "x" * 32},
        )
        monkeypatch.setattr("vvoice.dialogue.admission.controller", controller)

        await manager.recover()

        await asyncio.wait_for(process.wait(), 5)
        assert process.returncode is not None
        assert calls == [
            (
                "/permits/permit-orphan/release",
                {"stopped": True, "evidence": "haru_orphan_recovered"},
            )
        ]
        assert not state.exists()
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
