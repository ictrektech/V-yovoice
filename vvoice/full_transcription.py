from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
from fastapi import UploadFile

from .catalog import model_root
from .config import settings
from .vad import _speech_segments, vad_available

PIPELINE_VERSION = "full-file-v1"
RESPONSE_FORMATS = {"json", "verbose_json", "text", "srt", "vtt"}
MAX_ERROR_OUTPUT_BYTES = 8192
SAFE_AUDIO_DEMUXERS = (
    "aac,ac3,aiff,amr,asf,au,avi,caf,flac,matroska,mov,mp2,mp3,"
    "mpegts,ogg,oma,opus,w64,wav,webm"
)


class FullTranscriptionError(Exception):
    """全文件转写中可安全返回给调用方的错误。"""

    def __init__(
        self,
        status_code: int,
        code: str,
        detail: str,
        *,
        retryable: bool = False,
        retry_after: int | None = None,
        part_number: int | None = None,
    ) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.code = code
        self.detail = detail
        self.retryable = retryable
        self.retry_after = retry_after
        self.part_number = part_number


@dataclass(frozen=True)
class SegmentPolicy:
    """逐段编码与时长预算；只从已批准模型限制推导。"""

    max_samples: int
    max_seconds: float
    max_wav_bytes: int


@dataclass(frozen=True)
class SpeechPart:
    """一段待识别音频及其在原始文件中的起点。"""

    index: int
    start: float
    samples: np.ndarray

    @property
    def duration(self) -> float:
        return len(self.samples) / 16000

    @property
    def end(self) -> float:
        return self.start + self.duration

    @property
    def wav_bytes(self) -> int:
        # 16 kHz 单声道 PCM16 WAV：44 字节头加每个采样 2 字节。
        return 44 + len(self.samples) * 2


@dataclass(frozen=True)
class DecodedAudio:
    """有界解码后的单声道 16 kHz 音频。"""

    samples: np.ndarray
    duration: float
    source_sample_rate: int
    source_channels: int
    source_sha256: str


def _safe_suffix(filename: str) -> str:
    """只保留短扩展名；内容仍由 ffprobe/ffmpeg 按实际格式识别。"""
    suffix = Path(filename).suffix.lower()
    return suffix if re.fullmatch(r"\.[a-z0-9]{1,10}", suffix) else ".audio"


async def _write_upload(file: UploadFile, target: Path, cancel: asyncio.Event) -> str:
    """分块保存上传，限制编码大小并计算内容摘要。"""
    maximum = settings.max_upload_mb * 1024 * 1024
    if file.size is not None and file.size > maximum:
        raise FullTranscriptionError(413, "audio_file_too_large", "audio file is too large")
    total = 0
    digest = hashlib.sha256()
    with target.open("xb") as output:
        while True:
            if cancel.is_set():
                raise asyncio.CancelledError
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > maximum:
                raise FullTranscriptionError(413, "audio_file_too_large", "audio file is too large")
            digest.update(chunk)
            output.write(chunk)
    if total == 0:
        raise FullTranscriptionError(422, "empty_audio", "audio file is empty")
    return digest.hexdigest()


async def _terminate(process: asyncio.subprocess.Process) -> None:
    """先温和终止解码子进程，超时后再强制结束。"""
    if process.returncode is not None:
        return
    process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=3)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()


async def _stop_on_cancel(process: asyncio.subprocess.Process, cancel: asyncio.Event) -> None:
    await cancel.wait()
    await _terminate(process)


def _read_tail(path: Path) -> str:
    try:
        with path.open("rb") as source:
            source.seek(0, 2)
            source.seek(max(0, source.tell() - MAX_ERROR_OUTPUT_BYTES))
            return source.read().decode("utf-8", "replace").strip()
    except OSError:
        return ""


