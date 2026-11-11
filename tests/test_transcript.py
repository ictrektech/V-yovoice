from __future__ import annotations

from vvoice.transcript import (
    merge_segment_transcripts,
    normalize_transcript,
    subtitle,
    words_from_tokens,
)


def test_sentencepiece_tokens_are_merged_into_words() -> None:
    words = words_from_tokens(
        [" AFTER", " E", "AR", "LY", " NIGHT", "F", "A", "LL"],
        [0.0, 0.36, 0.52, 0.68, 0.96, 1.24, 1.32, 1.44],
        1.8,
    )
    assert words == [
        {"word": "AFTER", "start": 0.0, "end": 0.36},
        {"word": "EARLY", "start": 0.36, "end": 0.96},
        {"word": "NIGHTFALL", "start": 0.96, "end": 1.8},
    ]


def test_atat_bpe_tokens_are_merged_into_words() -> None:
    words = words_from_tokens(["ear@@", "ly", "night"], [0.1, 0.2, 0.5], 0.9)
    assert words == [
        {"word": "early", "start": 0.1, "end": 0.5},
        {"word": "night", "start": 0.5, "end": 0.9},
    ]


def test_missing_token_timestamps_are_not_fabricated() -> None:
    result = normalize_transcript({"text": "hello", "tokens": ["hello"], "timestamps": []}, 1.25)
    assert result["duration"] == 1.25
    assert result["words"] == []
    assert result["segments"] == []


def test_subtitles_use_real_audio_duration_when_model_has_no_timestamps() -> None:
    value = subtitle({"text": "hello", "duration": 1.25, "segments": []}, "srt")
    assert "00:00:00,000 --> 00:00:01,250" in value


def test_segment_text_uses_cjk_aware_spacing() -> None:
    parts = [
        {"text": "你好。", "words": [], "segments": [], "tokens": [], "timestamps": []},
        {"text": "世界", "words": [], "segments": [], "tokens": [], "timestamps": []},
        {"text": "hello", "words": [], "segments": [], "tokens": [], "timestamps": []},
    ]
    merged = merge_segment_transcripts(parts, [0.0, 1.0, 2.0], 3.0)
    assert merged["text"] == "你好。世界 hello"


def test_single_segment_shifts_timestamps_to_original_audio_offset() -> None:
    part = {
        "text": "later",
        "words": [{"word": "later", "start": 0.2, "end": 0.8}],
        "segments": [{"id": 0, "start": 0.2, "end": 0.8, "text": "later"}],
        "tokens": ["later"],
        "timestamps": [0.2],
        "duration": 1.0,
    }
    merged = merge_segment_transcripts([part], [10.0], 12.0)
    assert merged["words"][0]["start"] == 10.2
    assert merged["segments"][0]["start"] == 10.2
    assert merged["timestamps"] == [10.2]
    assert merged["duration"] == 12.0
