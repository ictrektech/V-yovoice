from __future__ import annotations

import asyncio
import contextlib
import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import HTTPException, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

MAX_INPUT_BYTES = 200 * 1024 * 1024
_export_lock = asyncio.Lock()


async def _save(source: UploadFile, target: Path, remaining: int) -> int:
    with target.open("wb") as output:
        while chunk := await source.read(1024 * 1024):
            remaining -= len(chunk)
            if remaining < 0:
                raise HTTPException(413, "Video export inputs exceed 200 MiB")
            output.write(chunk)
    return remaining


async def _run(*command: str, timeout: int) -> bytes:
    process = await asyncio.create_subprocess_exec(
        *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(), timeout)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        with contextlib.suppress(ProcessLookupError):
            process.kill()
        await process.wait()
        raise
    if process.returncode:
        raise ValueError("Unsupported or damaged media")
    return output


async def export_video(
    video: UploadFile,
    dub: UploadFile,
    captions: UploadFile | None,
    background: UploadFile | None,
    default_track: str,
) -> FileResponse:
    if _export_lock.locked():
        raise HTTPException(429, "Another video export is in progress")
    async with _export_lock:
        work = TemporaryDirectory(prefix="vvoice-dub-")
        root = Path(work.name)
        video_path, dub_path = root / "source.mp4", root / "dub.wav"
        subtitle_path, background_path, output = root / "captions.srt", root / "background.wav", root / "dubbed.mp4"
        try:
            remaining = await _save(video, video_path, MAX_INPUT_BYTES)
            remaining = await _save(dub, dub_path, remaining)
            if captions:
                remaining = await _save(captions, subtitle_path, remaining)
            if background:
                await _save(background, background_path, remaining)
            data = await _run(
                "ffprobe", "-v", "error", "-protocol_whitelist", "file",
                "-f", "mov", "-show_entries", "stream=codec_type,duration:format=duration",
                "-of", "json", str(video_path), timeout=20,
            )
            media = json.loads(data)
            streams = media.get("streams", [])
            stream = next((s for s in streams if s["codec_type"] == "video"), {})
            duration = float(stream.get("duration") or media.get("format", {}).get("duration") or 0)
            if not stream or not math.isfinite(duration) or not 0 < duration <= 3600:
                raise ValueError("Expected a video of up to one hour")
            original = any(s["codec_type"] == "audio" for s in streams)
            inputs = ["-protocol_whitelist", "file", "-f", "mov", "-i", str(video_path),
                      "-protocol_whitelist", "file", "-f", "wav", "-i", str(dub_path)]
            filters = "[1:a:0]apad[dub]"
            if background:
                inputs += ["-protocol_whitelist", "file", "-f", "wav", "-i", str(background_path)]
                filters = "[1:a:0]apad[voice];[voice][2:a:0]amix=inputs=2:duration=first:weights='1 0.25':normalize=0,alimiter=limit=0.95[dub]"
            tracks = ["-map", "0:v:0", "-map", "[dub]"]
            if original:
                tracks += ["-map", "0:a:0", "-metadata:s:a:1", "handler_name=Original",
                           "-disposition:a:1", "default" if default_track == "original" else "0"]
            if captions:
                index = 3 if background else 2
                inputs += ["-protocol_whitelist", "file", "-f", "srt", "-i", str(subtitle_path)]
                tracks += ["-map", f"{index}:s:0", "-c:s", "mov_text"]
            await _run(
                "ffmpeg", "-nostdin", "-v", "error", "-filter_complex_threads", "1", *inputs,
                "-filter_complex", filters, *tracks, "-c:v", "copy", "-c:a", "aac",
                "-metadata:s:a:0", "handler_name=Dub", "-disposition:a:0",
                "default" if not original or default_track == "dub" else "0", "-map_metadata", "-1",
                "-t", str(duration), "-movflags", "+faststart", str(output), timeout=180,
            )
        except asyncio.TimeoutError:
            work.cleanup()
            raise HTTPException(504, "Video export timed out") from None
        except (ValueError, KeyError, TypeError):
            work.cleanup()
            raise HTTPException(422, "Unsupported or damaged media; use MP4 video, WAV audio and SRT subtitles") from None
        except BaseException:
            work.cleanup()
            raise
        return FileResponse(output, filename="dubbed.mp4", media_type="video/mp4", background=BackgroundTask(work.cleanup))
