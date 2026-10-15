#!/usr/bin/env python3
"""在隔离镜像容器内验收品牌、旧目录、私有原生推理及未配置调度时的拒绝行为。"""
import hashlib
import base64
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request


def request(path, body=None, token=""):
    data = None if body is None else json.dumps(body).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(path, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=180) as response:
        return response.read()


def main():
    # 与镜像的 python -m 启动方式一致，读取 /app 中当前源码而非旧安装副本。
    sys.path.insert(0, "/app")
    assert hashlib.sha256(Path("/app/catalog/models.json").read_bytes()).hexdigest() == (
        "3f5eaa724ca756ead7f711096a41a2075cba9e935cea1952138cb12241e8c835")
    assert len(json.loads(Path("/app/catalog/audio-cpp.json").read_text())) == 38
    from vvoice.catalog import catalog
    assert len(catalog()) > 17
    from vvoice.main import app
    assert "/v1/audio/transcriptions" in {route.path for route in app.routes}
    sample = os.getenv("VVOICE_IMAGE_SEACO_SAMPLE")
    if sample:
        import soundfile
        from vvoice.catalog import resolve_files
        from vvoice.seaco import SeacoRecognizer
        samples, rate = soundfile.read(sample, dtype="float32")
        model = next(row for row in catalog() if row["key"] == "seaco-paraformer-zh")
        recognizer = SeacoRecognizer(resolve_files(model), 4)
        result = recognizer.transcribe(samples, rate, ["魔搭"])
        assert "魔搭" in result["text"], result["text"]
        assert "torch" not in sys.modules and "funasr" not in sys.modules
        del recognizer
        print("PASS: retained SeACo ONNX inference and request-scoped hotword")
    assert hashlib.sha256(Path("/opt/vvoice/web/v-voice.png").read_bytes()).hexdigest() == (
        "1bbcbdd36858d396f86b5894720003de39441029340ce625795417ae2fa51db0")
    secret = secrets.token_hex(32)
    with tempfile.TemporaryDirectory(prefix="voice-image-check-") as root:
        env = {**os.environ, "VVOICE_STUDIO_DATA_DIR": root,
               "VVOICE_STUDIO_INTERNAL_TOKEN": secret,
               "VVOICE_SCHEDULER_CONFIG": root + "/not-configured.json"}
        children = []
        try:
            children.append(subprocess.Popen(["/opt/vvoice/vvoice-studio"], env=env))
            children.append(subprocess.Popen([
                "python3", "-m", "uvicorn", "vvoice.main:app", "--host", "127.0.0.1", "--port", "7070"
            ], env=env))
            for port in (7080, 7070):
                for _ in range(120):
                    try:
                        request(f"http://127.0.0.1:{port}/health")
                        break
                    except (OSError, urllib.error.URLError):
                        time.sleep(0.5)
                else:
                    raise AssertionError(f"service did not start: {port}")
            assert b"<title>V-Voice</title>" in request("http://127.0.0.1:7070/")
            assert b"<html" in request("http://127.0.0.1:7070/service/")
            assert b"/v1/audio/speech" in request("http://127.0.0.1:7070/openapi.json")
            for _ in range(120):
                discovery = json.loads(request("http://127.0.0.1:7070/api/v1/discovery"))
                if any(model["id"] == "audiocpp-kokoro-82m-q8" for model in discovery["models"]):
                    break
                time.sleep(0.5)
            else:
                raise AssertionError("verified model did not become ready")
            try:
                request("http://127.0.0.1:7070/v1/audio/speech", {
                    "model": "audiocpp-kokoro-82m-q8", "input": "Hello.", "voice": "af_heart"})
                raise AssertionError("unconfigured Scheduler admitted public inference")
            except urllib.error.HTTPError as error:
                assert error.code == 503, error.code
            audio = request("http://127.0.0.1:7080/internal/speech", {
                "model": "kokoro-82m-q8", "text": "Hello, welcome to V Voice.",
                "voice": "af_heart", "language": "en", "speed": 1,
            }, secret)
            assert audio[:4] == b"RIFF" and len(audio) > 24000
            if os.getenv("VVOICE_IMAGE_CHECK_CLONING") == "1":
                cloned = request("http://127.0.0.1:7080/internal/speech", {
                    "model": "index-2.5-q8", "text": "Hello, welcome to our studio.", "language": "en", "speed": 1,
                    "reference_audio": base64.b64encode(audio).decode(),
                    "reference_text": "Hello, welcome to V Voice.",
                }, secret)
                assert cloned[:4] == b"RIFF" and len(cloned) > 24000
                print("PASS: native IndexTTS cloning with a generated synthetic reference")
            tasks = Path(f"/proc/{children[0].pid}/task")
            for thread in tasks.iterdir():
                try:
                    assert not (thread / "children").read_text().strip()
                except FileNotFoundError:
                    pass
            print("PASS: packaged logo, 17 legacy descriptors, 38 creative variants, UI/API, fail-closed admission, native speech and confirmed unload")
        finally:
            for child in reversed(children):
                child.terminate()
            for child in children:
                try:
                    child.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()


if __name__ == "__main__":
    main()