async def _run_command(
    args: list[str],
    *,
    timeout: float,
    cancel: asyncio.Event,
    stderr_path: Path,
    not_found_code: str = "audio_decoder_unavailable",
) -> bytes:
    """执行固定参数的媒体工具，支持取消、超时和有界错误输出。"""
    with stderr_path.open("wb") as stderr:
        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=stderr,
            )
        except FileNotFoundError:
            raise FullTranscriptionError(
                503, not_found_code, "server media decoder is unavailable"
            ) from None
    watcher = asyncio.create_task(_stop_on_cancel(process, cancel))
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        await _terminate(process)
        raise FullTranscriptionError(
            504, "audio_decode_timeout", "audio decoding timed out", retryable=True
        ) from None
    except asyncio.CancelledError:
        await _terminate(process)
        raise
    finally:
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)
    if cancel.is_set():
        raise asyncio.CancelledError
    if process.returncode:
        error = _read_tail(stderr_path)
        detail = "unsupported, invalid, or undecodable audio"
        if error:
            detail += f": {error[-1000:]}"
        raise FullTranscriptionError(415, "unsupported_audio", detail)
    return stdout


def _probe_metadata(stdout: bytes) -> tuple[int, int, float | None]:
    try:
        value = json.loads(stdout)
        stream = next(
            item for item in value.get("streams", []) if item.get("codec_type") == "audio"
        )
        sample_rate = int(stream["sample_rate"])
        channels = int(stream["channels"])
    except (ValueError, KeyError, TypeError, StopIteration):
        raise FullTranscriptionError(
            415, "unsupported_audio", "audio file has no readable audio stream"
        ) from None
    duration = None
    for candidate in (value.get("format", {}).get("duration"), stream.get("duration")):
        try:
            parsed = float(candidate)
        except (TypeError, ValueError):
            continue
        if math.isfinite(parsed) and parsed >= 0:
            duration = parsed
            break
    return sample_rate, channels, duration


async def decode_upload(
    file: UploadFile,
    directory: Path,
    cancel: asyncio.Event,
) -> DecodedAudio:
    """把整个上传转换为单声道 16 kHz PCM，并执行总时长和资源边界检查。"""
    source = directory / f"source{_safe_suffix(file.filename or 'audio')}"
    target = directory / "decoded.wav"
    source_sha256 = await _write_upload(file, source, cancel)
    metadata = await _run_command(
        [
            "ffprobe",
            "-v",
            "error",
            "-protocol_whitelist",
            "file",
            "-format_whitelist",
            SAFE_AUDIO_DEMUXERS,
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_type,sample_rate,channels,duration:format=duration",
            "-of",
            "json",
            str(source),
        ],
        timeout=min(60, settings.full_transcription_decode_timeout_seconds),
        cancel=cancel,
        stderr_path=directory / "ffprobe.log",
    )
    source_rate, channels, probed_duration = _probe_metadata(metadata)
    if source_rate <= 0 or source_rate > settings.full_transcription_max_source_sample_rate:
        raise FullTranscriptionError(
            422,
            "source_sample_rate_too_large",
            f"source sample rate must be 1-{settings.full_transcription_max_source_sample_rate} Hz",
        )
    if channels <= 0 or channels > settings.full_transcription_max_source_channels:
        raise FullTranscriptionError(
            422,
            "source_channels_too_large",
            f"source audio must have 1-{settings.full_transcription_max_source_channels} channels",
        )
    maximum = settings.full_transcription_max_seconds
    if probed_duration is not None and probed_duration > maximum + 0.05:
        raise FullTranscriptionError(
            413,
            "audio_duration_too_large",
            f"audio duration exceeds the {maximum:g}-second limit",
        )

    # 多解出一秒用于识别缺失时长元数据的超限文件，
    # 随后由实际帧数做最终判断。
    await _run_command(
        [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-max_alloc",
            str(256 * 1024 * 1024),
            "-probesize",
            str(64 * 1024 * 1024),
            "-analyzeduration",
            "30000000",
            "-protocol_whitelist",
            "file",
            "-format_whitelist",
            SAFE_AUDIO_DEMUXERS,
            "-threads",
            "1",
            "-filter_threads",
            "1",
            "-i",
            str(source),
            "-map",
            "0:a:0",
            "-vn",
            "-sn",
            "-dn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            "-t",
            f"{maximum + 1:.6f}",
            "-map_metadata",
            "-1",
            "-bitexact",
            str(target),
        ],
        timeout=settings.full_transcription_decode_timeout_seconds,
        cancel=cancel,
        stderr_path=directory / "ffmpeg.log",
    )
    try:
        info = sf.info(target)
    except RuntimeError:
        raise FullTranscriptionError(
            415, "unsupported_audio", "decoded audio is unreadable"
        ) from None
    if info.samplerate != 16000 or info.frames <= 0:
        raise FullTranscriptionError(422, "empty_audio", "audio has no decodable samples")
    duration = info.frames / info.samplerate
    if duration > maximum + 1 / 16000:
        raise FullTranscriptionError(
            413,
            "audio_duration_too_large",
            f"audio duration exceeds the {maximum:g}-second limit",
        )
    try:
        samples, rate = await asyncio.to_thread(
            sf.read, target, dtype="float32", always_2d=False
        )
    except RuntimeError:
        raise FullTranscriptionError(
            415, "unsupported_audio", "decoded audio is unreadable"
        ) from None
    samples = np.asarray(samples, dtype=np.float32)
    if samples.ndim > 1:
        samples = samples[:, 0]
    if rate != 16000 or not len(samples):
        raise FullTranscriptionError(422, "empty_audio", "audio has no decodable samples")
    return DecodedAudio(
        samples=samples,
        duration=len(samples) / rate,
        source_sample_rate=source_rate,
        source_channels=channels,
        source_sha256=source_sha256,
    )


