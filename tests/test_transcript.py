from __future__ import annotations

from vvoice.transcript import normalize_transcript, subtitle, words_from_tokens


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
