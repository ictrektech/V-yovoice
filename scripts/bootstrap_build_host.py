#!/usr/bin/env python3
"""在专用 Linux 构建机准备 Node 和 Go，不修改系统目录。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
NODE_MINIMUM = (22, 0, 0)
NODE_MANIFESTS = (
    "https://nodejs.org/dist/latest-v22.x/SHASUMS256.txt",
    "https://npmmirror.com/mirrors/node/latest-v22.x/SHASUMS256.txt",
)
GO_MANIFESTS = (
    "https://go.dev/dl/?mode=json&include=all",
    "https://golang.google.cn/dl/?mode=json&include=all",
)
GO_DOWNLOADS = (
    "https://dl.google.com/go/",
    "https://golang.google.cn/dl/",
    "https://mirrors.aliyun.com/golang/",
)


class BootstrapError(RuntimeError):
    pass


def version_tuple(value: str) -> tuple[int, ...]:
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", value)
    if not match:
        raise BootstrapError(f"cannot parse version: {value}")
    return tuple(map(int, match.groups()))


def required_go_version() -> str:
    text = (ROOT / "go.mod").read_text(encoding="utf-8")
    match = re.search(r"^go\s+(\d+\.\d+\.\d+)\s*$", text, re.MULTILINE)
    if not match:
        raise BootstrapError("go.mod does not declare a full Go version")
    return match.group(1)


def command_output(command: list[str]) -> str:
    try:
        result = subprocess.run(command, check=False, text=True, capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def detect(binary: str, toolchain_root: Path) -> tuple[Path | None, str]:
    candidate = toolchain_root / binary / "current" / "bin" / binary
    if candidate.is_file():
        output = command_output([str(candidate), "--version" if binary == "node" else "version"])
        if output:
            return candidate, output
    return None, ""


def node_ok(output: str) -> bool:
    try:
        return version_tuple(output) >= NODE_MINIMUM
    except BootstrapError:
        return False


def go_ok(output: str, required: str) -> bool:
    try:
        return version_tuple(output) >= version_tuple(required)
    except BootstrapError:
        return False


def fetch_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": "V-Voice build bootstrap"})
    with urlopen(request, timeout=60) as response:
        return response.read().decode("utf-8")


def download(url: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(path.suffix + ".part")
    with urlopen(
        Request(url, headers={"User-Agent": "V-Voice build bootstrap"}),
        timeout=120,
    ) as response, part.open("wb") as handle:
        shutil.copyfileobj(response, handle)
    part.replace(path)


def verify_sha256(path: Path, expected: str) -> None:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected:
        path.unlink(missing_ok=True)
        raise BootstrapError(f"checksum mismatch for {path.name}")


def safe_extract(archive: Path, destination: Path) -> None:
    with tarfile.open(archive, "r:gz") as value:
        for member in value.getmembers():
            target = (destination / member.name).resolve()
            if destination.resolve() not in target.parents and target != destination.resolve():
                raise BootstrapError(f"unsafe archive member: {member.name}")
        value.extractall(destination)


def node_archive() -> tuple[str, str, str]:
    arch = {"x86_64": "x64", "aarch64": "arm64", "arm64": "arm64"}.get(platform.machine())
    if arch is None:
        raise BootstrapError(f"unsupported Node architecture: {platform.machine()}")
    pattern = re.compile(
        rf"^([0-9a-f]{{64}})\s+(node-v(22\.\d+\.\d+)-linux-{arch}\.tar\.gz)$",
        re.MULTILINE,
    )
    errors = []
    for manifest in NODE_MANIFESTS:
        try:
            match = pattern.search(fetch_text(manifest))
            if match:
                return match.group(1), match.group(2), manifest.rsplit("/", 1)[0] + "/"
            errors.append(f"{manifest}: Node 22 {arch} archive not found")
        except OSError as exc:
            errors.append(f"{manifest}: {exc}")
    raise BootstrapError("; ".join(errors))


def install_node(toolchain_root: Path) -> Path:
    checksum, filename, base = node_archive()
    downloads = toolchain_root / ".downloads"
    archive = downloads / filename
    if not archive.is_file():
        download(base + filename, archive)
    verify_sha256(archive, checksum)
    with tempfile.TemporaryDirectory(dir=toolchain_root) as directory:
        staging = Path(directory)
        safe_extract(archive, staging)
        extracted = staging / filename.removesuffix(".tar.gz")
        label = re.search(r"node-(v22\.\d+\.\d+)-", filename)
        if not extracted.is_dir() or label is None:
            raise BootstrapError("Node archive has an unexpected layout")
        target = toolchain_root / f"node-{label.group(1)}"
        if target.exists():
            shutil.rmtree(target)
        extracted.replace(target)
    current = toolchain_root / "node" / "current"
    current.parent.mkdir(parents=True, exist_ok=True)
    if current.exists() or current.is_symlink():
        current.unlink()
    current.symlink_to(target, target_is_directory=True)
    return current / "bin" / "node"


def go_archive(version: str) -> tuple[str, str]:
    arch = {"x86_64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(platform.machine())
    if arch is None:
        raise BootstrapError(f"unsupported Go architecture: {platform.machine()}")
    errors = []
    for manifest in GO_MANIFESTS:
        try:
            releases = json.loads(fetch_text(manifest))
            release = next((item for item in releases if item.get("version") == f"go{version}"), None)
            file = next((
                item for item in (release or {}).get("files", [])
                if item.get("os") == "linux" and item.get("arch") == arch and item.get("kind") == "archive"
            ), None)
            if file and file.get("sha256") and file.get("filename"):
                return file["sha256"], file["filename"]
            errors.append(f"{manifest}: Go {version} linux/{arch} archive not found")
        except (OSError, ValueError) as exc:
            errors.append(f"{manifest}: {exc}")
    raise BootstrapError("; ".join(errors))


def install_go(toolchain_root: Path, version: str) -> Path:
    checksum, filename = go_archive(version)
    downloads = toolchain_root / ".downloads"
    archive = downloads / filename
    if not archive.is_file():
        errors = []
        for base in GO_DOWNLOADS:
            try:
                download(base + filename, archive)
                break
            except OSError as exc:
                errors.append(f"{base}: {exc}")
        else:
            raise BootstrapError("; ".join(errors))
    verify_sha256(archive, checksum)
    with tempfile.TemporaryDirectory(dir=toolchain_root) as directory:
        staging = Path(directory)
        safe_extract(archive, staging)
        extracted = staging / "go"
        if not extracted.is_dir():
            raise BootstrapError("Go archive has an unexpected layout")
        target = toolchain_root / f"go-{version}"
        if target.exists():
            shutil.rmtree(target)
        extracted.replace(target)
    current = toolchain_root / "go" / "current"
    current.parent.mkdir(parents=True, exist_ok=True)
    if current.exists() or current.is_symlink():
        current.unlink()
    current.symlink_to(target, target_is_directory=True)
    return current / "bin" / "go"


def env_content(toolchain_root: Path) -> str:
    paths = [
        toolchain_root / "node" / "current" / "bin",
        toolchain_root / "go" / "current" / "bin",
    ]
    joined = ":".join(str(path) for path in paths)
    return (
        "# Generated by scripts/bootstrap_build_host.py\n"
        f'export PATH="{joined}:$PATH"\n'
        "export GOTOOLCHAIN=local\n"
    )


def write_env(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{os.getpid()}.pending")
    temporary.write_text(content, encoding="utf-8")
    os.chmod(temporary, 0o644)
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="only inspect installed versions")
    parser.add_argument("--dry-run", action="store_true", help="print actions without downloading")
    parser.add_argument("--toolchain-root", type=Path, default=Path.home() / "dev/toolchains")
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path.home() / "dev/build/v-yovoice/toolchain.env",
    )
    args = parser.parse_args()
    if args.check and args.dry_run:
        parser.error("--check and --dry-run are mutually exclusive")
    if platform.system() != "Linux":
        raise BootstrapError("build host bootstrap requires Linux")

    required_go = required_go_version()
    args.toolchain_root = args.toolchain_root.expanduser().resolve()
    args.env_file = args.env_file.expanduser().resolve()
    node_path, node_output = detect("node", args.toolchain_root)
    go_path, go_output = detect("go", args.toolchain_root)
    need_node = not node_ok(node_output)
    need_go = not go_ok(go_output, required_go)
    status = {
        "node": node_output or "missing",
        "node_ok": not need_node,
        "go": go_output or "missing",
        "go_ok": not need_go,
        "required_go": required_go,
        "env_file": str(args.env_file),
    }
    print(json.dumps(status, ensure_ascii=False, sort_keys=True))
    if args.check:
        return 0 if not need_node and not need_go else 1
    if args.dry_run:
        print(f"Would install Node 22: {need_node}")
        print(f"Would install Go {required_go}: {need_go}")
        print(f"Would write {args.env_file}")
        return 0

    args.toolchain_root.mkdir(parents=True, exist_ok=True)
    if need_node:
        node_path = install_node(args.toolchain_root)
    if need_go:
        go_path = install_go(args.toolchain_root, required_go)
    write_env(args.env_file, env_content(args.toolchain_root))
    if node_path is None or go_path is None:
        raise BootstrapError("toolchain did not resolve after installation")
    actual_node = command_output([str(node_path), "--version"])
    actual_go = command_output([str(go_path), "version"])
    if not node_ok(actual_node) or not go_ok(actual_go, required_go):
        raise BootstrapError(f"installed toolchain failed verification: node={actual_node!r} go={actual_go!r}")
    print(f"PASS: node={actual_node} go={actual_go} env={args.env_file}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (BootstrapError, OSError, tarfile.TarError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
