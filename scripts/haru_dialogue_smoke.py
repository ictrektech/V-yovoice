#!/usr/bin/env python3
"""对候选镜像执行真实 Haru worker 与 WebSocket 会话冒烟。"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import signal
import subprocess
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_AUDIO = ROOT / "scripts/fixtures/haru-hello-24k.wav"
MODEL_PATH = "/modelhub/export/hf/sakasegawa/Haru-4B-GGUF/current/Haru-4B-Q8_0.gguf"
WORKER_PATH = "/opt/vvoice/speechcpp/speech"
MODEL_SIZE = 6623102720
PROFILES = {
    "amd-cuda": {
        "architecture": "amd64",
        "runtime": ["--gpus", "all"],
    },
    "l4t": {
        "architecture": "arm64",
        "runtime": [
            "--runtime",
            "nvidia",
            "-e",
            "NVIDIA_VISIBLE_DEVICES=all",
            "-e",
            "NVIDIA_DRIVER_CAPABILITIES=compute,utility",
        ],
    },
    "thor": {
        "architecture": "arm64",
        "runtime": [
            "--runtime",
            "nvidia",
            "-e",
            "NVIDIA_VISIBLE_DEVICES=all",
            "-e",
            "NVIDIA_DRIVER_CAPABILITIES=compute,utility",
        ],
    },
}


class SmokeError(RuntimeError):
    pass


def run(command: list[str], *, timeout: int = 30, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(command, check=False, text=True, capture_output=True, timeout=timeout)
    if check and result.returncode:
        raise SmokeError(result.stderr.strip() or f"command exited {result.returncode}: {shlex.join(command)}")
    return result


def inspect_image(image: str, profile: str) -> None:
    result = run(["docker", "image", "inspect", image, "--format", "{{.Architecture}}"])
    actual = result.stdout.strip()
    expected = PROFILES[profile]["architecture"]
    if actual != expected:
        raise SmokeError(f"image architecture is {actual!r}, expected {expected!r}")


def discover_model_root() -> Path:
    names = run(["docker", "ps", "--format", "{{.Names}}"]).stdout.splitlines()
    roots = set()
    for name in names:
        if "v-voice" not in name:
            continue
        result = run([
            "docker", "inspect", name, "--format",
            '{{range .Mounts}}{{if eq .Destination "/modelhub"}}{{.Source}}{{end}}{{end}}',
        ])
        if result.stdout.strip():
            roots.add(Path(result.stdout.strip()))
    if len(roots) != 1:
        raise SmokeError(
            "cannot determine the shared model directory; pass --model-root "
            f"(found {sorted(map(str, roots))})"
        )
    return roots.pop()


def validate_audio(path: Path) -> None:
    import wave

    try:
        with wave.open(str(path), "rb") as value:
            valid = (
                value.getnchannels() == 1
                and value.getsampwidth() == 2
                and value.getframerate() == 24000
                and value.getnframes() > 0
            )
    except (OSError, EOFError, wave.Error) as exc:
        raise SmokeError(f"invalid smoke audio: {exc}") from None
    if not valid:
        raise SmokeError("smoke audio must be 24 kHz mono signed 16-bit PCM")


def container_command(args: argparse.Namespace, model_root: Path, name: str) -> list[str]:
    command = [
        "docker", "run", "--rm", "--name", name, "--network", "none",
        *PROFILES[args.profile]["runtime"],
        "--tmpfs", "/tmp:rw,noexec,nosuid,size=256m",
        "--tmpfs", "/data:rw,noexec,nosuid,size=64m",
        "-v", f"{model_root}:/modelhub:ro",
        "-v", f"{Path(__file__).resolve()}:/smoke.py:ro",
        "-v", f"{args.audio.resolve()}:/smoke.wav:ro",
        "-e", f"VVOICE_PROFILE={args.profile}",
        "-e", "VVOICE_SCHEDULER_REQUIRED=false",
        "-e", "VVOICE_STUDIO_ENABLED=false",
        "-e", "VVOICE_DATA_DIR=/data",
        "-e", f"VVOICE_HARU_WORKER={WORKER_PATH}",
        "-e", f"VVOICE_HARU_MODEL_PATH={MODEL_PATH}",
        "-e", "VVOICE_HARU_IDLE_UNLOAD_SECONDS=0",
        "-e", "VVOICE_HARU_SESSION_IDLE_SECONDS=15",
        "--entrypoint", "python3",
        args.image,
        "/smoke.py", "--in-container",
        "--profile", args.profile,
        "--audio", "/smoke.wav",
        "--worker", WORKER_PATH,
        "--model", MODEL_PATH,
        "--data-dir", "/data",
        "--language", args.language,
        "--persona-id", args.persona_id,
        "--session-timeout", str(args.session_timeout),
    ]
    return command


def cleanup_container(name: str) -> None:
    subprocess.run(
        ["docker", "rm", "-f", name],
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )


def validate_ready(value: dict) -> None:
    model = value.get("model") or {}
    if (
        value.get("type") != "ready"
        or value.get("protocol") != 4
        or model.get("task") != "dialogue"
        or model.get("sample_rate") != 24000
        or model.get("frame_samples") != 3200
    ):
        raise SmokeError(f"unexpected worker ready message: {value}")


def matching_workers(worker: Path, model: Path) -> list[int]:
    if not Path("/proc").is_dir():
        return []
    matches = []
    for entry in Path("/proc").glob("[0-9]*"):
        try:
            fields = entry.joinpath("cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        if not fields or fields[0] != os.fsencode(worker):
            continue
        if b"worker" in fields and os.fsencode(model) in fields:
            matches.append(int(entry.name))
    return matches


def wait_for_unloaded(manager, exit_codes: list[int], seconds: float = 15) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if manager.state == "unloaded" and manager.worker is None and exit_codes:
            return
        time.sleep(0.1)
    raise SmokeError(
        f"worker did not unload: state={manager.state} worker={manager.worker!r} exits={exit_codes}"
    )


def in_container(args: argparse.Namespace) -> int:
    import wave
    from urllib.parse import quote

    from fastapi.testclient import TestClient

    from vvoice.dialogue import MODEL_KEY, SpeechWorker, manager
    from vvoice.main import app

    worker = args.worker.resolve()
    model = args.model.resolve()
    if not worker.is_file():
        raise SmokeError(f"worker is missing: {worker}")
    if not model.is_file() or model.stat().st_size != MODEL_SIZE:
        raise SmokeError(f"Haru model is missing or has the wrong size: {model}")

    ready_values: list[dict] = []
    exit_codes: list[int] = []
    original_start = SpeechWorker.start
    original_stop = SpeechWorker.stop

    async def start(value):
        await original_start(value)
        ready_values.append(value.ready.result())

    async def stop(value):
        result = await original_stop(value)
        if value.process is not None and value.process.returncode is not None:
            exit_codes.append(value.process.returncode)
        return result

    SpeechWorker.start = start
    SpeechWorker.stop = stop

    with wave.open(str(args.audio), "rb") as value:
        pcm = value.readframes(value.getnframes())
    pcm += b"\0" * (6400 * 4)

    def expire(_signum, _frame):
        raise SmokeError(f"session exceeded {args.session_timeout} seconds")

    signal.signal(signal.SIGALRM, expire)
    signal.setitimer(signal.ITIMER_REAL, args.session_timeout)
    frames: list[int] = []
    texts: list[str] = []
    ended: dict = {}
    try:
        ticket, _ = manager.tickets.issue("haru-smoke", args.language, args.persona_id, 60)
        with TestClient(app) as client:
            with client.websocket_connect(
                f"/api/v1/dialogue/ws?ticket={quote(ticket)}"
            ) as websocket:
                websocket.send_json({"type": "start", "protocol": 1})
                started = False
                while not started:
                    event = websocket.receive()
                    if event.get("text") is not None:
                        message = json.loads(event["text"])
                        if message.get("type") == "loading":
                            continue
                        if message.get("type") == "started":
                            started = True
                            continue
                        if message.get("type") == "error":
                            raise SmokeError(f"start failed: {message}")
                        raise SmokeError(f"unexpected start message: {message}")
                    if event.get("bytes") is not None:
                        raise SmokeError("audio arrived before the session started")
                    raise SmokeError(f"websocket closed during start: {event}")

                for offset in range(0, len(pcm), 6400):
                    websocket.send_bytes(pcm[offset:offset + 6400])
                    time.sleep(3200 / 24000)
                time.sleep(0.3)
                websocket.send_json({"type": "hang_up"})

                while True:
                    event = websocket.receive()
                    if event.get("bytes") is not None:
                        frames.append(len(event["bytes"]))
                    elif event.get("text") is not None:
                        message = json.loads(event["text"])
                        if message.get("type") == "text":
                            texts.append(str(message.get("text") or ""))
                        elif message.get("type") == "end":
                            ended = message
                            break
                        elif message.get("type") == "error":
                            raise SmokeError(f"dialogue failed: {message}")
                    elif event.get("type") == "websocket.close":
                        raise SmokeError("websocket closed without an end event")

            wait_for_unloaded(manager, exit_codes)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        SpeechWorker.start = original_start
        SpeechWorker.stop = original_stop

    if not ready_values:
        raise SmokeError("worker never reported ready")
    validate_ready(ready_values[0])
    if not frames:
        raise SmokeError("dialogue produced no audio frame")
    if any(size != 6400 for size in frames):
        raise SmokeError(f"dialogue emitted invalid frame sizes: {frames}")
    if ended.get("type") != "end" or int(ended.get("frames") or 0) <= 0:
        raise SmokeError(f"dialogue did not end normally: {ended}")
    if not exit_codes or any(code != 0 for code in exit_codes):
        raise SmokeError(f"worker did not exit cleanly: {exit_codes}")

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        orphans = matching_workers(args.worker, args.model)
        if not orphans:
            break
        time.sleep(0.2)
    else:
        raise SmokeError(f"orphaned Haru workers remain: {orphans}")
    if manager._state_path().exists():
        raise SmokeError("Haru residency state was not cleared")

    print(
        json.dumps(
            {
                "status": "PASS",
                "model": MODEL_KEY,
                "frames": len(frames),
                "frame_bytes": frames[0],
                "text_events": len(texts),
                "reason": ended.get("reason"),
                "worker_exit_code": exit_codes[-1],
                "orphaned_workers": 0,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def host(args: argparse.Namespace) -> int:
    validate_audio(args.audio)
    if not args.image:
        raise SmokeError("--image is required outside the container")
    inspect_image(args.image, args.profile)
    model_root = args.model_root.expanduser().resolve() if args.model_root else discover_model_root()
    name = f"v-voice-haru-smoke-{os.getpid()}"
    command = container_command(args, model_root, name)
    if args.dry_run:
        print(shlex.join(command))
        return 0
    try:
        result = subprocess.run(
            command,
            check=False,
            text=True,
            capture_output=True,
            timeout=args.timeout,
        )
    except subprocess.TimeoutExpired:
        cleanup_container(name)
        raise SmokeError(f"container exceeded {args.timeout} seconds") from None
    finally:
        cleanup_container(name)
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise SmokeError(f"container exited {result.returncode}: {detail[-2000:]}")
    payload = next(
        (line for line in reversed(result.stdout.splitlines()) if line.startswith("{")),
        "",
    )
    try:
        details = json.loads(payload)
    except json.JSONDecodeError:
        raise SmokeError(f"smoke produced no JSON result: {result.stdout[-1000:]}") from None
    if details.get("status") != "PASS":
        raise SmokeError(f"smoke failed: {details}")
    print(json.dumps(details, ensure_ascii=False, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image")
    parser.add_argument("--profile", required=True, choices=PROFILES)
    parser.add_argument("--model-root", type=Path)
    parser.add_argument("--audio", type=Path, default=DEFAULT_AUDIO)
    parser.add_argument("--language", choices=("zh", "en"), default="en")
    parser.add_argument("--persona-id", choices=("companion", "study", "interview"), default="companion")
    parser.add_argument("--session-timeout", type=int, default=90)
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--in-container", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--worker", type=Path, default=Path(WORKER_PATH), help=argparse.SUPPRESS)
    parser.add_argument("--model", type=Path, default=Path(MODEL_PATH), help=argparse.SUPPRESS)
    parser.add_argument("--data-dir", type=Path, default=Path("/data"), help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.in_container:
        os.environ.update({
            "VVOICE_PROFILE": args.profile,
            "VVOICE_SCHEDULER_REQUIRED": "false",
            "VVOICE_STUDIO_ENABLED": "false",
            "VVOICE_DATA_DIR": str(args.data_dir),
            "VVOICE_HARU_WORKER": str(args.worker),
            "VVOICE_HARU_MODEL_PATH": str(args.model),
            "VVOICE_HARU_IDLE_UNLOAD_SECONDS": "0",
            "VVOICE_HARU_SESSION_IDLE_SECONDS": "15",
        })
        return in_container(args)
    return host(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, SmokeError, subprocess.TimeoutExpired) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
    except Exception:  # noqa: BLE001 - 顶层打印完整栈后转为退出码
        traceback.print_exc()
        raise SystemExit(1)
