"""节点计算后端支持的模型、文件和任务类型。"""

from functools import lru_cache
from pathlib import PurePosixPath

from .creative import models as creative_catalog

TRANSCRIBE = "voice.transcribe"
SYNTHESIZE = "voice.synthesize"
EMBED = "voice.speaker_embedding"
WORKBENCH = "voice.workbench"

SENSEVOICE = "sensevoice-int8"
SENSEVOICE_FILES = {"model": "model.int8.onnx", "tokens": "tokens.txt"}
SENSEVOICE_LIMITS = {"input_bytes": 2 << 20, "sample_rate": 48000, "duration_seconds": 20}
CHINESE_RULES = {"fst-phone": "phone.fst", "fst-date": "date.fst", "fst-number": "number.fst"}

MODELS = {
    SENSEVOICE: (TRANSCRIBE, SENSEVOICE_FILES, SENSEVOICE_LIMITS),
    "vits-zh": (SYNTHESIZE, {"model": "model.onnx", "tokens": "tokens.txt", "lexicon": "lexicon.txt", **CHINESE_RULES},
                {"text_characters": 500}),
    "matcha-zh": (SYNTHESIZE, {"acoustic_model": "model-steps-3.onnx", "vocoder": "vocos-22khz-univ.onnx",
                              "tokens": "tokens.txt", "lexicon": "lexicon.txt", **CHINESE_RULES},
                  {"text_characters": 500}),
    "speaker-campplus-zh-en": (EMBED, {"model": "3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx"},
                            SENSEVOICE_LIMITS),
}

MAX_OUTPUT_BYTES = 20 << 20
WORKBENCH_BUNDLE_LIMIT = 500 << 20


@lru_cache(maxsize=1)
def workbench_models():
    return {item["key"]: item for item in creative_catalog(include_non_speech=True)}


def model_spec(model_id: str):
    if model_id in MODELS:
        return MODELS[model_id]
    item = workbench_models()[model_id]
    files = {role: PurePosixPath(path).name for role, path in item["runtime"]["files"].items()}
    return WORKBENCH, files, {"bundle_bytes": WORKBENCH_BUNDLE_LIMIT}


def model_ids():
    return (*MODELS, *workbench_models())
