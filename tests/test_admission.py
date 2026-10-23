import asyncio
import threading

import pytest
from fastapi import HTTPException

from vvoice import admission


@pytest.fixture
def broker(monkeypatch):
    calls = []
    config = {"url": "http://scheduler.invalid/api/v1", "token": "x" * 32,
              "upstream_url": "http://voice.invalid/v1", "models": {"asr": "voice.infer"},
              "gateway_executors": {"asr": "router.voice"}, "secondary_models": {"asr": ["speaker"]}}
    monkeypatch.setattr(admission, "configuration", lambda: config)
    monkeypatch.setattr(admission.Execution, "_watch", lambda self: None)

    def controller(config, path, body, key="", **kwargs):
        calls.append((path, body, key))
        return {"permit_id": "fixture-permit", "state": "active", "lease_seconds": 30}

    monkeypatch.setattr(admission, "controller", controller)
    return calls


def test_direct_call_and_secondary_model_share_one_budget(broker):
    execution = admission.Execution({})
    execution.enter("asr")
    execution.enter("speaker")
    assert len([c for c in broker if c[0] == "/permits"]) == 1
    assert len([c for c in broker if c[0].endswith("/verify")]) == 1
    execution.end()
    assert broker[-1][1]["stopped"] is True


def test_gateway_proof_does_not_acquire_or_release_a_second_budget(broker):
    execution = admission.Execution({"x-vscheduler-permit-id": "router-permit", "x-vscheduler-executor-id": "router.voice",
                                     "x-vscheduler-execution-token": "y" * 32})
    execution.enter("asr")
    execution.enter("speaker")
    execution.end()
    assert [c[0] for c in broker] == ["/permits/router-permit/verify"]
    assert broker[0][1]["claim"] is True


@pytest.mark.parametrize("headers", [
    {"x-vscheduler-permit-id": "forged"},
    {"x-vscheduler-permit-id": "forged", "x-vscheduler-executor-id": "wrong", "x-vscheduler-execution-token": "z" * 32},
])
def test_partial_or_unapproved_gateway_proof_fails_closed(headers, broker):
    with pytest.raises(HTTPException) as error:
        admission.Execution(headers).enter("asr")
    assert error.value.status_code == 503
    assert not broker


def test_unapproved_secondary_model_is_not_executed(broker):
    execution = admission.Execution({})
    execution.enter("asr")
    with pytest.raises(HTTPException):
        execution.enter("unapproved")
    execution.end()


def test_unknown_remote_stop_retains_suspect_reservation(broker):
    execution = admission.Execution({})
    execution.enter("asr")
    execution.uncertain = True
    execution.end()
    assert broker[-1][1]["stopped"] is False


@pytest.mark.asyncio
async def test_cancelled_await_does_not_release_running_native_thread(broker):
    execution = admission.Execution({})
    execution.enter("asr")
    entered, finish = threading.Event(), threading.Event()
    def native():
        entered.set()
        finish.wait(5)
        return True
    token = admission.current.set(execution)
    try:
        task = asyncio.create_task(admission.run_blocking(native))
        while not entered.is_set():
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        execution.end()
        assert not any(c[0].endswith("/release") for c in broker)
        finish.set()
        for _ in range(100):
            if execution.closed:
                break
            await asyncio.sleep(0.01)
        assert execution.closed
        assert broker[-1][1]["stopped"] is True
    finally:
        finish.set()
        admission.current.reset(token)


def test_direct_call_carries_scheduling_without_changing_native_budget(broker):
    execution = admission.Execution({"x-vscheduler-priority": "high", "x-vscheduler-preemptible": "true", "x-vscheduler-allow-preemption": "true"})
    execution.enter("asr")
    assert broker[0][1]["scheduling"] == {"priority": "high", "preemptible": True, "allow_preemption": True}
    execution.end()
    assert broker[-1][1]["stopped"] is True


@pytest.mark.parametrize("headers", [{"x-vscheduler-priority": "urgent"}, {"x-vscheduler-preemptible": "1"}])
def test_invalid_scheduling_does_not_start_native_work(headers, broker):
    with pytest.raises(HTTPException) as error:
        admission.Execution(headers).enter("asr")
    assert error.value.status_code == 422
    assert not broker
