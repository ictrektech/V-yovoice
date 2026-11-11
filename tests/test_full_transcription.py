from __future__ import annotations

import asyncio
import sys

import numpy as np
import pytest

from vvoice import full_transcription
from vvoice.full_transcription import (
    SAFE_AUDIO_DEMUXERS,
    FullTranscriptionError,
    segment_policy,
    split_parts,
)

LIMITS = {
    "duration_seconds": 20,
    "sample_rate": 24000,
    "hotwords_characters": 0,
    "input_bytes": 1048576,
}


def test_segment_policy_obeys_duration_and_encoded_bytes() -> None:
    policy = segment_policy(LIMITS)
    assert policy.max_samples == 20 * 16000
    assert policy.max_wav_bytes <= LIMITS["input_bytes"]


def test_audio_demuxer_allowlist_excludes_external_playlists() -> None:
    allowed = set(SAFE_AUDIO_DEMUXERS.split(","))
    assert {"wav", "mp3", "flac", "mov", "matroska", "ogg"} <= allowed
    assert not {"concat", "ffconcat", "hls", "dash", "image2"} & allowed


def test_segment_policy_rejects_unusable_calibration() -> None:
    with pytest.raises(FullTranscriptionError) as error:
        segment_policy({**LIMITS, "sample_rate": 8000})
    assert error.value.status_code == 503
    with pytest.raises(FullTranscriptionError):
        segment_policy(None)


def test_short_speech_stays_one_untrimmed_part(monkeypatch) -> None:
    monkeypatch.setattr(full_transcription, "vad_available", lambda: True)
    monkeypatch.setattr(
        full_transcription,
        "_speech_segments",
        lambda samples, _rate: [(1.0, samples[16000:32000])],
    )
    parts = split_parts(np.zeros(15 * 16000, dtype=np.float32), segment_policy(LIMITS))
    assert len(parts) == 1
    assert parts[0].start == 0 and parts[0].duration == 15


def test_short_silence_returns_no_parts(monkeypatch) -> None:
    monkeypatch.setattr(full_transcription, "vad_available", lambda: True)
    monkeypatch.setattr(full_transcription, "_speech_segments", lambda *_args: [])
    assert split_parts(np.zeros(5 * 16000, dtype=np.float32), segment_policy(LIMITS)) == []


def test_long_audio_falls_back_to_bounded_ordered_parts(monkeypatch) -> None:
    monkeypatch.setattr(full_transcription, "_speech_segments", lambda *_args: [])
    monkeypatch.setattr(full_transcription, "vad_available", lambda: False)
    monkeypatch.setattr(full_transcription, "_quiet_cut", lambda _chunk, maximum, _rate: maximum)
    parts = split_parts(np.zeros(45 * 16000, dtype=np.float32), segment_policy(LIMITS))
    assert len(parts) == 3
    assert [part.index for part in parts] == [0, 1, 2]
    assert [part.start for part in parts] == [0.0, 20.0, 40.0]
    assert all(part.duration <= 20 for part in parts)
    assert all(part.wav_bytes <= LIMITS["input_bytes"] for part in parts)


def test_vad_offsets_survive_secondary_byte_splits(monkeypatch) -> None:
    monkeypatch.setattr(full_transcription, "vad_available", lambda: True)
    monkeypatch.setattr(full_transcription, "_quiet_cut", lambda _chunk, maximum, _rate: maximum)
    monkeypatch.setattr(
        full_transcription,
        "_speech_segments",
        lambda *_args, **_kwargs: [
            (12.0, np.zeros(10 * 16000, dtype=np.float32)),
            (30.0, np.zeros(25 * 16000, dtype=np.float32)),
        ],
    )
    parts = split_parts(np.zeros(60 * 16000, dtype=np.float32), segment_policy(LIMITS))
    assert [part.start for part in parts] == [12.0, 30.0, 50.0]
    assert all(part.duration <= 20 for part in parts)


def test_vad_silence_is_a_complete_empty_result(monkeypatch) -> None:
    monkeypatch.setattr(full_transcription, "vad_available", lambda: True)
    monkeypatch.setattr(
        full_transcription, "_speech_segments", lambda *_args, **_kwargs: []
    )
    assert split_parts(np.zeros(60 * 16000, dtype=np.float32), segment_policy(LIMITS)) == []


def test_vad_failure_does_not_drop_speech(monkeypatch) -> None:
    monkeypatch.setattr(full_transcription, "vad_available", lambda: True)

    def fail(*_args):
        raise RuntimeError("vad failed")

    monkeypatch.setattr(full_transcription, "_speech_segments", fail)
    parts = split_parts(np.zeros(25 * 16000, dtype=np.float32), segment_policy(LIMITS))
    assert len(parts) == 2


@pytest.mark.asyncio
async def test_media_command_is_terminated_on_cancel(tmp_path) -> None:
    cancel = asyncio.Event()
    task = asyncio.create_task(
        full_transcription._run_command(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            timeout=10,
            cancel=cancel,
            stderr_path=tmp_path / "cancel.log",
        )
    )
    await asyncio.sleep(0.1)
    cancel.set()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_media_command_timeout_is_explicit(tmp_path) -> None:
    with pytest.raises(FullTranscriptionError) as error:
        await full_transcription._run_command(
            [sys.executable, "-c", "import time; time.sleep(1)"],
            timeout=0.05,
            cancel=asyncio.Event(),
            stderr_path=tmp_path / "timeout.log",
        )
    assert error.value.status_code == 504
    assert error.value.code == "audio_decode_timeout"
