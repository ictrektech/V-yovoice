#!/usr/bin/env python3
"""将 VOS 候选安装包在确认后按顺序升级到目标设备。"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


DEFAULT_VOS_PORT = 8105
TERMINAL_TASKS = {"Completed", "Failed", "Cancelled", "Canceled", "Terminated"}


class PreflightError(RuntimeError):
    pass


def parse_targets(values: list[str]) -> list[tuple[str, str]]:
    targets: list[tuple[str, str]] = []
    seen: set[str] = set()
    for value in values:
        host, separator, profile = value.rpartition("=")
        if (
            not separator
            or not re.fullmatch(r"[A-Za-z0-9_.:@-]+", host)
            or not re.fullmatch(r"[a-z0-9-]+", profile)
        ):
            raise ValueError(f"target must be SSH_HOST=PROFILE: {value}")
        if host in seen:
            raise ValueError(f"duplicate target host: {host}")
        seen.add(host)
        targets.append((host, profile))
    return targets


def read_package(path: Path) -> dict:
    if not path.is_file():
        raise PreflightError(f"candidate package not found: {path}")
    try:
        import yaml
    except ImportError as exc:
        raise PreflightError("candidate inspection requires PyYAML") from exc
    try:
        with tarfile.open(path, "r:*") as outer:
            if outer.getnames() != ["app.tar.gz"]:
                raise PreflightError("outer package must contain only app.tar.gz")
            app_tar = outer.extractfile("app.tar.gz")
            if app_tar is None:
                raise PreflightError("app.tar.gz is missing")
            with tarfile.open(fileobj=app_tar, mode="r:gz") as inner:
                manifest_file = inner.extractfile("manifest.yml")
                if manifest_file is None:
                    raise PreflightError("manifest.yml is missing from app.tar.gz")
                manifest = yaml.safe_load(manifest_file.read()) or {}
    except (tarfile.TarError, OSError) as exc:
        raise PreflightError(f"cannot inspect candidate package: {exc}") from exc
    app_id = manifest.get("id")
    version = str(manifest.get("version", ""))
    if not app_id or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise PreflightError("manifest.yml is missing a valid id or version")
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return {
        "app_id": app_id,
        "version": version,
        "profiles": [
            row.get("name")
            for row in manifest.get("profiles") or []
            if isinstance(row, dict) and row.get("name")
        ],
        "dependencies": [
            {"id": row.get("id"), "version": row.get("version", "")}
            for row in (manifest.get("dependencies") or {}).get("apps") or []
            if isinstance(row, dict) and row.get("id")
        ],
        "sha256": digest.hexdigest(),
    }


def version_tuple(value: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", value)
    if not match:
        raise PreflightError(f"unsupported version: {value}")
    return tuple(map(int, match.groups()))


def requirement_satisfied(version: str, requirement: str) -> bool:
    requirement = (requirement or "").strip()
    if not requirement:
        return True
    match = re.fullmatch(r"(>=|<=|>|<|==|=)?\s*(\d+\.\d+\.\d+)", requirement)
    if not match:
        raise PreflightError(f"unsupported dependency requirement: {requirement}")
    operator = match.group(1) or "="
    current = version_tuple(version)
    required = version_tuple(match.group(2))
    return {
        ">=": current >= required,
        ">": current > required,
        "<=": current <= required,
        "<": current < required,
        "=": current == required,
        "==": current == required,
    }[operator]


def request_json(base: str, path: str, payload: dict | None = None, token: str = "") -> dict:
    data = None if payload is None else json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(base + path, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)
    except (urllib.error.HTTPError, urllib.error.URLError) as exc:
        raise PreflightError(f"VOS API request failed: {exc}") from exc


def login(base: str, username: str, password: str) -> str:
    response = request_json(base, "/v1000/user/login", {"username": username, "password": password})
    if response.get("code") != 0:
        raise PreflightError(f"VOS login failed: {response.get('msg') or response.get('code')}")
    token = (response.get("data") or {}).get("access_token")
    if not token:
        raise PreflightError("VOS login did not return an access token")
    return token


def app_detail(base: str, token: str, app_id: str) -> dict:
    query = urllib.parse.urlencode({"app_id": app_id})
    response = request_json(base, "/v1000/app/detail?" + query, token=token)
    if response.get("code") != 0:
        raise PreflightError(
            f"{app_id} is not available for upgrade: {response.get('msg') or response.get('code')}"
        )
    return response.get("data") or {}


def installed_profile(detail: dict) -> str:
    value = (detail.get("configs_current") or {}).get("VOS_APP_PROFILES", "")
    if isinstance(value, list):
        return ",".join(map(str, value))
    return str(value)


def dependency_status(base: str, token: str, dependencies: list[dict]) -> list[dict]:
    if not dependencies:
        return []
    query = urllib.parse.urlencode({"page": 0, "page_size": 1000})
    response = request_json(base, "/v1000/app/list?" + query, token=token)
    if response.get("code") != 0:
        raise PreflightError(f"cannot read installed apps: {response.get('msg') or response.get('code')}")
    installed = {
        row.get("app_id"): row
        for row in (response.get("data") or {}).get("data") or []
    }
    result = []
    for dependency in dependencies:
        row = installed.get(dependency["id"]) or {}
        version = str(row.get("version", ""))
        state = str(row.get("state", ""))
        satisfied = bool(version) and state == "installed" and requirement_satisfied(
            version, dependency.get("version", "")
        )
        result.append({
            "id": dependency["id"],
            "required": dependency.get("version", ""),
            "installed": version,
            "state": state,
            "satisfied": satisfied,
        })
    return result


def inspect_target(base: str, token: str, host: str, profile: str, package: dict) -> dict:
    detail = app_detail(base, token, package["app_id"])
    current_version = str((detail.get("manifest") or {}).get("version", ""))
    current_profile = installed_profile(detail)
    dependencies = dependency_status(base, token, package["dependencies"])
    errors = []
    if detail.get("state") != "installed":
        errors.append(f"application state is {detail.get('state')!r}, expected 'installed'")
    if current_profile != profile:
        errors.append(
            f"selected profile {profile!r} does not match installed profile {current_profile!r}"
        )
    if current_version == package["version"]:
        errors.append("candidate version already has the installed version")
    if detail.get("current_task_id"):
        errors.append(f"VOS task is already running: {detail['current_task_id']}")
    errors.extend(
        (
            f"dependency {row['id']} requires {row['required']}, "
            f"installed {row['installed'] or 'none'} ({row['state'] or 'missing'})"
        )
        for row in dependencies
        if not row["satisfied"]
    )
    return {
        "host": host,
        "app_id": package["app_id"],
        "candidate_version": package["version"],
        "current_version": current_version,
        "profile": profile,
        "installed_profile": current_profile,
        "state": detail.get("state"),
        "runtime_ready": bool(detail.get("runtime_ready")),
        "dependencies": dependencies,
        "errors": errors,
        "ok": not errors,
    }


def upload_package(base: str, token: str, package: Path) -> str:
    parsed = urllib.parse.urlparse(base)
    boundary = "----vos-preflight-" + uuid.uuid4().hex
    prefix = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="package"; filename="{package.name}"\r\n'
        "Content-Type: application/gzip\r\n\r\n"
    ).encode()
    suffix = f"\r\n--{boundary}--\r\n".encode()
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=300)
    try:
        connection.putrequest("POST", "/v1000/app-store/upload_app")
        connection.putheader("Authorization", "Bearer " + token)
        connection.putheader("Content-Type", f"multipart/form-data; boundary={boundary}")
        connection.putheader("Content-Length", str(len(prefix) + package.stat().st_size + len(suffix)))
        connection.endheaders()
        connection.send(prefix)
        with package.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                connection.send(chunk)
        connection.send(suffix)
        response = connection.getresponse()
        body = response.read()
        status = response.status
    finally:
        connection.close()
    try:
        result = json.loads(body)
    except json.JSONDecodeError as exc:
        raise PreflightError("VOS upload returned invalid JSON") from exc
    if status >= 400 or result.get("code") != 0:
        raise PreflightError(f"VOS upload failed: {result.get('msg') or status}")
    source_id = (result.get("data") or {}).get("source_id")
    if not source_id:
        raise PreflightError("VOS upload did not return source_id")
    return source_id


def wait_for_task(base: str, token: str, task_id: str, timeout: int) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        query = urllib.parse.urlencode({"task_id": task_id})
        response = request_json(base, "/v1000/async-task/get?" + query, token=token)
        if response.get("code") != 0:
            raise PreflightError(f"cannot read VOS task: {response.get('msg') or response.get('code')}")
        task = response.get("data") or {}
        if task.get("status") in TERMINAL_TASKS:
            return task
        time.sleep(3)
    raise PreflightError(f"VOS task timed out: {task_id}")


def apply_target(base: str, token: str, host: str, profile: str, package_file: Path,
                 package: dict, timeout: int) -> dict:
    plan = inspect_target(base, token, host, profile, package)
    if not plan["ok"]:
        return {"ok": False, "stage": "plan", "plan": plan}
    source_id = upload_package(base, token, package_file)
    response = request_json(base, "/v1000/app-store/upgrade_async", {
        "source_id": source_id,
        "app_id": package["app_id"],
        "version": package["version"],
        "profiles": [profile],
    }, token=token)
    if response.get("code") != 0:
        raise PreflightError(f"VOS upgrade was rejected: {response.get('msg') or response.get('code')}")
    task_id = (response.get("data") or {}).get("task_id")
    if not task_id:
        raise PreflightError("VOS upgrade did not return task_id")
    task = wait_for_task(base, token, task_id, timeout)
    detail = app_detail(base, token, package["app_id"])
    version = str((detail.get("manifest") or {}).get("version", ""))
    current_profile = installed_profile(detail)
    errors = []
    if task.get("status") != "Completed":
        errors.append(f"VOS task ended with {task.get('status')!r}")
    if detail.get("state") != "installed":
        errors.append(f"application state is {detail.get('state')!r}")
    if version != package["version"]:
        errors.append(f"installed version is {version!r}, expected {package['version']!r}")
    if current_profile != profile:
        errors.append(f"installed profile is {current_profile!r}, expected {profile!r}")
    if not detail.get("runtime_ready"):
        errors.append("application runtime is not ready")
    return {
        "ok": not errors,
        "stage": "install",
        "plan": plan,
        "host": host,
        "task_id": task_id,
        "task_status": task.get("status"),
        "candidate_version": package["version"],
        "current_version": version,
        "profile": current_profile,
        "state": detail.get("state"),
        "runtime_ready": bool(detail.get("runtime_ready")),
        "errors": errors,
    }


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


@contextmanager
def ssh_tunnel(host: str, remote_port: int):
    local_port = free_port()
    try:
        process = subprocess.Popen(
            [
                "ssh", "-N", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
                "-o", "ExitOnForwardFailure=yes",
                "-L", f"127.0.0.1:{local_port}:127.0.0.1:{remote_port}", host,
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
        )
    except OSError as exc:
        raise PreflightError(f"cannot start SSH tunnel for {host}: {exc}") from exc
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise PreflightError(
                    f"SSH tunnel failed for {host}: {(process.stderr.read() or '').strip()[:300]}"
                )
            try:
                with socket.create_connection(("127.0.0.1", local_port), timeout=1):
                    break
            except OSError:
                time.sleep(0.2)
        else:
            raise PreflightError(f"SSH tunnel timed out for {host}")
        yield f"http://127.0.0.1:{local_port}"
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def summary_rows(results: list[dict]) -> str:
    lines = [
        "device\tinstalled_profile\tcandidate_profile\tcurrent\tcandidate\tresult\tdetails",
    ]
    for result in results:
        plan = result.get("plan") or result
        details = result.get("error") or "; ".join(plan.get("errors") or [])
        lines.append("\t".join([
            result.get("host", "-"),
            str(plan.get("installed_profile") or plan.get("profile") or "-"),
            str(plan.get("profile") or result.get("profile") or "-"),
            str(plan.get("current_version", "-")),
            str(plan.get("candidate_version", "-")),
            "ok" if result.get("ok") else "blocked",
            details or "-",
        ]))
    return "\n".join(lines)


def common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--target", action="append", required=True, metavar="SSH_HOST=PROFILE")
    parser.add_argument("--username", default=os.getenv("VOS_ADMIN_USERNAME", "admin"))
    parser.add_argument("--password-env", default="VOS_ADMIN_PASSWORD")
    parser.add_argument("--remote-port", type=int, default=DEFAULT_VOS_PORT)
    parser.add_argument("--timeout", type=int, default=1800)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command")
    plan_parser = subparsers.add_parser("plan", help="read targets without changing them")
    common_arguments(plan_parser)
    apply_parser = subparsers.add_parser("apply", help="upgrade confirmed targets in order")
    common_arguments(apply_parser)
    apply_parser.add_argument("--confirmed", action="store_true")
    args = parser.parse_args()
    if args.command not in {"plan", "apply"}:
        parser.error("choose plan or apply")
    if args.command == "apply" and not args.confirmed:
        parser.error("apply requires --confirmed after reviewing a plan")
    try:
        package = read_package(args.package.resolve())
        targets = parse_targets(args.target)
        unknown = [profile for _, profile in targets if profile not in package["profiles"]]
        if unknown:
            raise PreflightError(f"profiles not declared by candidate: {', '.join(unknown)}")
        password = os.getenv(args.password_env, "")
        if not password:
            raise PreflightError(f"set {args.password_env} from the approved credential source")
    except (ValueError, PreflightError) as exc:
        parser.error(str(exc))
    print(
        f"candidate={package['app_id']}@{package['version']} sha256={package['sha256']}",
        file=sys.stderr,
    )
    results: list[dict] = []
    for index, (host, profile) in enumerate(targets):
        try:
            with ssh_tunnel(host, args.remote_port) as base:
                token = login(base, args.username, password)
                if args.command == "plan":
                    result = inspect_target(base, token, host, profile, package)
                else:
                    result = apply_target(
                        base, token, host, profile, args.package.resolve(), package, args.timeout
                    )
        except PreflightError as exc:
            result = {"host": host, "ok": False, "error": str(exc)}
        results.append(result)
        if args.command == "apply":
            print(f"{host}: {'installed' if result.get('ok') else 'blocked'}", file=sys.stderr)
            if not result.get("ok"):
                results.extend(
                    {
                        "host": remaining_host,
                        "ok": False,
                        "error": "not attempted after previous target failed",
                    }
                    for remaining_host, _ in targets[index + 1:]
                )
                break
    print(summary_rows(results))
    print(json.dumps(results, ensure_ascii=False))
    return 0 if all(result.get("ok") for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
