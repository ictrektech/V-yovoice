import io

import numpy as np
import pytest
import soundfile as sf
from fastapi import HTTPException
from fastapi.testclient import TestClient

from vvoice import admission, audio, runtime
from vvoice.main import app


@pytest.fixture
def calibrated(monkeypatch):
    config = {"input_limits_version": 1, "model_limits": {
        "kokoro-multilang": {"text_characters": 512, "speed_min": 1.0, "speed_max": 1.0},
        "sensevoice-int8": {"duration_seconds": 20, "sample_rate": 24000, "hotwords_characters": 0, "input_bytes": 1048576},
    }}
    monkeypatch.setenv("VVOICE_SCHEDULER_REQUIRED", "true")
    monkeypatch.setattr(admission, "configuration", lambda: config)
    return config


@pytest.mark.parametrize("values", [{"text_characters": 513, "speed": 1}, {"text_characters": 512, "speed": 0.5}, {"text_characters": 512, "speed": float("nan")}, {"unknown": 1}])
def test_tts_rejects_uncalibrated_inputs_before_native_load(calibrated, values):
    with pytest.raises(HTTPException) as error:
        admission.validate_inputs("kokoro-multilang", **values)
    assert error.value.status_code == 422


def test_exact_limits_and_legacy_binding(calibrated):
    admission.validate_inputs("kokoro-multilang", text_characters=512, speed=1)
    admission.validate_inputs("sensevoice-int8", duration_seconds=20, sample_rate=24000, hotwords_characters=0)
    calibrated.pop("model_limits")
    assert admission.model_limits("kokoro-multilang") is None


def test_native_boundaries_reject_before_model_lookup(calibrated, monkeypatch):
    monkeypatch.setattr(runtime, "find_model", lambda *args: pytest.fail("native model lookup must not occur"))
    with pytest.raises(HTTPException):
        runtime.synthesize("kokoro-multilang", "a" * 513, "default", 1)
    with pytest.raises(HTTPException):
        runtime.transcribe("sensevoice-int8", np.zeros(21 * 16000), 16000)
    with pytest.raises(HTTPException):
        runtime.transcribe("sensevoice-int8", np.zeros(16000), 16000, hotwords=["unapproved"])


@pytest.mark.parametrize("seconds,rate,accepted", [(20, 24000, True), (21, 16000, False), (1, 48000, False)])
def test_audio_decode_is_bounded_and_checks_source_rate(calibrated, seconds, rate, accepted):
    source = io.BytesIO()
    sf.write(source, np.zeros(seconds * rate), rate, format="WAV", subtype="PCM_16")
    limits = calibrated["model_limits"]["sensevoice-int8"]
    if accepted:
        samples, decoded_rate = audio.decode_calibrated_audio(source.getvalue(), "audio.wav", limits)
        assert len(samples) == 20 * 16000 and decoded_rate == 16000
    else:
        with pytest.raises(ValueError):
            audio.decode_calibrated_audio(source.getvalue(), "audio.wav", limits)


def test_invalid_or_incomplete_calibration_fails_closed(calibrated):
    calibrated["model_limits"]["kokoro-multilang"]["speed_min"] = float("nan")
    with pytest.raises(HTTPException):
        admission.model_limits("kokoro-multilang")
    with pytest.raises(HTTPException):
        admission.model_limits("whisper-tiny")


def test_direct_and_forwarded_invalid_requests_never_take_or_claim_permit(calibrated, monkeypatch):
    monkeypatch.setattr(admission, "controller", lambda *args, **kwargs: pytest.fail("Invalid input must not take or claim a permit"))
    client = TestClient(admission.AdmissionMiddleware(app))
    for headers in [{}, {"X-VScheduler-Permit-ID": "forwarded", "X-VScheduler-Execution-Token": "x" * 32, "X-VScheduler-Executor-ID": "router.voice"}]:
        for payload in [{"model": "kokoro-multilang", "input": "a" * 513}, {"model": "kokoro-multilang", "input": "Hello", "speed": 0.5}]:
            assert client.post("/v1/audio/speech", json=payload, headers=headers).status_code == 422
        source = io.BytesIO()
        sf.write(source, np.zeros(21 * 16000), 16000, format="WAV", subtype="PCM_16")
        assert client.post("/v1/audio/transcriptions", data={"model": "sensevoice-int8"}, files={"file": ("audio.wav", source.getvalue(), "audio/wav")}, headers=headers).status_code == 422
        assert client.post("/transcribe", params={"model": "sensevoice-int8"}, content=source.getvalue(), headers={**headers, "Content-Type": "application/octet-stream"}).status_code == 422
    assert client.post("/transcribe", content=b"x" * (1048576 + 65537), headers={"Content-Type": "application/octet-stream"}).status_code == 413


def test_calibration_rotation_before_acquire_fails_closed(calibrated):
    execution = admission.Execution({})
    token = admission.current.set(execution)
    try:
        admission.validate_inputs("kokoro-multilang", text_characters=512, speed=1)
        execution.validated_binding = {**calibrated, "binding_revision": -1}
        with pytest.raises(HTTPException):
            execution.enter("kokoro-multilang")
    finally:
        admission.current.reset(token)
