from __future__ import annotations

import asyncio
import dataclasses
import tempfile

import numpy as np
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from vvoice import admission, main
from vvoice import config as config_module
from vvoice.full_transcription import DecodedAudio, FullTranscriptionError, SpeechPart
from vvoice.main import app

LIMITS = {
    "duration_seconds": 20,
    "sample_rate": 24000,
    "hotwords_characters": 0,
    "input_bytes": 1048576,
}
MODEL = {"key": "sensevoice-int8", "kind": "asr", "runtime": {"files": {}}}


def _decoded(seconds: float = 15) -> DecodedAudio:
    samples = np.zeros(round(seconds * 16000), dtype=np.float32)
    return DecodedAudio(
        samples=samples,
        duration=len(samples) / 16000,
        source_sample_rate=48000,
        source_channels=2,
        source_sha256="a" * 64,
    )


@pytest.fixture
def full_api(monkeypatch):
    monkeypatch.delenv("VVOICE_SCHEDULER_REQUIRED", raising=False)
    monkeypatch.setattr(main, "model_limits", lambda _key: LIMITS)
    monkeypatch.setattr(main, "find_model", lambda *_args: MODEL)

    async def admit(_model):
        return None

    monkeypatch.setattr(main, "admit_model", admit)
    return TestClient(app)


