#!/usr/bin/env python3
"""在构建机上对 V-yovoice 候选镜像做无持久化冒烟检查。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shlex
import subprocess
import sys


PROFILES = {
    "amd-cuda": {
        "architecture": "amd64",
        "docker_runtime": ["--gpus", "all"],
        "sherpa_suffix": "+cuda12",
        "requires_onnx_cuda": False,
        "requires_speech_cuda": True,
    },
    "l4t": {
        "architecture": "arm64",
        "docker_runtime": [
            "--runtime", "nvidia",
            "-e", "NVIDIA_VISIBLE_DEVICES=all",
            "-e", "NVIDIA_DRIVER_CAPABILITIES=compute,utility",
        ],
        "sherpa_suffix": "+cuda12",
        "requires_onnx_cuda": True,
        "requires_speech_cuda": True,
    },
    "thor": {
        "architecture": "arm64",
        "docker_runtime": [
            "--runtime", "nvidia",
            "-e", "NVIDIA_VISIBLE_DEVICES=all",
            "-e", "NVIDIA_DRIVER_CAPABILITIES=compute,utility",
        ],
        "sherpa_suffix": "+cuda13",
        "requires_onnx_cuda": True,
        "requires_speech_cuda": True,
    },
}

CONTAINER_CHECK = r"""
import hashlib
import json
import pathlib
import subprocess
import sys

paths = [
    pathlib.Path("/opt/vvoice/vvoice-studio"),
    pathlib.Path("/opt/vvoice/audiocpp/audiocpp_server"),
    pathlib.Path("/opt/vvoice/speechcpp/speech"),
    pathlib.Path("/opt/vvoice/web/index.html"),
    pathlib.Path("/app/catalog/audio-cpp.json"),
]
missing = [str(path) for path in paths if not path.is_file()]
if missing:
    raise SystemExit("missing required files: " + ", ".join(missing))

import importlib.util
forbidden = [
    name for name in ("torch", "torchaudio", "transformers", "diffusers")
    if importlib.util.find_spec(name) is not None
]
if forbidden:
    raise SystemExit("forbidden runtime packages: " + ", ".join(forbidden))

import onnxruntime
import sherpa_onnx

catalog_path = pathlib.Path("/app/catalog/audio-cpp.json")
catalog_bytes = catalog_path.read_bytes()
catalog = json.loads(catalog_bytes)
models = catalog.get("models")
if not isinstance(models, list) or not models:
    raise SystemExit("catalog has no models")
ids = [model.get("id") for model in models if isinstance(model, dict)]
if len(ids) != len(models) or any(not isinstance(model_id, str) or not model_id for model_id in ids):
    raise SystemExit("catalog contains invalid model entries")
if len(set(ids)) != len(ids):
    raise SystemExit("catalog contains duplicate model IDs")
catalog_sha256 = hashlib.sha256(catalog_bytes).hexdigest()
expected_catalog_sha256 = sys.argv[2]
if expected_catalog_sha256 and catalog_sha256 != expected_catalog_sha256:
    raise SystemExit(
        f"catalog sha256 is {catalog_sha256}, expected {expected_catalog_sha256}"
    )

providers = onnxruntime.get_available_providers()
has_cuda = "CUDAExecutionProvider" in providers
requires_onnx_cuda = sys.argv[1] == "true"
if has_cuda != requires_onnx_cuda:
    raise SystemExit(f"unexpected onnx providers: {providers}")

linked = subprocess.run(
    ["ldd", "/opt/vvoice/audiocpp/audiocpp_server"],
    check=True, capture_output=True, text=True,
).stdout
if "libcuda.so" not in linked or "libcudart.so" not in linked or "not found" in linked:
    raise SystemExit("audio.cpp is not linked to CUDA runtime")

requires_speech_cuda = sys.argv[3] == "true"
if requires_speech_cuda:
    speech_linked = subprocess.run(
        ["ldd", "/opt/vvoice/speechcpp/speech"],
        check=True, capture_output=True, text=True,
    ).stdout
    if (
        "libcuda.so" not in speech_linked
        or "libcudart.so" not in speech_linked
        or "not found" in speech_linked
    ):
        raise SystemExit("speech.cpp is not linked to CUDA runtime")

