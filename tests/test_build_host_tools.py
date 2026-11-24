"""构建机同步和工具链自举脚本的离线约束。"""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sync = load("sync_build_source")
bootstrap = load("bootstrap_build_host")


def test_sync_command_protects_git_credentials_and_caches():
    command = sync.rsync_command(ROOT, "czy@host", "/home/czy/dev/repos/V-yovoice", dry_run=True)

    assert "--delete" in command
    assert "--delete-excluded" not in command
    assert "--exclude=.ruff_cache/" in command
    assert "--exclude=.env" in command
    assert "--exclude=/.git/" in command
    assert all("whl" not in value for value in command)


def test_sync_rejects_protected_deletions():
    with pytest.raises(sync.SyncError, match="protected deletion"):
        sync.check_dry_run("*deleting .git/config\n*deleting cache/file\n")


def test_remote_destination_must_be_dedicated_and_owned():
    info = {
        "home": "/home/czy",
        "resolved": "/home/czy/dev/repos/V-yovoice",
        "user": "czy",
        "owner": "czy",
        "parent_owner": "czy",
    }
    sync.validate_remote(info)
    with pytest.raises(sync.SyncError, match="must resolve"):
        sync.validate_remote({**info, "resolved": "/home/czy/p/vai/apps/V-yovoice"})
    with pytest.raises(sync.SyncError, match="owned"):
        sync.validate_remote({**info, "owner": "root"})


def test_bootstrap_accepts_only_supported_tool_versions():
    required_go = bootstrap.required_go_version()

    assert bootstrap.node_ok("v22.23.5")
    assert not bootstrap.node_ok("v18.20.4")
    assert bootstrap.go_ok(f"go version go{required_go} linux/arm64", required_go)
    assert not bootstrap.go_ok("go version go1.25.0 linux/amd64", required_go)
    env = bootstrap.env_content(Path("/home/czy/dev/toolchains"))
    assert "/node/current/bin:/home/czy/dev/toolchains/go/current/bin" in env
    assert "GOTOOLCHAIN=local" in env


def test_bootstrap_detects_only_managed_toolchains(tmp_path):
    assert bootstrap.detect("node", tmp_path) == (None, "")
    assert bootstrap.detect("go", tmp_path) == (None, "")
