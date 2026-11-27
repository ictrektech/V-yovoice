"""V-Scheduler 私有通道的权重接收与校验。"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

CHUNK_BYTES = 1 << 20
MANIFEST_BYTES = 64 << 10
IDENTIFIER = r"^[a-z0-9][a-z0-9_.-]{0,95}$"
DIGEST = r"^[a-f0-9]{64}$"


class WeightFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_id: str = Field(pattern=IDENTIFIER)
    path: str = Field(min_length=1, max_length=200)
    size_bytes: int = Field(strict=True, gt=0, le=1 << 40)
    sha256: str = Field(pattern=DIGEST)
    shared_path: str | None = Field(default=None, max_length=1024)


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: str = Field(pattern=IDENTIFIER)
    source: Literal["copy", "shared"] = "copy"
    files: list[WeightFile] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def validate_paths(self):
        if len({row.file_id for row in self.files}) != len(self.files):
            raise ValueError("重复的文件 ID")
        for row in self.files:
            if not safe_path(row.path) or "/" in row.path or row.path.startswith("."):
                raise ValueError("无效的文件名")
            if self.source == "shared":
                if not row.shared_path or not safe_path(row.shared_path) or row.shared_path.split("/")[-1] != row.path:
                    raise ValueError("无效的共享文件路径")
            elif row.shared_path is not None:
                raise ValueError("复制传输不接受共享路径")
        return self


def safe_path(value: str) -> bool:
    return not any(part in ("", ".", "..") for part in value.split("/")) and "\\" not in value and all(
        ord(char) >= 32 and ord(char) != 127 for char in value
    )


def write_json(path: Path, value: dict) -> None:
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(value, stream, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


class WeightStore:
    def __init__(self, root: Path, shared: Path):
        self.root = root
        self.shared = shared
        self.lock = RLock()

    def shared_available(self) -> bool:
        return os.path.ismount(self.shared) and (self.shared / "export").is_dir()

    @contextmanager
    def transfer(self, transfer_id: str):
        if not re.fullmatch(DIGEST, transfer_id):
            raise HTTPException(404, "WEIGHT_TRANSFER_NOT_FOUND")
        with self.lock:
            directory = self.root / transfer_id
            manifest_path = directory / "manifest.json"
            if not manifest_path.is_file():
                raise HTTPException(404, "WEIGHT_TRANSFER_NOT_FOUND")
            yield directory, Manifest.model_validate_json(manifest_path.read_bytes())

    def begin(self, manifest: Manifest) -> dict:
        if manifest.source == "shared" and not self.shared_available():
            raise HTTPException(409, "WEIGHT_SHARED_UNAVAILABLE")
        manifest.files.sort(key=lambda row: row.file_id)
        transfer_id = hashlib.sha256(manifest.model_dump_json().encode()).hexdigest()
        with self.lock:
            directory = self.root / transfer_id
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            path = directory / "manifest.json"
            if not path.exists():
                write_json(path, manifest.model_dump())
            return self.receipt(directory, manifest)

    def path(self, directory: Path, row: WeightFile) -> Path:
        if not row.shared_path:
            return directory / "files" / row.file_id / row.path
        root = self.shared.resolve()
        path = (root / row.shared_path).resolve()
        if not self.shared_available() or not path.is_relative_to(root):
            raise HTTPException(409, "WEIGHT_SHARED_UNAVAILABLE")
        return path

    def receipt(self, directory: Path, manifest: Manifest) -> dict:
        verified_path = directory / "verified.json"
        fingerprints = json.loads(verified_path.read_bytes()) if verified_path.is_file() else {}
        files = []
        verified = bool(fingerprints)
        for row in manifest.files:
            try:
                stat = self.path(directory, row).stat()
                received = stat.st_size
                verified = verified and fingerprints.get(row.file_id) == fingerprint(stat)
            except FileNotFoundError:
                received = 0
                verified = False
            files.append({"file_id": row.file_id, "received_bytes": received})
        return {"transfer_id": directory.name, "model_id": manifest.model_id, "source": manifest.source,
                "verified": verified, "files": files}

    def status(self, transfer_id: str) -> dict:
        with self.transfer(transfer_id) as (directory, manifest):
            return self.receipt(directory, manifest)

    def write(self, transfer_id: str, file_id: str, offset: int, content: bytes) -> dict:
        with self.transfer(transfer_id) as (directory, manifest):
            row = next((entry for entry in manifest.files if entry.file_id == file_id), None)
            if row is None:
                raise HTTPException(404, "WEIGHT_FILE_NOT_FOUND")
            if row.shared_path:
                raise HTTPException(409, "WEIGHT_SHARED_READ_ONLY")
            path = self.path(directory, row)
            received = path.stat().st_size if path.exists() else 0
            end = offset + len(content)
            if offset > received or end > row.size_bytes:
                raise HTTPException(409, "WEIGHT_OFFSET_MISMATCH")
            if offset < received:
                with path.open("rb") as stream:
                    stream.seek(offset)
                    if end > received or stream.read(len(content)) != content:
                        raise HTTPException(409, "WEIGHT_OFFSET_MISMATCH")
                return {"received_bytes": received}
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with path.open("ab") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            return {"received_bytes": end}

    def complete(self, transfer_id: str) -> dict:
        with self.transfer(transfer_id) as (directory, manifest):
            receipt = self.receipt(directory, manifest)
            if receipt["verified"]:
                return receipt
            fingerprints = {}
            for row in manifest.files:
                path = self.path(directory, row)
                try:
                    before = path.stat()
                    if before.st_size != row.size_bytes:
                        raise HTTPException(409, "WEIGHT_SIZE_MISMATCH")
                    with path.open("rb") as stream:
                        digest = hashlib.sha256()
                        for chunk in iter(lambda: stream.read(CHUNK_BYTES), b""):
                            digest.update(chunk)
                    if digest.hexdigest() != row.sha256 or fingerprint(before) != fingerprint(path.stat()):
                        raise HTTPException(409, "WEIGHT_CHECKSUM_MISMATCH")
                except FileNotFoundError:
                    raise HTTPException(409, "WEIGHT_FILE_INCOMPLETE") from None
                fingerprints[row.file_id] = fingerprint(before)
            write_json(directory / "verified.json", fingerprints)
            return self.receipt(directory, manifest)

    def verified_files(self, transfer_id: str, model_id: str) -> dict[str, Path]:
        with self.transfer(transfer_id) as (directory, manifest):
            if manifest.model_id != model_id or not self.receipt(directory, manifest)["verified"]:
                raise HTTPException(409, "WORKER_WEIGHTS_NOT_READY")
            return {row.file_id: self.path(directory, row) for row in manifest.files}

    def ready_transfer(self, model_id: str) -> str | None:
        with self.lock:
            for path in self.root.glob("*/verified.json"):
                try:
                    receipt = self.status(path.parent.name)
                    if receipt["model_id"] == model_id and receipt["verified"]:
                        return path.parent.name
                except HTTPException:
                    continue
        return None

    def ready(self, model_id: str) -> bool:
        return self.ready_transfer(model_id) is not None

    def delete(self, model_id: str) -> dict:
        count = 0
        with self.lock:
            for path in self.root.glob("*/manifest.json"):
                if Manifest.model_validate_json(path.read_bytes()).model_id == model_id:
                    shutil.rmtree(path.parent)
                    count += 1
        return {"deleted_transfers": count}


def fingerprint(stat: os.stat_result) -> list[int]:
    return [stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns]
