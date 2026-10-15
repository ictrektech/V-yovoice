from __future__ import annotations

import threading
from pathlib import Path

import numpy as np

from .config import settings


VAD_ASSET = Path(__file__).resolve().parent / "assets" / "silero_vad.onnx"
MERGE_GAP_SECONDS = 0.4
MAX_SEGMENT_SECONDS = 20.0

_vad_lock = threading.Lock()
_vad_config: tuple | None = None


def _speech_segments(samples: np.ndarray, rate: int) -> list[tuple[float, np.ndarray]]:
    """Split decoded audio into (offset_seconds, samples) speech segments.

    Uses the bundled silero VAD through sherpa-onnx; returns [] when the VAD
    asset or runtime is unavailable so callers can fall back to one-shot decode.
    """
    global _vad_config
    try:
        import sherpa_onnx
    except ImportError:
        return []
    with _vad_lock:
        if _vad_config is None:
            if not VAD_ASSET.is_file():
                return []
            config = sherpa_onnx.VadModelConfig()
            config.silero_vad.model = str(VAD_ASSET)
            config.silero_vad.threshold = 0.5
            config.silero_vad.min_silence_duration = 0.25
            config.silero_vad.min_speech_duration = 0.3
            if not config.validate():
                return []
            _vad_config = (str(VAD_ASSET),)
    config = sherpa_onnx.VadModelConfig()
    config.silero_vad.model = _vad_config[0]
    config.silero_vad.threshold = 0.5
    config.silero_vad.min_silence_duration = 0.25
    config.silero_vad.min_speech_duration = 0.3

    vad = sherpa_onnx.VoiceActivityDetector(config, buffer_size_in_seconds=30)
    collected: list[tuple[float, np.ndarray]] = []

    def drain() -> None:
        while not vad.empty():
            segment = vad.front
            collected.append((segment.start / rate, np.asarray(segment.samples, dtype=np.float32)))
            vad.pop()

    window = int(rate * 0.1)
    for start in range(0, len(samples), window):
        vad.accept_waveform(samples[start:start + window])
        drain()
    vad.flush()
    drain()
    if not collected:
        return []
    return _merge_and_cap(collected, rate)


def _merge_and_cap(segments: list[tuple[float, np.ndarray]], rate: int) -> list[tuple[float, np.ndarray]]:
    """Merge segments separated by tiny gaps, then cap segment duration."""
    merged: list[list] = []
    for start, chunk in segments:
        if merged and start - merged[-1][0] - len(merged[-1][1]) / rate <= MERGE_GAP_SECONDS:
            merged[-1][1] = np.concatenate([merged[-1][1], chunk])
        else:
            merged.append([start, chunk])

    result: list[tuple[float, np.ndarray]] = []
    max_samples = int(MAX_SEGMENT_SECONDS * rate)
    for start, chunk in merged:
        if len(chunk) <= max_samples:
            result.append((start, chunk))
            continue
        parts = int(np.ceil(len(chunk) / max_samples))
        step = int(np.ceil(len(chunk) / parts))
        for index in range(parts):
            piece = chunk[index * step:(index + 1) * step]
            if len(piece):
                result.append((start + index * step / rate, piece))
    return result


def needs_split(samples: np.ndarray, rate: int) -> bool:
    limit = settings.vad_split_seconds
    if limit <= 0:
        return False
    return rate > 0 and len(samples) / rate > limit
