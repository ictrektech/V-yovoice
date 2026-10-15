from __future__ import annotations

import json
import re
import shutil
import threading
import time
import uuid
from pathlib import Path


MAX_HOTWORDS = 64
MAX_HOTWORDS_BYTES = 4096
MAX_HOTWORDS_FILE_BYTES = 64 * 1024
MAX_HOTWORD_SET_NAME_CHARS = 64

# Derived per-model hotword table formats materialized for every saved set.
HOTWORD_SET_FORMATS = ("text", "qwen3", "zipformer")


def parse_hotwords(inline: str = "", file_data: bytes | None = None) -> list[str]:
    if file_data is not None and len(file_data) > MAX_HOTWORDS_FILE_BYTES:
        raise ValueError(f"hotwords_file exceeds {MAX_HOTWORDS_FILE_BYTES} bytes")
    try:
        file_text = file_data.decode("utf-8-sig") if file_data else ""
    except UnicodeDecodeError as exc:
        raise ValueError("hotwords_file must be UTF-8 text") from exc

    phrases: list[str] = []
    seen: set[str] = set()
    for value in (inline, file_text):
        for phrase in re.split(r"[,\r\n]+", value):
            phrase = " ".join(phrase.strip().split())
            if phrase and phrase not in seen:
                phrases.append(phrase)
                seen.add(phrase)

    if len(phrases) > MAX_HOTWORDS:
        raise ValueError(f"at most {MAX_HOTWORDS} hotwords are allowed")
    if sum(len(phrase.encode("utf-8")) for phrase in phrases) > MAX_HOTWORDS_BYTES:
        raise ValueError(f"hotwords exceed {MAX_HOTWORDS_BYTES} UTF-8 bytes")
    return phrases


def clean_phrases(phrases: list[str]) -> list[str]:
    """Normalize already-parsed phrases (for example from a saved set) without
    splitting on commas, then enforce the shared hotword limits."""
    cleaned: list[str] = []
    seen: set[str] = set()
    for phrase in phrases:
        value = " ".join(str(phrase).strip().split())
        if value and value not in seen:
            cleaned.append(value)
            seen.add(value)
    if not cleaned:
        raise ValueError("hotword set requires at least one phrase")
    if len(cleaned) > MAX_HOTWORDS:
        raise ValueError(f"at most {MAX_HOTWORDS} hotwords are allowed")
    if sum(len(phrase.encode("utf-8")) for phrase in cleaned) > MAX_HOTWORDS_BYTES:
        raise ValueError(f"hotwords exceed {MAX_HOTWORDS_BYTES} UTF-8 bytes")
    return cleaned


def merge_phrases(*groups: list[str]) -> list[str]:
    """Merge saved-set and request-level phrases, deduplicated, limits enforced."""
    merged: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for phrase in group:
            if phrase and phrase not in seen:
                merged.append(phrase)
                seen.add(phrase)
    if len(merged) > MAX_HOTWORDS:
        raise ValueError(f"at most {MAX_HOTWORDS} hotwords are allowed")
    if sum(len(phrase.encode("utf-8")) for phrase in merged) > MAX_HOTWORDS_BYTES:
        raise ValueError(f"hotwords exceed {MAX_HOTWORDS_BYTES} UTF-8 bytes")
    return merged


def clean_hotword_set_name(name: str) -> str:
    value = " ".join(str(name).strip().split())
    if not value:
        raise ValueError("hotword set name is required")
    if len(value) > MAX_HOTWORD_SET_NAME_CHARS:
        raise ValueError(f"hotword set name exceeds {MAX_HOTWORD_SET_NAME_CHARS} characters")
    return value


def render_hotword_format(phrases: list[str], fmt: str) -> str:
    """Render phrases in the hotword table format expected by a model family."""
    if fmt == "qwen3":
        return ",".join(phrases) + "\n"
    if fmt == "zipformer":
        return "\n".join(phrases) + "\n"
    if fmt == "text":
        return "\n".join(phrases) + "\n"
    raise ValueError(f"unsupported hotword format: {fmt}")


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class HotwordStore:
    """Persistent named hotword sets with derived per-model format artifacts.

    Sets live in ``<data_dir>/hotwords.json``; saving or updating a set
    materializes the model-side hotword tables under
    ``<data_dir>/hotwords-artifacts/<id>/`` so hotword-enabled models can read
    the exact table format they expect without any client-side conversion.
    """

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._file = self._root / "hotwords.json"
        self._artifacts = self._root / "hotwords-artifacts"
        self._lock = threading.RLock()

    def _load(self) -> list[dict]:
        try:
            value = json.loads(self._file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        sets = value.get("sets") if isinstance(value, dict) else None
        return [item for item in sets if isinstance(item, dict)] if isinstance(sets, list) else []

    def _save(self, sets: list[dict]) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"schema_version": 1, "sets": sets}, ensure_ascii=False, indent=2) + "\n"
        tmp = self._file.with_name("hotwords.json.tmp")
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(self._file)

    def _materialize(self, item: dict) -> None:
        folder = self._artifacts / item["id"]
        folder.mkdir(parents=True, exist_ok=True)
        for fmt in HOTWORD_SET_FORMATS:
            (folder / f"{fmt}.txt").write_text(render_hotword_format(item["phrases"], fmt), encoding="utf-8")

    @staticmethod
    def describe(item: dict) -> dict:
        return {
            "id": item["id"],
            "name": item["name"],
            "phrases": item["phrases"],
            "phrase_count": len(item["phrases"]),
            "created_at": item["created_at"],
            "updated_at": item["updated_at"],
            "formats": [
                {"format": fmt, "file": f"{fmt}.txt", "bytes": len(render_hotword_format(item["phrases"], fmt).encode("utf-8"))}
                for fmt in HOTWORD_SET_FORMATS
            ],
        }

    def list_sets(self) -> list[dict]:
        with self._lock:
            return [self.describe(item) for item in self._load()]

    def get(self, set_id: str) -> dict | None:
        with self._lock:
            item = next((row for row in self._load() if row["id"] == set_id), None)
        return dict(item) if item else None

    def create(self, name: str, phrases: list[str]) -> dict:
        name = clean_hotword_set_name(name)
        cleaned = clean_phrases(phrases)
        with self._lock:
            sets = self._load()
            item = {
                "id": f"hw_{uuid.uuid4().hex[:8]}",
                "name": name,
                "phrases": cleaned,
                "created_at": _now(),
                "updated_at": _now(),
            }
            sets.append(item)
            self._save(sets)
            self._materialize(item)
        return self.describe(item)

    def update(self, set_id: str, name: str | None = None, phrases: list[str] | None = None) -> dict | None:
        with self._lock:
            sets = self._load()
            item = next((row for row in sets if row["id"] == set_id), None)
            if item is None:
                return None
            if name is not None:
                item["name"] = clean_hotword_set_name(name)
            if phrases is not None:
                item["phrases"] = clean_phrases(phrases)
            item["updated_at"] = _now()
            self._save(sets)
            self._materialize(item)
        return self.describe(item)

    def delete(self, set_id: str) -> bool:
        with self._lock:
            sets = self._load()
            remaining = [row for row in sets if row["id"] != set_id]
            if len(remaining) == len(sets):
                return False
            self._save(remaining)
            shutil.rmtree(self._artifacts / set_id, ignore_errors=True)
        return True