print(json.dumps({
    "model_count": len(models),
    "catalog_sha256": catalog_sha256,
    "providers": providers,
    "sherpa": sherpa_onnx.__version__,
    "cuda_linked": True,
    "speech_cuda_linked": requires_speech_cuda,
}))
"""


class SmokeError(RuntimeError):
    pass


def sha256_argument(value: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) != 64 or any(
        char not in "0123456789abcdef" for char in normalized
    ):
        raise argparse.ArgumentTypeError("expected a 64-character SHA256 hex digest")
    return normalized


def docker_run_command(
    image: str, profile: str, expected_catalog_sha256: str | None
) -> list[str]:
    config = PROFILES[profile]
    return [
        "docker", "run", "--rm",
        *config["docker_runtime"],
        "--entrypoint", "python3",
        image, "-c", CONTAINER_CHECK.strip(),
        "true" if config["requires_onnx_cuda"] else "false",
        expected_catalog_sha256 or "",
        "true" if config["requires_speech_cuda"] else "false",
    ]


def remote_script(
    image: str, profile: str, expected_catalog_sha256: str | None
) -> str:
    run = docker_run_command(image, profile, expected_catalog_sha256)
    return (
        "set -euo pipefail\n"
        f"architecture=\"$(docker image inspect {shlex.quote(image)} "
        "--format '{{.Architecture}}')\"\n"
        f"result=\"$({shlex.join(run)})\"\n"
        "printf '%s\\n%s\\n' \"$architecture\" \"$result\"\n"
    )


def ssh_command(
    host: str,
    image: str,
    profile: str,
    expected_catalog_sha256: str | None = None,
) -> str:
    script = f"""
{remote_script(image, profile, expected_catalog_sha256)}
"""
    return (
        f"ssh -o BatchMode=yes -o ConnectTimeout=8 {shlex.quote(host)} bash -s <<'EOF'"
        f"{script}EOF"
    )


def check(
    host: str,
    image: str,
    profile: str,
    timeout: int,
    expected_catalog_sha256: str | None,
) -> dict:
    config = PROFILES[profile]
    result = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", host, "bash", "-s"],
        input=remote_script(image, profile, expected_catalog_sha256),
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise SmokeError(result.stderr.strip() or f"remote check exited {result.returncode}")
    lines = result.stdout.strip().splitlines()
    if len(lines) != 2:
        raise SmokeError(f"unexpected remote output: {result.stdout[:300]}")
    architecture, payload = lines
    try:
        details = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise SmokeError(f"invalid container check output: {payload[:300]}") from exc
    errors = []
    if architecture != config["architecture"]:
        errors.append(
            f"image architecture is {architecture!r}, expected {config['architecture']!r}"
        )
    sherpa = str(details.get("sherpa", ""))
    if config["sherpa_suffix"] not in sherpa:
        errors.append(
            f"Sherpa version {sherpa!r} does not contain {config['sherpa_suffix']!r}"
        )
    catalog_sha256 = str(details.get("catalog_sha256", ""))
    if expected_catalog_sha256 and catalog_sha256 != expected_catalog_sha256:
        errors.append(
            f"catalog SHA256 is {catalog_sha256!r}, expected {expected_catalog_sha256!r}"
        )
    return {
        "host": host,
        "image": image,
        "profile": profile,
        "architecture": architecture,
        "model_count": details.get("model_count"),
        "catalog_sha256": catalog_sha256,
        "providers": details.get("providers"),
        "sherpa": sherpa,
        "cuda_linked": details.get("cuda_linked"),
        "errors": errors,
        "ok": not errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ssh", required=True, help="SSH destination for the matching build host")
    parser.add_argument("--image", required=True, help="full image reference to check")
    parser.add_argument("--profile", required=True, choices=PROFILES)
    parser.add_argument(
        "--expected-catalog-sha256",
        type=sha256_argument,
        help="fail unless the image catalog matches this source-file SHA256",
    )
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.dry_run:
        print(
            ssh_command(
                args.ssh,
                args.image,
                args.profile,
                args.expected_catalog_sha256,
            )
        )
        return 0
    try:
        result = check(
            args.ssh,
            args.image,
            args.profile,
            args.timeout,
            args.expected_catalog_sha256,
        )
    except (subprocess.TimeoutExpired, OSError, SmokeError) as exc:
        result = {
            "host": args.ssh,
            "image": args.image,
            "profile": args.profile,
            "errors": [str(exc)],
            "ok": False,
        }
    details = "; ".join(result["errors"]) or (
        f"arch={result['architecture']} models={result['model_count']} "
        f"catalog_sha256={result['catalog_sha256'][:12]} "
        f"sherpa={result['sherpa']} cuda_linked={result['cuda_linked']}"
    )
    status = "ok" if result["ok"] else "failed"
    print(f"{result['profile']}\t{result['image']}\t{status}\t{details}")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
