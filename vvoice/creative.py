"""audio.cpp 模型目录映射；权重统一由 V-Scheduler 内置模型仓库安装。"""
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
    if family in {"omnivoice", "voxcpm2", "breeze_tts", "ming3_tts"}:
        return ["voice_cloning", "voice_design"]
    if family == "plapre":
        return ["builtin_voices", "voice_cloning"]
    if family in {"xtts_v2", "fish_drama3"}:
        return ["voice_cloning"]
    if family in {"kokoro_tts", "voxtral_tts", "gradium_phonon"}:
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


def models(include_non_speech: bool = False) -> list[dict]:
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
    previous_path = source.with_name("previous-model-files.json")
    previous = {row["id"]: row for row in json.loads(previous_path.read_text())} if previous_path.is_file() else {}
    result = []
    for row in json.loads(source.read_text()):
        non_speech = row.get("task") in {"gen", "instrument", "midi", "align"}
        if non_speech and not include_non_speech:
            continue
        # 仅导入模型由管理员校验原文件后发布到同一 ModelScope 仓库，不能伪造下载来源。
        files = row.get("files") or [{"path": row["remotePath"] or f"imports/{row['id']}.gguf", "size": row["size"], "sha256": row["sha256"]}]
        if row.get("repo"):
            files = [{**f, "path": f"mirrors/{row['repo']}/{f['path']}"} for f in files]
        old = previous.get(row["id"])
        old_files = []
        if old:
            old_files = old.get("files") or [{"path": row["remotePath"], "size": old["size"], "sha256": old["sha256"]}]
            if row.get("repo"):
                old_files = [{**f, "path": f"mirrors/{row['repo']}/{f['path']}"} for f in old_files]
        voices = row.get("voices") or (["Vivian", "Serena", "Uncle_Fu", "Dylan", "Eric", "Ryan", "Aiden", "Ono_Anna", "Sohee"] if row.get("variant") == "customvoice" else [])
        result.append({
            "key": f"audiocpp-{row['id']}", "name": f"{row['name']} {row['precision']}",
            "kind": ("soundfont" if row.get("task") == "instrument" else "music") if non_speech else "tts", "family": row["family"], "backend": "audio.cpp",
            "description": "Creative speech synthesis through audio.cpp.",
            "capabilities": [row["task"]] if non_speech else speech_capabilities(row),
            "import_required": not bool(row.get("remotePath")),
            "languages": [], "modelscope_repo": selection["modelscope_repo"],
            "runtime": {"family": "audio_cpp", "model_id": row["id"],
                        "files": {f"file_{i}": f["path"] for i, f in enumerate(files)}},
            "shared_files": files, "previous_shared_files": old_files, "voices": {v: {"language": "", "sid": i} for i, v in enumerate(voices or ["default"])},
        })
    return result
