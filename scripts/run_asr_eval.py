#!/usr/bin/env python3
"""Run an ASR eval manifest against a V-Voice endpoint and print a CER table."""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.request
from pathlib import Path


def normalize(text: str) -> str:
    text = re.sub(r"[^\w\u4e00-\u9fff]+", "", text, flags=re.UNICODE)
    return text.lower()


def normalize_words(text: str) -> list[str]:
    text = re.sub(r"[^\w\s'-]+", "", text.lower(), flags=re.UNICODE)
    return text.split()


def is_english(manifest: list[dict]) -> bool:
    sample = "".join(item["ref"] for item in manifest[:10])
    cjk = len(re.findall(r"[\u4e00-\u9fff]", sample))
    return cjk < len(sample) * 0.1


def error_rate(ref: str, hyp: str) -> tuple[float, int] | None:
    """CER for Chinese, WER for English; returns (rate, distance) or None on error."""
    if is_english_ref:
        ref_tokens, hyp_tokens = normalize_words(ref), normalize_words(hyp)
        denominator = max(1, len(ref_tokens))
    else:
        ref_tokens, hyp_tokens = normalize(ref), normalize(hyp)
        denominator = max(1, len(ref_tokens))
    distance = levenshtein(ref_tokens, hyp_tokens)
    return round(distance / denominator, 4), distance


is_english_ref = False


def levenshtein(a: str, b: str) -> int:
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def transcribe(base_url: str, wav_path: str, clip_id: str, model: str) -> str:
    boundary_token = "----vvoiceeval"
    with open(wav_path, "rb") as handle:
        body = (
            f"--{boundary_token}\r\nContent-Disposition: form-data; name=\"model\"\r\n\r\n{model}\r\n"
            f"--{boundary_token}\r\nContent-Disposition: form-data; name=\"response_format\"\r\n\r\njson\r\n"
            f"--{boundary_token}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{clip_id}.wav\"\r\n"
            f"Content-Type: audio/wav\r\n\r\n"
        ).encode() + handle.read() + f"\r\n--{boundary_token}--\r\n".encode()
    request = urllib.request.Request(
        f"{base_url}/v1/audio/transcriptions",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary_token}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            return json.load(response).get("text", "")
    except Exception as exc:
        return f"<ERROR {exc}>"


def evaluate(base_url: str, manifest: list[dict], model: str, metric: str = "cer") -> dict:
    global is_english_ref
    is_english_ref = metric == "wer"
    rows = []
    started = time.time()
    for item in manifest:
        hyp = transcribe(base_url, item["wav"], item["id"], model)
        scored = None if hyp.startswith("<ERROR") else error_rate(item["ref"], hyp)
        rows.append({
            "id": item["id"], "ref": item["ref"], "hyp": hyp,
            "cer": None if scored is None else scored[0],
        })
    valid = [r["cer"] for r in rows if r["cer"] is not None]
    return {
        "rows": rows,
        "metric": "wer" if metric == "wer" else "cer",
        "cer": round(sum(valid) / len(valid), 4) if valid else None,
        "errors": sum(1 for r in rows if r["cer"] is None),
        "empty_hyps": sum(1 for r in rows if not r["hyp"].strip()),
        "seconds": round(time.time() - started, 1),
    }


def main() -> None:
    base_url = sys.argv[1].rstrip("/")
    manifest_path = Path(sys.argv[2])
    models = sys.argv[3].split(",")
    out_path = Path(sys.argv[4]) if len(sys.argv) > 4 else Path("eval-results.json")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    metric = "wer" if is_english(manifest) else "cer"
    print(f"metric: {metric} ({len(manifest)} utterances)")
    results = {}
    for model in models:
        results[model] = evaluate(base_url, manifest, model, metric)
        label = "WER" if metric == "wer" else "CER"
        print(f"{model}: {label}={results[model]['cer']} errors={results[model]['errors']} time={results[model]['seconds']:.0f}s")
        out_path.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