def segment_policy(limits: dict[str, Any] | None) -> SegmentPolicy:
    """从模型校准值推导可发送的段长；不添加任何未批准裕量。"""
    if not limits:
        raise FullTranscriptionError(
            503,
            "model_not_calibrated",
            "full-file transcription requires calibrated model input limits",
        )
    try:
        duration = float(limits["duration_seconds"])
        input_bytes = int(limits["input_bytes"])
        sample_rate = int(limits["sample_rate"])
    except (KeyError, TypeError, ValueError):
        raise FullTranscriptionError(
            503, "invalid_model_calibration", "model input limits are incomplete"
        ) from None
    if sample_rate < 16000:
        raise FullTranscriptionError(
            503,
            "invalid_model_calibration",
            "model calibration does not accept 16 kHz mono audio",
        )
    if not math.isfinite(duration) or duration <= 0 or input_bytes <= 44:
        raise FullTranscriptionError(
            503, "invalid_model_calibration", "model input limits are unusable"
        )
    by_duration = int(duration * 16000)
    by_bytes = (input_bytes - 44) // 2
    maximum = min(by_duration, by_bytes)
    if maximum < 1600:
        raise FullTranscriptionError(
            503, "invalid_model_calibration", "model segment limit is below 0.1 seconds"
        )
    return SegmentPolicy(
        max_samples=maximum,
        max_seconds=maximum / 16000,
        max_wav_bytes=44 + maximum * 2,
    )


def _quiet_cut(chunk: np.ndarray, maximum: int, rate: int) -> int:
    """在接近上限的一秒内选择能量最低点，尽量避开词中切分。"""
    frame = max(1, int(rate * 0.02))
    search_start = max(int(maximum * 0.8), maximum - rate)
    start = max(frame, min(search_start, maximum - frame))
    frames = chunk[start:maximum]
    count = len(frames) // frame
    if count < 2:
        return maximum
    energy = [
        float(np.mean(np.abs(frames[index * frame:(index + 1) * frame])))
        for index in range(count)
    ]
    quiet = min(range(count), key=energy.__getitem__)
    cut = start + (quiet + 1) * frame
    return cut if frame * 2 <= cut <= maximum else maximum


