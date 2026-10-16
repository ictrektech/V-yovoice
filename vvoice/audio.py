from __future__ import annotations

import subprocess
import json
import math
import tempfile
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import soundfile as sf


def decode_calibrated_audio(data: bytes, filename: str, limits: dict) -> tuple[np.ndarray, int]:
    if len(data) > limits["input_bytes"]:
        raise ValueError("audio exceeds calibrated input bytes")
    with tempfile.TemporaryDirectory(prefix="vvoice-") as directory:
        source = Path(directory) / ("input" + (Path(filename).suffix or ".audio"))
        target = Path(directory) / "decoded.wav"
        source.write_bytes(data)
        metadata = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=sample_rate", "-of", "json", str(source)], check=True, capture_output=True, timeout=30)
        rate = float(json.loads(metadata.stdout)["streams"][0]["sample_rate"])
        if not math.isfinite(rate) or rate <= 0 or rate > limits["sample_rate"]:
            raise ValueError("audio exceeds calibrated sample rate")
        maximum = limits["duration_seconds"]
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-threads", "1", "-i", str(source), "-filter_threads", "1", "-t", str(maximum + 1 / 16000), "-ac", "1", "-ar", "16000", str(target)], check=True, timeout=30)
        samples, sample_rate = sf.read(target, dtype="float32", always_2d=False)
        if len(samples) > maximum * sample_rate:
            raise ValueError("audio exceeds calibrated duration")
    return np.asarray(samples, dtype=np.float32), int(sample_rate)


def decode_audio(data: bytes, filename: str) -> tuple[np.ndarray, int]:
    suffix = Path(filename).suffix or ".audio"
    with tempfile.TemporaryDirectory(prefix="vvoice-") as directory:
        source = Path(directory) / f"input{suffix}"
        target = Path(directory) / "decoded.wav"
        source.write_bytes(data)
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source), "-ac", "1", "-ar", "16000", str(target)],
            check=True,
            timeout=300,
        )
        samples, rate = sf.read(target, dtype="float32", always_2d=False)
    if samples.ndim > 1:
        samples = samples[:, 0]
    return np.asarray(samples, dtype=np.float32), int(rate)


def encode_audio(samples: np.ndarray, sample_rate: int, response_format: str) -> tuple[bytes, str]:
    fmt = response_format.lower()
    if fmt == "pcm":
        pcm = np.clip(samples, -1, 1)
        return (pcm * 32767).astype("<i2").tobytes(), "audio/pcm"
    codecs = {
        "wav": ("pcm_s16le", "audio/wav"),
        "mp3": ("libmp3lame", "audio/mpeg"),
        "opus": ("libopus", "audio/ogg"),
        "flac": ("flac", "audio/flac"),
        "aac": ("aac", "audio/aac"),
    }
    if fmt not in codecs:
        raise ValueError(f"unsupported response_format: {response_format}")
    codec, media_type = codecs[fmt]
    with tempfile.TemporaryDirectory(prefix="vvoice-") as directory:
        wav = Path(directory) / "source.wav"
        output = Path(directory) / f"speech.{fmt if fmt != 'opus' else 'ogg'}"
        sf.write(wav, samples, sample_rate, subtype="PCM_16")
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(wav), "-codec:a", codec, str(output)],
            check=True,
            timeout=300,
        )
        return output.read_bytes(), media_type


class StreamingPcmDecoder:
    """Incremental s16le PCM extraction from chunked audio uploads.

    ``pcm`` feeds raw s16le mono bytes straight through; ``wav`` locates the
    RIFF ``data`` chunk and streams its payload; any other format buffers the
    body and decodes once with ffmpeg when ``flush`` is called.
    """

    def __init__(self, fmt: str = "pcm", sample_rate: int = 16000) -> None:
        self.fmt = fmt.lower()
        self.rate = int(sample_rate) if self.fmt == "pcm" else None
        self._buffer = bytearray()
        self._wav_ready = False
        self._wav_offset = 0

    def _pcm_bytes(self, data: bytes) -> np.ndarray:
        usable = len(data) - (len(data) % 2)
        if usable <= 0:
            return np.zeros(0, dtype=np.float32)
        return np.frombuffer(data[:usable], dtype="<i2").astype(np.float32) / 32768.0

    def _parse_wav_header(self) -> bool:
        buffer = self._buffer
        if len(buffer) < 12:
            return False
        if buffer[:4] != b"RIFF" or buffer[8:12] != b"WAVE":
            raise ValueError("wav stream must start with a RIFF/WAVE header")
        offset = 12
        while True:
            if offset + 8 > len(buffer):
                return False
            chunk_id = bytes(buffer[offset:offset + 4])
            chunk_size = int.from_bytes(buffer[offset + 4:offset + 8], "little")
            offset += 8
            if chunk_id == b"fmt ":
                if offset + chunk_size > len(buffer):
                    return False
                audio_format = int.from_bytes(buffer[offset:offset + 2], "little")
                channels = int.from_bytes(buffer[offset + 2:offset + 4], "little")
                self.rate = int.from_bytes(buffer[offset + 4:offset + 8], "little")
                if audio_format != 1 or channels != 1:
                    raise ValueError("streaming wav must be uncompressed mono PCM; use format=auto otherwise")
                offset += chunk_size
            elif chunk_id == b"data":
                self._wav_offset = offset
                self._wav_ready = True
                return True
            else:
                offset += chunk_size
                if offset > len(buffer):
                    return False

    def feed(self, chunk: bytes) -> Iterator[np.ndarray]:
        if not chunk:
            return
        if self.fmt == "pcm":
            samples = self._pcm_bytes(chunk)
            if len(samples):
                yield samples
            return
        self._buffer.extend(chunk)
        if self.fmt == "wav":
            if not self._wav_ready and not self._parse_wav_header():
                return
            payload = bytes(self._buffer[self._wav_offset:])
            del self._buffer[:]
            self._wav_offset = 0
            samples = self._pcm_bytes(payload)
            if len(samples):
                yield samples

    def flush(self) -> tuple[np.ndarray, int] | None:
        """Return leftover samples for buffered formats; None when nothing to decode."""
        if self.fmt in {"pcm", "wav"}:
            if self.fmt == "wav" and not self._wav_ready and not self._parse_wav_header():
                raise ValueError("wav stream ended before a data chunk was found")
            return None
        if not self._buffer:
            return np.zeros(0, dtype=np.float32), self.rate or 16000
        data = bytes(self._buffer)
        del self._buffer[:]
        samples, rate = decode_audio(data, "streaming-input.wav")
        return samples, rate
