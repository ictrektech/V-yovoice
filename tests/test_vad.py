from __future__ import annotations

import numpy as np

from vvoice.runtime import transcribe
from vvoice.transcript import merge_segment_transcripts
from vvoice.vad import MAX_SEGMENT_SECONDS, _merge_and_cap, needs_split


def _part(text: str, start: float, end: float) -> dict:
    return {
        "text": text,
        "words": [{"word": text, "start": start, "end": end}],
        "segments": [{"id": 0, "start": start, "end": end, "text": text}],
        "tokens": [text],
        "timestamps": [start],
        "duration": round(end - start, 3),
    }


def test_merge_shifts_timestamps_and_joins_text() -> None:
    parts = [_part("你好", 0.1, 0.9), _part("world", 0.2, 1.5)]
    merged = merge_segment_transcripts(parts, [0.0, 10.0], 12.5)
    assert merged["text"] == "你好 world"
    assert merged["words"][1]["start"] == 10.2
    assert merged["segments"][1]["id"] == 1
    assert merged["timestamps"][1] == 10.2
    assert merged["duration"] == 12.5


def test_merge_keeps_first_paralinguistic_labels() -> None:
    parts = [_part("a", 0.0, 0.5), _part("b", 0.0, 0.5)]
    parts[0]["lang"] = "<|zh|>"
    parts[0]["emotion"] = "NEUTRAL"
    parts[1]["lang"] = "<|en|>"
    merged = merge_segment_transcripts(parts, [0.0, 5.0], 6.0)
    assert merged["lang"] == "<|zh|>"
    assert merged["emotion"] == "NEUTRAL"


def test_merge_and_cap_merges_small_gaps_and_splits_long_runs() -> None:
    rate = 100
    segments = [
        (0.0, np.zeros(100, dtype=np.float32)),
        (1.2, np.ones(50, dtype=np.float32)),
        (5.0, np.full(int(MAX_SEGMENT_SECONDS * rate) * 2, 0.5, dtype=np.float32)),
    ]
    merged = _merge_and_cap(segments, rate)
    assert len(merged[0][1]) == 150
    assert all(len(chunk) <= MAX_SEGMENT_SECONDS * rate for _, chunk in merged)
    assert merged[1][0] == 5.0
    assert len(merged[1:]) >= 2


def test_needs_split_respects_threshold(monkeypatch) -> None:
    import dataclasses

    from vvoice import vad as vad_module

    monkeypatch.setattr(vad_module, "settings", dataclasses.replace(vad_module.settings, vad_split_seconds=30.0))
    assert needs_split(np.zeros(31 * 100), 100) is True
    assert needs_split(np.zeros(10 * 100), 100) is False
    monkeypatch.setattr(vad_module, "settings", dataclasses.replace(vad_module.settings, vad_split_seconds=0.0))
    assert needs_split(np.zeros(1000 * 100), 100) is False


def test_long_transcription_uses_vad_segments(monkeypatch) -> None:
    """Long audio is split via VAD, decoded per segment, and merged."""
    import dataclasses

    from vvoice import runtime, vad as vad_module

    item = {"key": "sensevoice-int8", "kind": "asr", "runtime": {"factory": "from_sense_voice"}}
    monkeypatch.setattr(runtime, "find_model", lambda key, kind: item)
    monkeypatch.setattr(vad_module, "settings", dataclasses.replace(vad_module.settings, vad_split_seconds=30.0))
    calls = []

    def fake_decode(key, item_arg, chunk, rate, language, task, phrases, score):
        calls.append(len(chunk))
        return {"text": f"part{len(calls)}", "words": [], "segments": [], "tokens": [], "timestamps": [], "duration": 10.0}

    monkeypatch.setattr(runtime, "_decode_segment", fake_decode)
    monkeypatch.setattr(
        runtime, "_speech_segments",
        lambda samples, rate: [(0.0, np.zeros(160000, dtype=np.float32)), (10.0, np.zeros(160000, dtype=np.float32))],
    )

    result = transcribe("sensevoice-int8", np.zeros(480016, dtype=np.float32), 16000)
    assert calls == [160000, 160000]
    assert result["text"] == "part1 part2"
    assert result["segments_decoded"] == 2
    assert result["task"] == "transcribe"


def test_vad_failure_falls_back_to_whole_decode(monkeypatch) -> None:
    from vvoice import runtime

    item = {"key": "sensevoice-int8", "kind": "asr", "runtime": {"factory": "from_sense_voice"}}
    monkeypatch.setattr(runtime, "find_model", lambda key, kind: item)

    def boom(samples, rate):
        raise RuntimeError("vad unavailable")

    monkeypatch.setattr(runtime, "_speech_segments", boom)
    seen = {}

    def fake_decode(key, item_arg, chunk, rate, language, task, phrases, score):
        seen["len"] = len(chunk)
        return {"text": "whole", "words": [], "segments": [], "tokens": [], "timestamps": [], "duration": 40.0}

    monkeypatch.setattr(runtime, "_decode_segment", fake_decode)
    result = transcribe("sensevoice-int8", np.zeros(640000, dtype=np.float32), 16000)
    assert seen["len"] == 640000
    assert result["text"] == "whole"


def test_cpu_models_pin_forces_cpu_provider(monkeypatch) -> None:
    import dataclasses

    from vvoice import runtime, vad as vad_module

    monkeypatch.setattr(runtime, "resolve_files", lambda item: {})
    monkeypatch.setattr(runtime, "detect_provider", lambda: "cuda")
    pinned = dataclasses.replace(vad_module.settings, cpu_models=("paraformer-zh",))
    monkeypatch.setattr(runtime, "settings", pinned)

    paraformer = {"key": "paraformer-zh", "runtime": {"factory": "from_paraformer", "files": {"paraformer": "m.onnx"}}}
    sensevoice = {"key": "sensevoice-int8", "runtime": {"factory": "from_sense_voice", "files": {"model": "m.onnx"}}}
    assert runtime._kwargs(paraformer)["provider"] == "cpu"
    assert runtime._kwargs(sensevoice)["provider"] == "cuda"