def _cap_chunk(
    start: float,
    chunk: np.ndarray,
    policy: SegmentPolicy,
    rate: int = 16000,
) -> list[tuple[float, np.ndarray]]:
    pieces: list[tuple[float, np.ndarray]] = []
    offset = 0
    while len(chunk) - offset > policy.max_samples:
        cut = _quiet_cut(chunk[offset:], policy.max_samples, rate)
        piece = chunk[offset:offset + cut]
        pieces.append((start + offset / rate, piece))
        offset += len(piece)
    tail = chunk[offset:]
    if len(tail):
        pieces.append((start + offset / rate, tail))
    return pieces


def split_parts(samples: np.ndarray, policy: SegmentPolicy) -> list[SpeechPart]:
    """短音频保持完整，长音频优先按 VAD 和低能量点切分。"""
    if not len(samples):
        return []
    if len(samples) <= policy.max_samples:
        # 短音频不切分，但仍用 VAD 排除模型对纯静音产生的幻觉文本。
        if vad_available():
            try:
                if not _speech_segments(samples, 16000):
                    return []
            except Exception:
                pass
        return [SpeechPart(0, 0.0, samples)]
    vad_failed = False
    try:
        speech = _speech_segments(samples, 16000, max_segment_seconds=None)
    except Exception:
        speech = []
        vad_failed = True
    if not speech and (vad_failed or not vad_available()):
        # VAD 不可用时仍提供有界服务，固定切分并在响应中保留真实时间偏移。
        speech = [(0.0, samples)]
    raw: list[tuple[float, np.ndarray]] = []
    for offset, chunk in speech:
        raw.extend(_cap_chunk(offset, chunk, policy))
        if len(raw) > settings.full_transcription_max_parts:
            break
    if len(raw) > settings.full_transcription_max_parts:
        raise FullTranscriptionError(
            413,
            "too_many_audio_parts",
            f"audio requires more than {settings.full_transcription_max_parts} parts",
        )
    return [
        SpeechPart(index, offset, chunk)
        for index, (offset, chunk) in enumerate(raw)
        if len(chunk)
    ]


def cache_identity(
    model: str,
    item: dict[str, Any],
    limits: dict[str, Any],
    source_sha256: str,
    language: str,
) -> dict[str, str]:
    """生成无持久化缓存所需的完整结果身份。"""
    files = []
    for role, relative in sorted((item.get("runtime", {}).get("files") or {}).items()):
        for part in str(relative).split(","):
            path = model_root(item) / part
            try:
                stat = path.stat()
                files.append(
                    [role, part, stat.st_size, stat.st_mtime_ns]
                )
            except OSError:
                files.append([role, part, None, None])
    model_revision = hashlib.sha256(
        json.dumps(
            {
                "model": model,
                "limits": limits,
                "files": files,
                "pipeline": PIPELINE_VERSION,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()[:16]
    cache_key = hashlib.sha256(
        json.dumps(
            {
                "source_sha256": source_sha256,
                "model_revision": model_revision,
                "language": language,
                "pipeline": PIPELINE_VERSION,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return {
        "processing_version": PIPELINE_VERSION,
        "model_revision": model_revision,
        "source_sha256": source_sha256,
        "key": cache_key,
    }


def full_transcription_metadata() -> dict[str, Any]:
    """公开全文件接口边界，供调用方在提交音频前判断。"""
    return {
        "endpoint": "/v1/audio/transcriptions/full",
        "processing_version": PIPELINE_VERSION,
        "max_upload_bytes": settings.max_upload_mb * 1024 * 1024,
        "max_duration_seconds": settings.full_transcription_max_seconds,
        "max_parts": settings.full_transcription_max_parts,
        "max_source_sample_rate": settings.full_transcription_max_source_sample_rate,
        "max_source_channels": settings.full_transcription_max_source_channels,
        "response_formats": sorted(RESPONSE_FORMATS),
    }
