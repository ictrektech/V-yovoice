import asyncio
import io
import json
import shutil
import subprocess

from fastapi import UploadFile
import pytest

from vvoice.video_export import export_video


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="需要 FFmpeg")
def test_export_video_muxes_original_dub_and_subtitle(tmp_path):
    video = tmp_path / "source.mp4"
    wav = tmp_path / "voice.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=64x64:r=10",
                    "-f", "lavfi", "-i", "sine=frequency=500", "-t", "2", "-c:v", "mpeg4",
                    "-c:a", "aac", str(video)], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=900",
                    "-t", "1", str(wav)], check=True)
    caption = UploadFile(io.BytesIO(b"1\n00:00:00,000 --> 00:00:01,000\nHello\n"))
    with video.open("rb") as source, wav.open("rb") as voice, wav.open("rb") as bg:
        result = asyncio.run(export_video(UploadFile(source), UploadFile(voice), caption, UploadFile(bg), "original"))
    try:
        report = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-show_streams",
                                                     "-show_format", "-of", "json", result.path]))
        streams = report["streams"]
        assert [stream["codec_type"] for stream in streams] == ["video", "audio", "audio", "subtitle"]
        assert streams[1]["tags"]["handler_name"] == "Dub"
        assert streams[2]["tags"]["handler_name"] == "Original"
        assert [stream["disposition"]["default"] for stream in streams[1:3]] == [0, 1]
        assert 1.95 <= float(report["format"]["duration"]) <= 2.05
    finally:
        asyncio.run(result.background())
