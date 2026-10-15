"""audio.cpp 模型目录映射；权重统一由 Model Hub 安装。"""
from __future__ import annotations

import json
import io
import os
from pathlib import Path

REPOSITORY = "vivibit/v-voice-audiocpp-gguf"


def speech_capabilities(row: dict) -> list[str]:
    family, variant = row["family"], row.get("variant", "")
    if family == "qwen3_tts":
        return ["voice_cloning"] if variant == "base" else ["voice_design"] if variant == "voicedesign" else ["builtin_voices", "voice_instruction"]
    if family in {"omnivoice", "voxcpm2", "breeze_tts"}:
        return ["voice_cloning", "voice_design"]
    if family == "kokoro_tts":
        return ["builtin_voices"]
    return ["voice_cloning", "emotion_control"]


def synthesize(item: dict, text: str, voice: str, speed: float, language: str = "", **options):
    import httpx
    import soundfile as sf
    from fastapi import HTTPException
    from .admission import current
    token = os.getenv("VVOICE_STUDIO_INTERNAL_TOKEN", "")
    if len(token) < 32:
        raise HTTPException(503, "Creative speech runtime unavailable")
    try:
        response = httpx.post("http://127.0.0.1:7080/internal/speech", json={
            "model": item["runtime"]["model_id"], "text": text, "voice": voice, "speed": speed,
            "language": language, **options,
        }, headers={"Authorization": f"Bearer {token}"}, timeout=1800)
    except httpx.HTTPError:
        execution = current.get()
        if execution is not None:
            execution.uncertain = True
        raise HTTPException(503, "Creative speech stop state is unknown") from None
    if response.status_code != 200:
        raise HTTPException(422, "Creative speech model needs ready weights and valid reference/voice settings")
    samples, rate = sf.read(io.BytesIO(response.content), dtype="float32")
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    return samples, int(rate)


def models() -> list[dict]:
    root = Path(__file__).resolve().parents[1]
    source = root / "internal" / "catalog" / "catalog.json"
    if not source.is_file():
        source = root / "catalog" / "audio-cpp.json"
    if not source.is_file():
        return []
    selection_path = root / "internal" / "catalog" / "vos.json"
    if not selection_path.is_file():
        selection_path = root / "catalog" / "audio-cpp-vos.json"
    selection = json.loads(selection_path.read_text())
    result = []
    for row in json.loads(source.read_text()):
        if row.get("task") in {"gen", "instrument"}:
            continue
        # 仅导入模型由管理员校验原文件后发布到同一 ModelScope 仓库，不能伪造下载来源。
        files = row.get("files") or [{"path": row["remotePath"] or f"imports/{row['id']}.gguf", "size": row["size"], "sha256": row["sha256"]}]
        if row.get("repo"):
            files = [{**f, "path": f"mirrors/{row['repo']}/{f['path']}"} for f in files]
        voices = row.get("voices") or (["Vivian", "Serena", "Uncle_Fu", "Dylan", "Eric", "Ryan", "Aiden", "Ono_Anna", "Sohee"] if row.get("variant") == "customvoice" else [])
        result.append({
            "key": f"audiocpp-{row['id']}", "name": f"{row['name']} {row['precision']}",
            "kind": "tts", "family": row["family"], "backend": "audio.cpp",
            "description": "Creative speech synthesis through audio.cpp.",
            "capabilities": speech_capabilities(row),
            "languages": [], "modelscope_repo": selection["modelscope_repo"],
            "runtime": {"family": "audio_cpp", "model_id": row["id"],
                        "files": {f"file_{i}": f["path"] for i, f in enumerate(files)}},
            "shared_files": files, "voices": {v: {"language": "", "sid": i} for i, v in enumerate(voices or ["default"])},
        })
    return result
