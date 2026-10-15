#!/usr/bin/env python3
"""Benchmark V-Voice ASR/TTS/speaker paths, direct vs via V-Router.

Usage:
  python3 bench_voice_router.py <base-url> <clips-dir> <out.json> [concurrency...]
Measures, per path: latency percentiles (p50/p95), throughput, error count.
"""
from __future__ import annotations

import json
import statistics
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

base_url = sys.argv[1].rstrip("/")
clips_dir = Path(sys.argv[2])
out_path = Path(sys.argv[3])
concurrency_levels = [int(v) for v in sys.argv[4:]] or [1, 2, 4]

CLIP = str(clips_dir / "utt_000.wav")
TTS_TEXT = "这是一段用于性能测试的文本，长度适中。"


def post_multipart(path: str, fields: dict[str, str], file_field: str, file_path: str, timeout: int = 300) -> tuple[float, int, bytes]:
    boundary = "----vvoicebench"
    parts = []
    for name, value in fields.items():
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode()
        )
    with open(file_path, "rb") as handle:
        payload = handle.read()
    parts.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"{file_field}\"; filename=\"clip.wav\"\r\n"
        f"Content-Type: audio/wav\r\n\r\n".encode() + payload + f"\r\n--{boundary}--\r\n".encode()
    )
    body = b"".join(parts)
    request = urllib.request.Request(
        base_url + path,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read()
            return time.perf_counter() - started, response.status, data
    except urllib.error.HTTPError as exc:
        exc.read()
        return time.perf_counter() - started, exc.code, b""
    except Exception:
        return time.perf_counter() - started, 0, b""


def post_json(path: str, payload: dict, timeout: int = 300) -> tuple[float, int, bytes]:
    request = urllib.request.Request(
        base_url + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return time.perf_counter() - started, response.status, response.read()
    except urllib.error.HTTPError as exc:
        exc.read()
        return time.perf_counter() - started, exc.code, b""
    except Exception:
        return time.perf_counter() - started, 0, b""


def summarize(label: str, latencies: list[float], errors: int, total_seconds: float) -> dict:
    if not latencies:
        return {"label": label, "errors": errors, "count": 0}
    ordered = sorted(latencies)
    return {
        "label": label,
        "count": len(ordered),
        "errors": errors,
        "p50_s": round(ordered[len(ordered) // 2], 3),
        "p95_s": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))], 3),
        "max_s": round(ordered[-1], 3),
        "throughput_rps": round(len(ordered) / total_seconds, 2),
    }


def run_case(label: str, concurrency: int, requests_per_worker: int, fn) -> dict:
    latencies: list[float] = []
    errors = 0

    def worker() -> None:
        nonlocal errors
        for _ in range(requests_per_worker):
            elapsed, status, _ = fn()
            if status != 200:
                errors += 1
            latencies.append(elapsed)

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        list(pool.map(lambda _: worker(), range(concurrency)))
    wall = time.perf_counter() - started
    summary = summarize(label, latencies, errors, wall)
    summary["concurrency"] = concurrency
    return summary


def bench_asr() -> tuple[float, int, bytes]:
    return post_multipart(
        "/v1/audio/transcriptions",
        {"model": "sensevoice-int8", "response_format": "json"},
        "file", CLIP,
    )


def bench_tts() -> tuple[float, int, bytes]:
    return post_json(
        "/v1/audio/speech",
        {"model": "kokoro-multilang", "voice": "zf_xiaoxiao", "input": TTS_TEXT, "response_format": "wav"},
    )


def bench_speaker() -> tuple[float, int, bytes]:
    return post_multipart(
        "/v1/audio/speakers/identify",
        {"model": "speaker-campplus-zh-en", "threshold": "0.6"},
        "file", CLIP,
    )


results: dict = {"base_url": base_url, "cases": []}
# 预热各路径
bench_asr()
bench_tts()
bench_speaker()

for label, fn in [("asr-sensevoice-13s", bench_asr), ("tts-kokoro-short", bench_tts), ("speaker-identify-13s", bench_speaker)]:
    for concurrency in concurrency_levels:
        case = run_case(label, concurrency, 4, fn)
        results["cases"].append(case)
        print(json.dumps(case, ensure_ascii=False))

out_path.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
