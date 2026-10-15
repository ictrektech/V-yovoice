#!/usr/bin/env python3
"""Run ASR eval models sequentially, unloading all models before each pass."""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

base_url = sys.argv[1].rstrip("/")
manifest_path = Path(sys.argv[2])
models = sys.argv[3].split(",")
out_path = Path(sys.argv[4])

ALL_MODELS = [
    "sensevoice-int8", "whisper-tiny", "qwen3-asr-0.6b", "qwen3-asr-1.7b",
    "paraformer-zh", "zipformer-en-streaming", "zipformer-zh-streaming", "zipformer-en",
]


def unload_all() -> None:
    for key in ALL_MODELS:
        request = urllib.request.Request(f"{base_url}/api/v1/models/{key}/unload", method="POST")
        try:
            urllib.request.urlopen(request, timeout=30)
        except Exception:
            pass


sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_asr_eval import evaluate, normalize  # noqa: E402

existing = json.loads(out_path.read_text(encoding="utf-8")) if out_path.is_file() else {}
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

for model in models:
    unload_all()
    result = evaluate(base_url, manifest, model)
    existing[model] = result
    print(f"{model}: CER={result['cer']} errors={result['errors']} empty={result['empty_hyps']}")
    out_path.write_text(json.dumps(existing, ensure_ascii=False, indent=1), encoding="utf-8")
