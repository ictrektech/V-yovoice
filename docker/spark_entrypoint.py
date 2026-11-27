"""在同一个后端镜像内为 DGX Spark 选择兼容的 CUDA 运行库。"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from pathlib import Path


def spark_selected() -> bool:
    deployment = os.environ.get("V_SCHEDULER_BACKEND_CONFIG_B64")
    if deployment is not None:
        try:
            return json.loads(base64.b64decode(deployment, validate=True))["profile"] == "dgx-spark"
        except (ValueError, KeyError, TypeError):
            return False
    if os.environ.get("VVOICE_PROFILE") != "thor":
        return False
    try:
        hardware = subprocess.run(
            ["nvidia-smi", "--query-gpu=compute_cap", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=4, check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return any(line.strip() == "12.1" for line in hardware.stdout.splitlines())


runtime = Path("/opt/vvoice/spark-runtime")
if runtime.is_dir() and spark_selected():
    inherited = os.environ.get("PYTHONPATH")
    os.environ["PYTHONPATH"] = os.pathsep.join(filter(None, (str(runtime), inherited)))
os.execvp(sys.argv[1], sys.argv[1:])
