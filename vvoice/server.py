"""在同一个 VOS 生命周期中管理兼容推理服务与声音创作工作台。"""
from __future__ import annotations

import os
import signal
import secrets
import threading
import subprocess
import uvicorn


def main() -> None:
    os.environ["VVOICE_STUDIO_INTERNAL_TOKEN"] = secrets.token_hex(32)
    studio = subprocess.Popen([os.getenv("VVOICE_STUDIO_BINARY", "/opt/vvoice/vvoice-studio")])
    stopping = threading.Event()
    def supervise():
        studio.wait()
        if not stopping.is_set():
            os.kill(os.getpid(), signal.SIGTERM)
    threading.Thread(target=supervise, daemon=True).start()
    try:
        uvicorn.run("vvoice.main:app", host=os.getenv("VVOICE_HOST", "0.0.0.0"),
                    port=int(os.getenv("VVOICE_PORT", "7070")))
    finally:
        stopping.set()
        if studio.poll() is None:
            studio.send_signal(signal.SIGTERM)
            try:
                studio.wait(timeout=15)
            except subprocess.TimeoutExpired:
                studio.kill()
                studio.wait()


if __name__ == "__main__":
    main()
