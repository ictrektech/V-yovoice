from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path

import numpy as np


MAX_SPEAKER_NAME_CHARS = 64
DEFAULT_IDENTIFY_THRESHOLD = 0.6


def cosine_similarity(left, right) -> float:
    left = np.asarray(left, dtype=np.float32).ravel()
    right = np.asarray(right, dtype=np.float32).ravel()
    norm_left = float(np.linalg.norm(left))
    norm_right = float(np.linalg.norm(right))
    if not norm_left or not norm_right or left.size != right.size:
        return 0.0
    return float(np.dot(left, right) / (norm_left * norm_right))


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def clean_speaker_name(name: str) -> str:
    value = " ".join(str(name).strip().split())
    if not value:
        raise ValueError("speaker name is required")
    if len(value) > MAX_SPEAKER_NAME_CHARS:
        raise ValueError(f"speaker name exceeds {MAX_SPEAKER_NAME_CHARS} characters")
    return value


class SpeakerStore:
    """Persisted enrolled speakers with their voiceprint embeddings.

    Enrollment audio is converted once into an embedding vector; the vectors are
    stored in ``<data_dir>/speakers.json`` so identification and verification
    only need cosine similarity against the saved voiceprints.
    """

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._file = self._root / "speakers.json"
        self._lock = threading.RLock()

    def _load(self) -> list[dict]:
        try:
            value = json.loads(self._file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        speakers = value.get("speakers") if isinstance(value, dict) else None
        return [item for item in speakers if isinstance(item, dict)] if isinstance(speakers, list) else []

    def _save(self, speakers: list[dict]) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"schema_version": 1, "speakers": speakers}, ensure_ascii=False, indent=2) + "\n"
        tmp = self._file.with_name("speakers.json.tmp")
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(self._file)

    @staticmethod
    def describe(item: dict) -> dict:
        return {
            "id": item["id"],
            "name": item["name"],
            "created_at": item["created_at"],
            "model": item.get("model", ""),
            "dimension": len(item["embedding"]),
        }

    def list_speakers(self) -> list[dict]:
        with self._lock:
            return [self.describe(item) for item in self._load()]

    def get(self, speaker_id: str) -> dict | None:
        with self._lock:
            item = next((row for row in self._load() if row["id"] == speaker_id), None)
        return dict(item) if item else None

    def find(self, reference: str) -> dict | None:
        """Look up an enrolled speaker by id or exact name."""
        with self._lock:
            rows = self._load()
        for row in rows:
            if row["id"] == reference or row["name"] == reference:
                return dict(row)
        return None

    def create(self, name: str, embedding: np.ndarray, model: str = "") -> dict:
        name = clean_speaker_name(name)
        vector = np.asarray(embedding, dtype=np.float32).ravel()
        if not vector.size:
            raise ValueError("speaker embedding is empty")
        with self._lock:
            speakers = self._load()
            item = {
                "id": f"sp_{uuid.uuid4().hex[:8]}",
                "name": name,
                "model": model,
                "embedding": [round(float(value), 6) for value in vector],
                "created_at": _now(),
            }
            speakers.append(item)
            self._save(speakers)
        return self.describe(item)

    def delete(self, speaker_id: str) -> bool:
        with self._lock:
            speakers = self._load()
            remaining = [row for row in speakers if row["id"] != speaker_id]
            if len(remaining) == len(speakers):
                return False
            self._save(remaining)
        return True

    def rank(self, embedding, limit: int | None = None) -> list[dict]:
        """Rank enrolled speakers against an embedding by cosine similarity.

        Speakers enrolled with an incompatible embedding dimension are skipped.
        """
        vector = np.asarray(embedding, dtype=np.float32).ravel()
        with self._lock:
            rows = self._load()
        scored = [
            {"id": row["id"], "name": row["name"], "score": round(cosine_similarity(vector, row["embedding"]), 6)}
            for row in rows
            if len(row.get("embedding") or []) == vector.size
        ]
        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:limit] if limit else scored