def test_full_transcription_short_file_returns_complete_result(
    full_api, monkeypatch, tmp_path
) -> None:
    audio = _decoded(15)

    async def decode(*_args):
        return audio

    monkeypatch.setattr(main, "decode_upload", decode)
    monkeypatch.setattr(
        main, "split_parts", lambda samples, _policy: [SpeechPart(0, 0.0, samples)]
    )
    monkeypatch.setattr(
        main,
        "transcribe",
        lambda *_args: {
            "text": " complete ",
            "tokens": ["complete"],
            "timestamps": [0.2],
            "words": [{"word": "complete", "start": 0.2, "end": 1.0}],
            "segments": [],
            "duration": 15.0,
        },
    )
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))

    response = full_api.post(
        "/v1/audio/transcriptions/full",
        data={"model": "sensevoice-int8"},
        files={"file": ("sample.wav", b"full audio", "audio/wav")},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["text"] == "complete"
    assert body["complete"] is True
    assert body["parts_total"] == 1
    assert body["speech_detected"] is True
    assert body["audio"] == {
        "source_sample_rate": 48000,
        "source_channels": 2,
        "decoded_sample_rate": 16000,
    }
    assert body["cache"]["source_sha256"] == "a" * 64
    assert response.headers["x-vvoice-transcription-complete"] == "true"
    assert response.headers["cache-control"] == "no-store"
    assert not list(tmp_path.glob("vvoice-full-*"))


def test_full_transcription_is_documented_in_openapi(full_api) -> None:
    response = full_api.get("/openapi.json")
    assert response.status_code == 200
    operation = response.json()["paths"]["/v1/audio/transcriptions/full"]["post"]
    assert operation["summary"] == "Transcribe one complete audio file"
    assert {"404", "413", "415", "429", "503", "504"} <= operation["responses"].keys()


def test_full_transcription_merges_parts_in_original_order(full_api, monkeypatch) -> None:
    audio = _decoded(25)

    async def decode(*_args):
        return audio

    parts = [
        SpeechPart(0, 0.0, audio.samples[:10 * 16000]),
        SpeechPart(1, 10.0, audio.samples[10 * 16000:20 * 16000]),
    ]
    monkeypatch.setattr(main, "decode_upload", decode)
    monkeypatch.setattr(main, "split_parts", lambda *_args: parts)
    texts = iter(["你好。", "世界"])
    monkeypatch.setattr(
        main,
        "transcribe",
        lambda *_args: {
            "text": next(texts),
            "tokens": [],
            "timestamps": [],
            "words": [],
            "segments": [],
            "duration": 10.0,
        },
    )

    response = full_api.post(
        "/v1/audio/transcriptions/full",
        data={"model": "sensevoice-int8", "response_format": "verbose_json"},
        files={"file": ("sample.wav", b"full audio", "audio/wav")},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["text"] == "你好。世界"
    assert [part["start"] for part in body["parts"]] == [0.0, 10.0]
    assert body["duration"] == 25.0
    assert body["complete"] is True


def test_full_transcription_part_failure_is_explicitly_partial(
    full_api, monkeypatch
) -> None:
    audio = _decoded(30)

    async def decode(*_args):
        return audio

    parts = [
        SpeechPart(0, 0.0, audio.samples[:15 * 16000]),
        SpeechPart(1, 15.0, audio.samples[15 * 16000:]),
    ]
    monkeypatch.setattr(main, "decode_upload", decode)
    monkeypatch.setattr(main, "split_parts", lambda *_args: parts)
    calls = 0

    def transcribe(*_args):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise HTTPException(
                status_code=429, detail="Local compute resources are busy", headers={"Retry-After": "3"}
            )
        return {
            "text": "first",
            "tokens": [],
            "timestamps": [],
            "words": [],
            "segments": [],
            "duration": 15.0,
        }

    monkeypatch.setattr(main, "transcribe", transcribe)
    response = full_api.post(
        "/v1/audio/transcriptions/full",
        data={"model": "sensevoice-int8"},
        files={"file": ("sample.wav", b"full audio", "audio/wav")},
    )

    assert response.status_code == 429
    assert response.headers["retry-after"] == "3"
    assert response.headers["x-vvoice-transcription-complete"] == "false"
    body = response.json()
    assert body["complete"] is False
    assert body["error"]["code"] == "service_busy"
    assert body["error"]["part_number"] == 2
    assert body["partial"] == {
        "complete": False,
        "text": "first",
        "duration": 30.0,
        "parts_completed": 1,
        "parts_total": 2,
        "parts": [
            {"index": 0, "start": 0.0, "end": 15.0, "duration": 15.0, "text": "first"}
        ],
    }


def test_full_transcription_empty_speech_is_complete(full_api, monkeypatch) -> None:
    audio = _decoded(30)

    async def decode(*_args):
        return audio

    monkeypatch.setattr(main, "decode_upload", decode)
    monkeypatch.setattr(main, "split_parts", lambda *_args: [])
    monkeypatch.setattr(main, "transcribe", lambda *_args: pytest.fail("no speech must not load a model"))

    response = full_api.post(
        "/v1/audio/transcriptions/full",
        data={"model": "sensevoice-int8"},
        files={"file": ("silence.wav", b"silence", "audio/wav")},
    )

    assert response.status_code == 200, response.text
    assert response.json()["complete"] is True
    assert response.json()["text"] == ""
    assert response.json()["parts_total"] == 0
    assert response.json()["speech_detected"] is False


def test_full_transcription_uncalibrated_model_fails_before_decode(
    full_api, monkeypatch
) -> None:
    monkeypatch.setattr(main, "model_limits", lambda _key: None)
    monkeypatch.setattr(
        main, "decode_upload", lambda *_args: pytest.fail("decode must not start")
    )
    response = full_api.post(
        "/v1/audio/transcriptions/full",
        data={"model": "sensevoice-int8"},
        files={"file": ("sample.wav", b"audio", "audio/wav")},
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "model_not_calibrated"


def test_full_transcription_validation_error_uses_structured_incomplete_response(
    full_api,
) -> None:
    response = full_api.post(
        "/v1/audio/transcriptions/full",
        data={"model": "sensevoice-int8"},
    )
    assert response.status_code == 422
    body = response.json()
    assert body["complete"] is False
    assert body["error"]["code"] == "invalid_request"
    assert body["error"]["details"]
    assert response.headers["x-vvoice-transcription-complete"] == "false"


def test_full_transcription_middleware_oversize_error_keeps_contract(
    monkeypatch,
) -> None:
    limited = dataclasses.replace(main.settings, max_upload_mb=1)
    monkeypatch.setattr(main, "settings", limited)
    monkeypatch.setattr(config_module, "settings", limited)
    client = TestClient(admission.AdmissionMiddleware(app))
    response = client.post(
        "/v1/audio/transcriptions/full",
        data={"model": "sensevoice-int8"},
        files={"file": ("large.wav", b"x" * (1024 * 1024 + 65537), "audio/wav")},
    )
    assert response.status_code == 413
    body = response.json()
    assert body["complete"] is False
    assert body["error"]["code"] == "audio_file_too_large"


def test_full_transcription_rejects_gateway_single_permit(full_api, monkeypatch) -> None:
    monkeypatch.setattr(
        main, "decode_upload", lambda *_args: pytest.fail("decode must not start")
    )
    response = full_api.post(
        "/v1/audio/transcriptions/full",
        data={"model": "sensevoice-int8"},
        files={"file": ("sample.wav", b"audio", "audio/wav")},
        headers={
            "X-VScheduler-Permit-ID": "one-request",
            "X-VScheduler-Execution-Token": "x" * 32,
            "X-VScheduler-Executor-ID": "router.voice",
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "direct_admission_required"


def test_full_transcription_decode_error_is_not_reported_as_complete(
    full_api, monkeypatch
) -> None:
    async def decode(*_args):
        raise FullTranscriptionError(
            415, "unsupported_audio", "unsupported, invalid, or undecodable audio"
        )

    monkeypatch.setattr(main, "decode_upload", decode)
    response = full_api.post(
        "/v1/audio/transcriptions/full",
        data={"model": "sensevoice-int8"},
        files={"file": ("broken.mp3", b"not audio", "audio/mpeg")},
    )
    assert response.status_code == 415
    body = response.json()
    assert body["complete"] is False
    assert body["error"]["code"] == "unsupported_audio"
    assert "partial" not in body


def test_full_transcription_total_timeout_has_no_fake_result(
    full_api, monkeypatch
) -> None:
    monkeypatch.setattr(
        main,
        "settings",
        dataclasses.replace(main.settings, full_transcription_timeout_seconds=0.01),
    )

    async def slow_decode(*_args):
        await asyncio.sleep(1)
        return _decoded()

    monkeypatch.setattr(main, "decode_upload", slow_decode)
    response = full_api.post(
        "/v1/audio/transcriptions/full",
        data={"model": "sensevoice-int8"},
        files={"file": ("slow.wav", b"audio", "audio/wav")},
    )
    assert response.status_code == 504
    assert response.json()["error"]["code"] == "transcription_timeout"
    assert response.json()["complete"] is False


def test_full_transcription_text_and_srt_mark_complete(full_api, monkeypatch) -> None:
    audio = _decoded(2)

    async def decode(*_args):
        return audio

    monkeypatch.setattr(main, "decode_upload", decode)
    monkeypatch.setattr(
        main, "split_parts", lambda samples, _policy: [SpeechPart(0, 0.0, samples)]
    )
    monkeypatch.setattr(
        main,
        "transcribe",
        lambda *_args: {
            "text": "hello",
            "tokens": ["hello"],
            "timestamps": [0.1],
            "words": [{"word": "hello", "start": 0.1, "end": 0.8}],
            "segments": [{"id": 0, "start": 0.1, "end": 0.8, "text": "hello"}],
            "duration": 2.0,
        },
    )
    text = full_api.post(
        "/v1/audio/transcriptions/full",
        data={"model": "sensevoice-int8", "response_format": "text"},
        files={"file": ("sample.wav", b"audio", "audio/wav")},
    )
    assert text.status_code == 200
    assert text.text == "hello"
    assert text.headers["x-vvoice-transcription-complete"] == "true"

    srt = full_api.post(
        "/v1/audio/transcriptions/full",
        data={"model": "sensevoice-int8", "response_format": "srt"},
        files={"file": ("sample.wav", b"audio", "audio/wav")},
    )
    assert srt.status_code == 200
    assert "00:00:00,100 --> 00:00:00,800" in srt.text


def test_each_full_file_part_takes_and_releases_its_own_permit(monkeypatch) -> None:
    config = {
        "url": "http://scheduler.invalid/api/v1",
        "token": "x" * 32,
        "upstream_url": "http://voice.invalid/v1",
        "input_limits_version": 1,
        "models": {"sensevoice-int8": "voice.infer"},
        "model_limits": {"sensevoice-int8": LIMITS},
    }
    calls: list[str] = []
    monkeypatch.setenv("VVOICE_SCHEDULER_REQUIRED", "true")
    monkeypatch.setattr(admission, "configuration", lambda: config)
    monkeypatch.setattr(admission.Execution, "_watch", lambda _self: None)

    def controller(_config, path, _body, _key="", **_kwargs):
        calls.append(path)
        if path.endswith("/verify"):
            return {"state": "active", "lease_seconds": 30}
        if path.endswith("/release"):
            return {}
        return {"permit_id": f"permit-{len(calls)}"}

    monkeypatch.setattr(admission, "controller", controller)
    monkeypatch.setattr(main, "find_model", lambda *_args: MODEL)
    audio = _decoded(30)

    async def decode(*_args):
        return audio

    parts = [
        SpeechPart(0, 0.0, audio.samples[:15 * 16000]),
        SpeechPart(1, 15.0, audio.samples[15 * 16000:]),
    ]
    monkeypatch.setattr(main, "decode_upload", decode)
    monkeypatch.setattr(main, "split_parts", lambda *_args: parts)
    texts = iter(["one", "two"])
    monkeypatch.setattr(
        main,
        "transcribe",
        lambda *_args: {
            "text": next(texts),
            "tokens": [],
            "timestamps": [],
            "words": [],
            "segments": [],
            "duration": 15.0,
        },
    )
    client = TestClient(admission.AdmissionMiddleware(app))
    response = client.post(
        "/v1/audio/transcriptions/full",
        data={"model": "sensevoice-int8"},
        files={"file": ("sample.wav", b"audio", "audio/wav")},
    )

    assert response.status_code == 200, response.text
    assert response.json()["text"] == "one two"
    assert calls.count("/permits") == 2
    assert len([path for path in calls if path.endswith("/verify")]) == 2
    assert len([path for path in calls if path.endswith("/release")]) == 2
