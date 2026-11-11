#!/usr/bin/env python3
"""Verify the complete-file ASR contract against a running V-Voice service."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from urllib.parse import quote

import httpx


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True, help="Service root, for example http://10.0.0.1:22700")
    parser.add_argument("--model", default="sensevoice-int8")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--language", default="")
    parser.add_argument("--timeout", default=600.0, type=float)
    parser.add_argument("--expect-text", default="", help="Case-insensitive substring that must appear")
    parser.add_argument("--expect-empty", action="store_true", help="Require a complete empty transcript")
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    data = args.input.read_bytes()
    source_sha256 = hashlib.sha256(data).hexdigest()
    with httpx.Client(timeout=args.timeout, follow_redirects=False) as client:
        limits_response = client.get(
            f"{base}/api/v1/models/{quote(args.model, safe='')}/input-limits"
        )
        limits_response.raise_for_status()
        metadata = limits_response.json().get("full_transcription")
        if not isinstance(metadata, dict):
            raise RuntimeError("service does not publish full_transcription limits")
        if len(data) > int(metadata["max_upload_bytes"]):
            raise RuntimeError("input file exceeds the advertised full-file upload limit")

        response = client.post(
            f"{base}{metadata['endpoint']}",
            data={
                "model": args.model,
                "language": args.language,
                "response_format": "json",
            },
            files={
                "file": (
                    args.input.name,
                    data,
                    "application/octet-stream",
                )
            },
        )
        try:
            body = response.json()
        except ValueError:
            print(response.text, file=sys.stderr)
            raise RuntimeError(f"service returned HTTP {response.status_code} without JSON")
        if response.status_code != 200 or body.get("complete") is not True:
            print(json.dumps(body, ensure_ascii=False, indent=2), file=sys.stderr)
            raise RuntimeError(f"complete-file transcription failed with HTTP {response.status_code}")
        text = body.get("text")
        if not isinstance(text, str):
            raise RuntimeError("complete-file response has no text")
        if body.get("cache", {}).get("source_sha256") != source_sha256:
            raise RuntimeError("complete-file response does not identify the uploaded bytes")
        if args.expect_empty and text:
            raise RuntimeError("expected an empty transcript")
        if args.expect_text and args.expect_text.casefold() not in text.casefold():
            raise RuntimeError("expected transcript substring was not recognized")
        print(
            json.dumps(
                {
                    "status": "PASS",
                    "model": args.model,
                    "file": args.input.name,
                    "bytes": len(data),
                    "duration": body.get("duration"),
                    "parts": body.get("parts_total"),
                    "characters": len(text),
                    "cache_key": body.get("cache", {}).get("key"),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
