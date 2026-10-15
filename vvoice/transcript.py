from __future__ import annotations

import re
from typing import Any


_PUNCTUATION = re.compile(r"^[\s\.,!?;:'\"，。！？；：、…—\-]+$")


def _span(word: str, start: float, end: float) -> dict[str, Any]:
    return {"word": word, "start": round(max(0.0, start), 3), "end": round(max(start, end), 3)}


def words_from_tokens(tokens: list[str], timestamps: list[float], duration: float) -> list[dict[str, Any]]:
    """Convert sherpa token starts into OpenAI-style word spans."""
    if not tokens or len(tokens) != len(timestamps):
        return []
    starts = [float(value) for value in timestamps]
    end_of = lambda index: starts[index + 1] if index + 1 < len(starts) else duration
    words: list[dict[str, Any]] = []

    if any("@@" in token for token in tokens):
        current = ""
        current_start = 0.0
        for index, raw in enumerate(tokens):
            token = raw.strip()
            if not token:
                continue
            if not current:
                current_start = starts[index]
            current += token.removesuffix("@@")
            if not token.endswith("@@"):
                words.append(_span(current, current_start, end_of(index)))
                current = ""
        if current:
            words.append(_span(current, current_start, duration))
        return words

    has_boundaries = any(token.startswith((" ", "▁")) for token in tokens)
    if has_boundaries:
        current = ""
        current_start = 0.0
        current_last = 0
        for index, raw in enumerate(tokens):
            boundary = raw.startswith((" ", "▁"))
            token = raw.lstrip().lstrip("▁")
            if not token:
                continue
            if boundary and current:
                words.append(_span(current, current_start, starts[index]))
                current = ""
            if not current:
                current_start = starts[index]
            current += token
            current_last = index
        if current:
            words.append(_span(current, current_start, end_of(current_last)))
        return words

    for index, raw in enumerate(tokens):
        token = raw.strip().lstrip("▁")
        if not token:
            continue
        if words and _PUNCTUATION.fullmatch(token):
            words[-1]["word"] += token
            words[-1]["end"] = round(max(words[-1]["start"], end_of(index)), 3)
        else:
            words.append(_span(token, starts[index], end_of(index)))
    return words


def merge_segment_transcripts(parts: list[dict[str, Any]], offsets: list[float], duration: float) -> dict[str, Any]:
    """Merge per-segment transcripts (decoded separately) into one result.

    Word/segment/token timestamps shift by each part's audio offset; text joins
    without separators between CJK characters and with spaces between
    word-forming scripts. Paralinguistic labels keep the first non-empty value.
    """
    if len(parts) == 1:
        merged = dict(parts[0])
        merged["duration"] = round(max(0.0, duration), 3)
        return normalize_transcript(merged, duration) if not merged.get("words") else merged

    def joiner(left: str, right: str) -> str:
        if not left:
            return right
        if not right:
            return left
        if left[-1].isspace() or right[0].isspace():
            return left + right
        if (left[-1].isascii() and left[-1].isalnum()) or (right[0].isascii() and right[0].isalnum()):
            return left + " " + right
        return left + right

    text = ""
    words: list[dict[str, Any]] = []
    segments: list[dict[str, Any]] = []
    tokens: list[str] = []
    timestamps: list[float] = []
    carried: dict[str, Any] = {}
    for part, offset in zip(parts, offsets):
        text = joiner(text, str(part.get("text") or ""))
        for word in part.get("words") or []:
            shifted = dict(word)
            shifted["start"] = round(word["start"] + offset, 3)
            shifted["end"] = round(word["end"] + offset, 3)
            words.append(shifted)
        for segment in part.get("segments") or []:
            shifted = dict(segment)
            shifted["id"] = len(segments)
            shifted["start"] = round(segment["start"] + offset, 3)
            shifted["end"] = round(segment["end"] + offset, 3)
            segments.append(shifted)
        tokens.extend(part.get("tokens") or [])
        timestamps.extend(float(value) + offset for value in part.get("timestamps") or [])
        for key in ("lang", "emotion", "event", "language"):
            if key not in carried and part.get(key):
                carried[key] = part[key]

    merged: dict[str, Any] = {
        "text": text,
        "tokens": tokens,
        "timestamps": timestamps,
        "words": words,
        "segments": segments,
        "duration": round(max(0.0, duration), 3),
    }
    merged.update(carried)
    return merged


def normalize_transcript(parsed: dict[str, Any], duration: float) -> dict[str, Any]:
    text = str(parsed.get("text") or "").strip()
    tokens = [str(value) for value in (parsed.get("tokens") or [])]
    timestamps = list(parsed.get("timestamps") or [])
    words = words_from_tokens(tokens, timestamps, duration)
    parsed["text"] = text
    parsed["tokens"] = tokens
    parsed["timestamps"] = [float(value) for value in timestamps]
    parsed["duration"] = round(max(0.0, duration), 3)
    parsed["words"] = words
    parsed["segments"] = (
        [{"id": 0, "start": words[0]["start"], "end": words[-1]["end"], "text": text}]
        if words and text
        else []
    )
    return parsed


def subtitle(result: dict[str, Any], format: str) -> str:
    segments = result.get("segments") or []
    if not segments and result.get("text"):
        segments = [{"start": 0.0, "end": result.get("duration", 0.0), "text": result["text"]}]

    def clock(value: float, separator: str) -> str:
        milliseconds = max(0, round(float(value) * 1000))
        hours, milliseconds = divmod(milliseconds, 3_600_000)
        minutes, milliseconds = divmod(milliseconds, 60_000)
        seconds, milliseconds = divmod(milliseconds, 1000)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}{separator}{milliseconds:03d}"

    separator = "." if format == "vtt" else ","
    blocks = []
    for index, segment in enumerate(segments, 1):
        blocks.append(
            f"{index}\n{clock(segment['start'], separator)} --> {clock(segment['end'], separator)}\n"
            f"{segment['text']}\n"
        )
    return ("WEBVTT\n\n" if format == "vtt" else "") + "\n".join(blocks)
