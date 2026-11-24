#!/usr/bin/env python3
"""把本机工作树安全同步到专用构建机源码目录。"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DESTINATION = "~/dev/repos/V-yovoice"
EXCLUDES = (
    "/.git/",
    "/.venv/",
    "venv/",
    "node_modules/",
    "dist/",
    "build/",
    "data/",
    "__pycache__/",
    ".pytest_cache/",
    ".ruff_cache/",
    ".mypy_cache/",
    ".cache/",
    ".env",
    "*.pyc",
    "*.log",
    ".DS_Store",
)
PROTECTED_COMPONENTS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    "data",
    ".env",
}


class SyncError(RuntimeError):
    pass


def run(command: list[str], *, input_text: str | None = None, timeout: int = 30) -> subprocess.CompletedProcess:
    result = subprocess.run(
        command,
        check=False,
        input=input_text,
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise SyncError(detail or f"command exited {result.returncode}: {shlex.join(command)}")
    return result


def inspect_remote(host: str, destination: str) -> dict[str, str]:
    script = r"""
set -euo pipefail
dest="$1"
case "$dest" in
  "~/"*) dest="$HOME/${dest#~/}" ;;
esac
if [[ -L "$dest" ]]; then
  echo "destination is a symlink" >&2
  exit 2
fi
if [[ ! -d "$dest" ]]; then
  echo "destination does not exist: $dest" >&2
  exit 3
fi
resolved="$(readlink -f "$dest")"
parent_owner="$(stat -c %U "$(dirname "$resolved")")"
printf '%s\n%s\n%s\n%s\n%s\n' \
  "$HOME" "$resolved" "$(id -un)" "$(stat -c %U "$resolved")" "$parent_owner"
"""
    result = run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", host, "bash", "-s", "--", destination],
        input_text=script,
    )
    lines = result.stdout.splitlines()
    if len(lines) != 5:
        raise SyncError(f"unexpected remote inspection output: {result.stdout.strip()[:300]}")
    home, resolved, user, owner, parent_owner = lines
    return {
        "home": home,
        "resolved": resolved,
        "user": user,
        "owner": owner,
        "parent_owner": parent_owner,
    }


def validate_remote(info: dict[str, str]) -> None:
    expected = f"{info['home']}/dev/repos/V-yovoice"
    if info["resolved"] != expected:
        raise SyncError(f"destination must resolve to {expected}, got {info['resolved']}")
    if info["owner"] != info["user"] or info["parent_owner"] != info["user"]:
        raise SyncError(
            f"destination must be owned by {info['user']}, "
            f"got directory={info['owner']} parent={info['parent_owner']}"
        )


def rsync_command(source: Path, host: str, destination: str, *, dry_run: bool) -> list[str]:
    command = ["rsync", "-a", "--delete", "--itemize-changes", "--human-readable"]
    if dry_run:
        command.append("--dry-run")
    for pattern in EXCLUDES:
        command.append(f"--exclude={pattern}")
    command.extend([f"{source}/", f"{host}:{destination}/"])
    return command


def protected_path(path: str) -> bool:
    return any(part in PROTECTED_COMPONENTS for part in Path(path).parts)


def check_dry_run(output: str) -> list[str]:
    deletions = []
    for line in output.splitlines():
        if not line.startswith("*deleting "):
            continue
        path = line.removeprefix("*deleting ").strip()
        if protected_path(path):
            raise SyncError(f"refusing protected deletion: {path}")
        deletions.append(path)
    return deletions


def print_summary(output: str, deletions: list[str]) -> None:
    changes = [line for line in output.splitlines() if line and not line.startswith(("sending ", "sent ", "total size"))]
    print(f"Pending changes: {len(changes)}; deletions: {len(deletions)}")
    for line in changes[:40]:
        print(line)
    if len(changes) > 40:
        print(f"... {len(changes) - 40} more changes")


def bootstrap(host: str, destination: str) -> None:
    script = r"""
set -euo pipefail
cd "$1"
python3 scripts/bootstrap_build_host.py
"""
    result = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", host, "bash", "-s", "--", destination],
        check=False,
        input=script,
        text=True,
        timeout=1800,
    )
    if result.returncode:
        raise SyncError(f"bootstrap failed with exit code {result.returncode}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True, help="SSH destination, for example czy@10.144.144.232")
    parser.add_argument("--source", type=Path, default=ROOT)
    parser.add_argument("--destination", default=DEFAULT_DESTINATION)
    parser.add_argument("--apply", action="store_true", help="apply after the safety dry-run")
    parser.add_argument("--bootstrap", action="store_true", help="bootstrap Node/Go after applying")
    args = parser.parse_args()
    if args.bootstrap and not args.apply:
        parser.error("--bootstrap requires --apply")

    source = args.source.resolve()
    for required in ("go.mod", "web/package.json", "docker/build_image.sh"):
        if not (source / required).is_file():
            raise SystemExit(f"source is not a V-yovoice checkout: missing {required}")

    info = inspect_remote(args.host, args.destination)
    validate_remote(info)
    print(
        f"Remote: {args.host}:{info['resolved']} owner={info['owner']} "
        f"excluded=git/venv/node_modules/cache/dist/build/data/.env"
    )

    dry_run = run(rsync_command(source, args.host, info["resolved"], dry_run=True), timeout=300)
    deletions = check_dry_run(dry_run.stdout)
    print_summary(dry_run.stdout, deletions)
    if not args.apply:
        print("Dry-run only. Re-run with --apply to synchronize.")
        return 0

    applied = run(rsync_command(source, args.host, info["resolved"], dry_run=False), timeout=1800)
    lines = applied.stdout.splitlines()
    for line in lines[-20:]:
        print(line)
    if args.bootstrap:
        bootstrap(args.host, info["resolved"])
    print("PASS: build source synchronized")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, SyncError, subprocess.TimeoutExpired) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
