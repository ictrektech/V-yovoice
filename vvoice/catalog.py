from __future__ import annotations

import json
import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Any

from .config import settings


@lru_cache(maxsize=128)
def _shared_hash(path: str, size: int, modified: int) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


ASR_FACTORIES = {
    "from_transducer", "from_sense_voice", "from_funasr_nano", "from_qwen3_asr",
    "from_paraformer", "from_telespeech_ctc", "from_dolphin_ctc", "from_fire_red_asr_ctc",
    "from_medasr_ctc", "from_omnilingual_asr_ctc", "from_zipformer_ctc", "from_nemo_ctc",
    "from_nemo_canary", "from_whisper", "from_fire_red_asr", "from_cohere_transcribe",
    "from_moonshine", "from_moonshine_v2", "from_tdnn_ctc", "from_wenet_ctc", "seaco_onnx",
}
# Factories valid on OnlineRecognizer for streaming-capable ASR descriptors.
STREAMING_FACTORIES = {"from_transducer", "from_paraformer"}
SPEAKER_FACTORIES = {"speaker_embedding"}
TTS_FAMILIES = {"vits", "matcha", "kokoro", "zipvoice", "kitten", "pocket", "supertonic", "audio_cpp"}


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def validate_descriptor(value: dict[str, Any], source: str = "descriptor") -> dict[str, Any]:
    key = str(value.get("key") or "").strip()
    kind = str(value.get("kind") or "").strip().lower()
    runtime = value.get("runtime")
    if not key or kind not in {"asr", "tts", "speaker"} or not isinstance(runtime, dict):
        raise ValueError(f"{source}: key, kind(asr|tts|speaker), and runtime are required")
    streaming = bool(value.get("streaming", False))
    if kind == "asr":
        factory = runtime.get("factory")
        if streaming:
            if factory not in STREAMING_FACTORIES:
                raise ValueError(f"{source}: streaming ASR factory {factory!r} is not supported by OnlineRecognizer")
        elif factory not in ASR_FACTORIES:
            raise ValueError(f"{source}: unsupported ASR factory {factory!r}")
    if kind == "tts":
        if streaming:
            raise ValueError(f"{source}: streaming is only valid for ASR models")
        if runtime.get("family") not in TTS_FAMILIES:
            raise ValueError(f"{source}: unsupported TTS family {runtime.get('family')!r}")
    if kind == "speaker":
        if streaming:
            raise ValueError(f"{source}: streaming is only valid for ASR models")
        if runtime.get("factory") not in SPEAKER_FACTORIES:
            raise ValueError(f"{source}: unsupported speaker factory {runtime.get('factory')!r}")
    files = runtime.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError(f"{source}: runtime.files must be a non-empty object")
    for field, relative in files.items():
        path = Path(str(relative))
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"{source}: invalid runtime file {field}={relative}")
    return value


@lru_cache(maxsize=1)
def catalog() -> list[dict[str, Any]]:
    value = _read_json(settings.catalog_path)
    models = value.get("models")
    if not isinstance(models, list):
        raise ValueError("catalog models must be a list")
    from .creative import models as creative_models
    models = [*models, *creative_models()]
    result = [validate_descriptor(item, f"catalog.models[{index}]") for index, item in enumerate(models)]
    keys = [item["key"] for item in result]
    if len(keys) != len(set(keys)):
        raise ValueError("catalog model keys must be unique")
    return result


def model_root(item: dict[str, Any]) -> Path:
    repo = str(item["modelscope_repo"])
    return settings.modelhub_root / "export" / "ms" / repo / "current"


def descriptor_for(item: dict[str, Any]) -> dict[str, Any]:
    root = model_root(item)
    local = root / "vvoice-model.json"
    if local.is_file():
        descriptor = validate_descriptor(_read_json(local), str(local))
        merged = dict(item)
        merged.update(descriptor)
        runtime = dict(item["runtime"])
        runtime.update(descriptor["runtime"])
        runtime["files"] = {**item["runtime"].get("files", {}), **descriptor["runtime"].get("files", {})}
        runtime["options"] = {
            **item["runtime"].get("options", {}),
            **descriptor["runtime"].get("options", {}),
        }
        merged["runtime"] = runtime
        return merged
    return item


def resolve_files(item: dict[str, Any]) -> dict[str, str]:
    root = model_root(item).resolve()
    resolved: dict[str, str] = {}
    for field, relative in item["runtime"]["files"].items():
        targets = []
        for part in str(relative).split(","):
            target = (root / part).resolve()
            if target != root and root not in target.parents:
                raise ValueError(f"model file escapes repository: {part}")
            if not target.exists():
                raise FileNotFoundError(target)
            targets.append(str(target))
        resolved[field] = ",".join(targets)
    return resolved


def model_files_ready(item: dict[str, Any]) -> tuple[bool, str]:
    """Check the merged catalog/installed descriptor without loading a model."""
    try:
        resolve_files(descriptor_for(item))
        for file in item.get("shared_files", []):
            path = (model_root(item) / file["path"]).resolve()
            stat = path.stat()
            if stat.st_size != file["size"] or _shared_hash(str(path), stat.st_size, stat.st_mtime_ns) != file["sha256"]:
                raise ValueError("shared model file size mismatch")
    except (FileNotFoundError, ValueError) as exc:
        return False, str(exc)
    return True, ""


def find_model(key: str, kind: str | None = None) -> dict[str, Any]:
    for item in catalog():
        if item["key"] == key and (kind is None or item["kind"] == kind):
            return descriptor_for(item)
    raise KeyError(key)
