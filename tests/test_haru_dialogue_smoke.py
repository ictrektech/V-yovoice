"""Haru 冒烟脚本的镜像参数和真实 WebSocket 会话回归。"""

from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/haru_dialogue_smoke.py"
spec = importlib.util.spec_from_file_location("haru_dialogue_smoke", SCRIPT)
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


def arguments(**changes):
    value = {
        "profile": "l4t",
        "image": "registry.example/v-voice:l4t",
        "audio": ROOT / "scripts/fixtures/haru-hello-24k.wav",
        "language": "en",
        "persona_id": "companion",
        "session_timeout": 90,
    }
    value.update(changes)
    return argparse.Namespace(**value)


def test_container_command_uses_isolated_gpu_runtime():
    for profile, expected in (("amd-cuda", "--gpus"), ("l4t", "--runtime"), ("thor", "--runtime")):
        command = smoke.container_command(
            arguments(profile=profile),
            Path("/models"),
            f"haru-{profile}",
        )
        assert expected in command
        assert "--network" in command and command[command.index("--network") + 1] == "none"
        assert "/models:/modelhub:ro" in command
        assert "VVOICE_HARU_IDLE_UNLOAD_SECONDS=0" in command


def test_smoke_audio_is_fixed_format():
    smoke.validate_audio(ROOT / "scripts/fixtures/haru-hello-24k.wav")
    with wave.open(str(ROOT / "scripts/fixtures/haru-hello-24k.wav"), "rb") as value:
        assert value.getframerate() == 24000
        assert value.getnchannels() == 1
        assert value.getsampwidth() == 2


def test_in_container_session_reports_ready_frame_end_and_clean_exit(tmp_path):
    worker = tmp_path / "speech"
    worker.write_text(
        f"""#!{sys.executable}
import base64
import json
import sys

print(json.dumps({{"type":"ready","protocol":4,"model":{{"name":"haru-4b","task":"dialogue","sample_rate":24000,"frame_samples":3200}}}}), flush=True)
frames = 0
for line in sys.stdin:
    value = json.loads(line)
    if value.get("type") == "chunk":
        print(json.dumps({{"type":"chunk","id":value["id"],"seq":frames,"pcm":base64.b64encode(b"\\0" * 6400).decode(),"text":"hello"}}), flush=True)
        frames += 1
    elif value.get("type") == "hang_up":
        print(json.dumps({{"type":"end","id":value["id"],"frames":frames,"samples":frames * 3200}}), flush=True)
        break
""",
        encoding="utf-8",
    )
    worker.chmod(0o755)
    model = tmp_path / "Haru-4B-Q8_0.gguf"
    with model.open("wb") as value:
        value.truncate(smoke.MODEL_SIZE)
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--in-container",
            "--profile",
            "l4t",
            "--audio",
            str(ROOT / "scripts/fixtures/haru-hello-24k.wav"),
            "--worker",
            str(worker),
            "--model",
            str(model),
            "--data-dir",
            str(tmp_path / "data"),
            "--session-timeout",
            "30",
        ],
        check=False,
        cwd=ROOT,
        env={**os.environ},
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert '"status": "PASS"' in result.stdout
    assert '"orphaned_workers": 0' in result.stdout
