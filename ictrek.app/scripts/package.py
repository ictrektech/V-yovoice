#!/usr/bin/env python3
from __future__ import annotations

import argparse
import io
import json
import os
import re
import shutil
import subprocess
import tarfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
DIST = ROOT / "dist"
LOCK_PATH = ROOT / "dependency-lock.json"
SPREADSHEET = os.getenv("FEISHU_SPREADSHEET_TOKEN", "Htotsn3oahO1zxt73YMcaB1zn8e")
REPOSITORY = "swr.cn-southwest-2.myhuaweicloud.com/ictrek/v-voice"
IMAGE_REFERENCE = re.compile(r"^[\w.-]+\.[\w.-]+(?::\d+)?/[^\s]+$")
PACKAGE_MEMBERS = (
    ".env",
    "manifest.yml",
    "docker-compose.yml",
    "configs.yml",
    "routers.yml",
    "icon.png",
    "README.zh-CN.md",
    "README.en.md",
)
PROFILES = {
    "VVOICE_AMD_IMAGE": ["AMD_with_mxn100"],
    "VVOICE_AMD_CUDA_IMAGE": ["AMD_with_cuda"],
    "VVOICE_ARM_IMAGE": ["ARM_without_cuda", "SOPHON_bm1688"],
    "VVOICE_ARM_CUDA_IMAGE": ["ARM_with_cuda"],
    "VVOICE_L4T_IMAGE": ["l4t"],
    "VVOICE_THOR_IMAGE": ["thor_spark"],
}
IMAGE_PREFIXES = {
    "VVOICE_AMD_IMAGE": "amd",
    "VVOICE_AMD_CUDA_IMAGE": "amd_cu128",
    "VVOICE_ARM_IMAGE": "arm",
    "VVOICE_ARM_CUDA_IMAGE": "arm_cu130",
    "VVOICE_L4T_IMAGE": "l4t",
    "VVOICE_THOR_IMAGE": "thor",
}
REMOTE_PROFILES = {
    "amd-cuda": "VVOICE_AMD_CUDA_IMAGE",
    "jetson-orin": "VVOICE_L4T_IMAGE",
    "jetson-thor": "VVOICE_THOR_IMAGE",
    "dgx-spark": "VVOICE_THOR_IMAGE",
}
DEPENDENCIES = {
    "com.ictrek.v-scheduler": ("ictrektech/V-Scheduler", "0.0.24"),
}


def appstore_version(app_id: str, base: str) -> str:
    """私有 GitHub 仓库改从已授权隧道读取实时发布记录，不扩大 CI 令牌权限。"""
    parsed = urllib.parse.urlparse(base)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.path not in {"", "/"}:
        raise RuntimeError("App Store dependency verification requires the approved loopback tunnel")
    with urllib.request.urlopen(f"{base.rstrip('/')}/api/appstore/apps/{app_id}", timeout=30) as response:
        record = json.load(response)
    detail = record.get("data") or {}
    version = detail.get("current_version", "")
    versions = [v for v in detail.get("versions", []) if re.fullmatch(r"\d+\.\d+\.\d+", v)]
    archive = detail.get("app_tar_gz") or {}
    expected = f"appstore/apps/{app_id}/{version}/app.tar.gz"
    if (record.get("code") != 0 or detail.get("id") != app_id or not versions
            or version != max(versions, key=lambda v: tuple(map(int, v.split("."))))
            or archive.get("size", 0) <= 0 or archive.get("download_path") != expected):
        raise RuntimeError(f"{app_id}: no verified latest published App Store package")
    # 实际文件必须可访问，不能把仅有索引的记录当成已发布包。
    probe = urllib.request.Request(f"{base.rstrip('/')}/store/{expected}",
                                   headers={"Range": "bytes=0-1", "Accept-Encoding": "identity"})
    with urllib.request.urlopen(probe, timeout=30) as response:
        prefix = response.read(2)
        valid = prefix == b"\x1f\x8b"
        if response.status == 206:
            valid = valid and response.headers.get("Content-Range") == f"bytes 0-1/{archive['size']}"
        elif response.status == 200:
            # 部署端可能忽略 Range 或省略 HEAD 长度；流式计数，不信任 SPA/错误页的 200。
            count = len(prefix)
            while count <= archive["size"]:
                chunk = response.read(min(1024 * 1024, archive["size"] + 1 - count))
                if not chunk:
                    break
                count += len(chunk)
            valid = valid and count == archive["size"]
        else:
            valid = False
        if not valid:
            raise RuntimeError(f"{app_id}: published App Store archive is unavailable or changed")
    return version


def load_dependency_lock(path: Path = LOCK_PATH) -> dict[str, str]:
    """读取已验收依赖；缺失、未知应用或非法版本都阻止打包。"""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise RuntimeError(
            "dependency lock is missing; run python3 ictrek.app/scripts/package.py "
            "--update-dependency-lock"
        ) from None
    locks = value.get("apps") if isinstance(value, dict) and value.get("version") == 1 else None
    if not isinstance(locks, dict) or set(locks) != set(DEPENDENCIES):
        raise RuntimeError("dependency lock does not cover the supported applications")
    for app_id, version in locks.items():
        if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version):
            raise RuntimeError(f"invalid dependency lock version for {app_id}")
    return locks


def write_dependency_lock(manifest: dict, path: Path = LOCK_PATH) -> dict[str, str]:
    """把刚从已发布包解析出的版本写成可提交的验收锁。"""
    existing = load_dependency_lock(path) if path.is_file() else {}
    apps = {}
    for dependency in manifest.get("dependencies", {}).get("apps", []):
        match = re.fullmatch(r">=(\d+\.\d+\.\d+)", str(dependency.get("version", "")))
        if not match:
            raise RuntimeError(f"{dependency.get('id')} has no resolved minimum version")
        apps[dependency["id"]] = match.group(1)
    if set(apps) != set(DEPENDENCIES):
        raise RuntimeError("dependency lock does not cover the supported applications")
    for app_id, version in apps.items():
        if app_id in existing and tuple(map(int, version.split("."))) < tuple(
            map(int, existing[app_id].split("."))
        ):
            raise RuntimeError(f"refusing dependency lock downgrade for {app_id}")
    value = {"version": 1, "apps": apps}
    temporary = path.with_suffix(f".{os.getpid()}.pending")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)
    return apps


def resolve_dependencies(manifest: dict, expected: dict[str, str] | None = None) -> None:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "V-Voice VOS packaging"}
    token = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
    if not token and shutil.which("gh"):
        # 本机复用已有登录，不要求用户把凭据复制到命令行或配置文件。
        try:
            login = subprocess.run(
                ["gh", "auth", "token", "--hostname", "github.com"],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if login.returncode == 0:
                token = login.stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            pass
    if token:
        headers["Authorization"] = "Bearer " + token
    for dependency in manifest.get("dependencies", {}).get("apps", []):
        repository, minimum = DEPENDENCIES[dependency["id"]]
        url = f"https://api.github.com/repos/{repository}/releases/latest"
        source = "GitHub Release"
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as response:
                release = json.load(response)
        except urllib.error.HTTPError as exc:
            base = os.getenv("VVOICE_APPSTORE_API_URL", "")
            if exc.code not in {401, 403, 404} or not base:
                raise RuntimeError(f"{repository}: cannot verify published dependency (GitHub HTTP {exc.code}); "
                                   "use gh auth login, GH_TOKEN/GITHUB_TOKEN, or configure VVOICE_APPSTORE_API_URL through the approved App Store tunnel") from exc
            version = appstore_version(dependency["id"], base)
            source = "VOS App Store"
        else:
            match = re.fullmatch(r"v?(\d+\.\d+\.\d+)", release.get("tag_name", ""))
            if (not match or not release.get("published_at") or release.get("draft")
                    or release.get("prerelease") or not any(
                        asset.get("name", "").endswith("_pull.tar") for asset in release.get("assets", []))):
                raise RuntimeError(f"{repository}: no verified published VOS package")
            version = match.group(1)
        # 已发布版本不能替代本应用实际需要的协议下限；不足时明确阻止打包。
        if tuple(map(int, version.split("."))) < tuple(map(int, minimum.split("."))):
            raise RuntimeError(f"{repository}: published {version} lacks required contract >= {minimum}")
        locked = (expected or {}).get(dependency["id"])
        if locked is not None and version != locked:
            raise RuntimeError(
                f"Dependency drift: {dependency['id']} locked={locked} latest={version}; "
                "retest the candidate, then run python3 ictrek.app/scripts/package.py "
                "--update-dependency-lock"
            )
        dependency["version"] = ">=" + version
        print(f"Dependency resolved: {dependency['id']} source={source} published={version} package=>={version}")


def request(method: str, url: str, token: str = "", body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers, method=method), timeout=30) as response:
        value = json.load(response)
    if value.get("code") != 0:
        raise RuntimeError(value)
    return value


def cell_text(value) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "".join(cell_text(part) for part in value).strip()
    if isinstance(value, dict):
        return str(value.get("text") or value.get("link") or "").strip()
    return "" if value is None else str(value).strip()


def column_name(index: int) -> str:
    output = ""
    while index:
        index, rem = divmod(index - 1, 26)
        output = chr(65 + rem) + output
    return output


class Feishu:
    def __init__(self) -> None:
        configured = os.getenv("FEISHU_CONFIG_FILE")
        paths = [Path(configured)] if configured else [Path.home() / ".feishu.components.json", Path.home() / ".feishu.json"]
        path = next((candidate for candidate in paths if candidate.is_file()), None)
        if path is None:
            raise RuntimeError("Feishu credential file not found")
        config = json.loads(path.read_text())
        login = request(
            "POST",
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            body={"app_id": config["feishu_app_id"], "app_secret": config["feishu_app_secret"]},
        )
        self.token = login["tenant_access_token"]
        self.base = "https://open.feishu.cn/open-apis/sheets"
        response = request("GET", f"{self.base}/v3/spreadsheets/{SPREADSHEET}/sheets/query", self.token)
        self.sheets = {row["title"]: row["sheet_id"] for row in response["data"]["sheets"]}

    def latest_image(self, title: str) -> str:
        sheet_id = self.sheets[title]
        response = request("GET", f"{self.base}/v2/spreadsheets/{SPREADSHEET}/values/{sheet_id}!A1:ZZ2", self.token)
        rows = response.get("data", {}).get("valueRange", {}).get("values", [])
        header = rows[0] if rows else []
        repos = rows[1] if len(rows) > 1 else []
        column = next((index for index, value in enumerate(header, 1) if cell_text(value) == "v-voice"), None)
        if column is None:
            raise RuntimeError(f"v-voice column missing from {title}")
        repository = cell_text(repos[column - 1]) if len(repos) >= column else REPOSITORY
        response = request(
            "GET",
            f"{self.base}/v2/spreadsheets/{SPREADSHEET}/values/{sheet_id}!{column_name(column)}4:{column_name(column)}2000",
            self.token,
        )
        values = response.get("data", {}).get("valueRange", {}).get("values", [])
        tag = next((cell_text(row[0]) for row in values if row and cell_text(row[0])), "")
        if not tag:
            raise RuntimeError(f"v-voice tag missing from {title}")
        return f"{repository or REPOSITORY}:{tag}"


def render(
    version: str,
    images: dict[str, str],
    stage: Path,
    dependency_lock: dict[str, str],
) -> None:
    stage.mkdir(parents=True)
    for name in ("manifest.yml", "configs.yml", "routers.yml", "README.zh-CN.md", "README.en.md"):
        text = (SRC / name).read_text(encoding="utf-8").replace("__APP_VERSION__", version)
        if name == "manifest.yml":
            manifest = yaml.safe_load(text)
            resolve_dependencies(manifest, expected=dependency_lock)
            text = yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False)
        (stage / name).write_text(text, encoding="utf-8")
    shutil.copy2(SRC / "icon.png", stage / "icon.png")
    env = "".join(f"{key}={value}\n" for key, value in images.items())
    (stage / ".env").write_text(env, encoding="utf-8")
    compose = (SRC / "docker-compose.yml").read_text(encoding="utf-8").replace("__APP_VERSION__", version)
    compose = re.sub(
        r"\$\{([A-Z0-9_]+)(?::-[^}]*)?\}",
        lambda match: images.get(match.group(1), match.group(0)),
        compose,
    )
    remote_images = {
        profile: images[variable] for profile, variable in REMOTE_PROFILES.items()
        if images[variable].endswith("_" + version)
    }
    if remote_images:
        compose = "x-v-scheduler-backend-images: " + json.dumps(remote_images, separators=(",", ":")) + "\n" + compose
    (stage / "docker-compose.yml").write_text(compose, encoding="utf-8")
    if re.search(r"\$\{[^}]*_IMAGE[^}]*\}", compose):
        raise RuntimeError("unrendered image variable remains")


def parse_image_overrides(values: list[str]) -> dict[str, str]:
    """解析候选包镜像覆盖；正式打包仍默认读取飞书。"""
    overrides: dict[str, str] = {}
    for value in values:
        variable, separator, image = value.partition("=")
        if not separator or variable not in PROFILES or not image:
            raise ValueError(f"invalid image override: {value}")
        if not IMAGE_REFERENCE.fullmatch(image):
            raise ValueError(f"invalid image reference: {image}")
        if variable in overrides:
            raise ValueError(f"duplicate image override: {variable}")
        overrides[variable] = image
    return overrides


def verify_release_images(images: dict[str, str], version: str) -> None:
    if set(images) != set(PROFILES):
        raise RuntimeError(f"image variables differ from supported profiles: {sorted(images)}")
    for variable, image in images.items():
        expected = f"{REPOSITORY}:{IMAGE_PREFIXES[variable]}_{version}"
        if image != expected:
            raise RuntimeError(f"{variable} requires the release image {expected} from the approved repository, got {image}")


def verify_pull_package(output: Path, version: str) -> None:
    """校验最终安装包，不依赖某个候选版本，也不访问外部服务。"""
    with tarfile.open(output) as outer:
        if outer.getnames() != ["app.tar.gz"]:
            raise RuntimeError("invalid outer package")
        archive = outer.extractfile("app.tar.gz")
        if archive is None:
            raise RuntimeError("invalid outer package")
        payload = archive.read()

    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as inner:
        members = inner.getnames()
        if sorted(members) != sorted(PACKAGE_MEMBERS) or len(members) != len(PACKAGE_MEMBERS):
            raise RuntimeError(f"invalid package members: {members}")

        def read(name: str) -> str:
            member = inner.extractfile(name)
            if member is None:
                raise RuntimeError(f"missing package member: {name}")
            return member.read().decode("utf-8")

        images: dict[str, str] = {}
        for line in read(".env").splitlines():
            if not line:
                continue
            key, separator, image = line.partition("=")
            if not separator or not key or key in images:
                raise RuntimeError(f"invalid image entry: {line}")
            images[key] = image
        manifest = yaml.safe_load(read("manifest.yml"))
        if str(manifest.get("version", "")) != version:
            raise RuntimeError(f"manifest version differs from {version}")
        verify_release_images(images, version)
        dependencies = manifest.get("dependencies", {}).get("apps", [])
        if {entry.get("id") for entry in dependencies} != set(DEPENDENCIES):
            raise RuntimeError("dependency set differs from the supported applications")
        for dependency in dependencies:
            _, minimum = DEPENDENCIES[dependency["id"]]
            match = re.fullmatch(r">=(\d+\.\d+\.\d+)", str(dependency.get("version", "")))
            if not match:
                raise RuntimeError(f"{dependency['id']} has no resolved minimum version")
            resolved = tuple(map(int, match.group(1).split(".")))
            required = tuple(map(int, minimum.split(".")))
            if resolved < required:
                raise RuntimeError(f"{dependency['id']} is below required contract {minimum}")

        compose = yaml.safe_load(read("docker-compose.yml"))
        service_images = [str(service.get("image", "")) for service in compose.get("services", {}).values()]
        if sorted(service_images) != sorted(images.values()):
            raise RuntimeError("docker-compose image references differ from .env")

    print(f"PASS: pull package {output.name} version={version} profiles={len(images)}")


def package(version: str, stage: Path) -> Path:
    DIST.mkdir(exist_ok=True)
    app_tar = DIST / "app.tar.gz"
    members = list(PACKAGE_MEMBERS)
    with tarfile.open(app_tar, "w:gz") as archive:
        for name in members:
            archive.add(stage / name, arcname=name)
    output = DIST / f"v_voice_{version}_pull.tar"
    payload = app_tar.read_bytes()
    info = tarfile.TarInfo("app.tar.gz")
    info.size = len(payload)
    with tarfile.open(output, "w") as archive:
        archive.addfile(info, io.BytesIO(payload))
    with tarfile.open(output) as archive:
        if archive.getnames() != ["app.tar.gz"]:
            raise RuntimeError("invalid outer package")
    for name in members:
        if name == "icon.png":
            continue
        text = (stage / name).read_text()
        if re.search(r"__[A-Z0-9_]+__", text):
            raise RuntimeError(f"unrendered placeholder: {name}")
    compose = yaml.safe_load((stage / "docker-compose.yml").read_text())
    if not compose.get("networks", {}).get("vos_default", {}).get("external"):
        raise RuntimeError("missing external vos_default network")
    for service in compose["services"].values():
        if not IMAGE_REFERENCE.fullmatch(service.get("image", "")):
            raise RuntimeError("invalid service image")
        if not service.get("networks", {}).get("vos_default", {}).get("aliases"):
            raise RuntimeError("missing vos_default service alias")
    verify_pull_package(output, version)
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default=os.getenv("PACKAGE_VERSION", ""))
    parser.add_argument(
        "--image",
        action="append",
        default=[],
        metavar="VARIABLE=REFERENCE",
        help="override one profile image, for example VVOICE_L4T_IMAGE=registry.example/v-voice:l4t_0.0.35",
    )
    parser.add_argument(
        "--verify-package",
        metavar="PATH",
        help="verify an existing pull package for the selected version",
    )
    parser.add_argument(
        "--update-dependency-lock",
        action="store_true",
        help="resolve live dependencies and update dependency-lock.json after retesting",
    )
    parser.add_argument("--check-release-images", action="store_true",
                        help="check all six published image tags in Feishu without building a package")
    args = parser.parse_args()
    version = args.version or (ROOT / "VERSION").read_text().strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise SystemExit(f"invalid version: {version}")
    if args.check_release_images and (args.verify_package or args.image or args.update_dependency_lock):
        parser.error("--check-release-images cannot be combined with other operations or image overrides")
    if args.update_dependency_lock:
        if args.verify_package or args.image:
            parser.error("--update-dependency-lock cannot be combined with package verification or image overrides")
        manifest = yaml.safe_load((SRC / "manifest.yml").read_text(encoding="utf-8"))
        resolve_dependencies(manifest)
        apps = write_dependency_lock(manifest)
        print(json.dumps({"dependency_lock": str(LOCK_PATH), "apps": apps}, sort_keys=True))
        return
    if args.verify_package:
        if args.image:
            parser.error("--verify-package cannot be combined with --image")
        verify_pull_package(Path(args.verify_package), version)
        return
    try:
        overrides = parse_image_overrides(args.image)
    except ValueError as exc:
        parser.error(str(exc))
    print(f"[INFO] Package version: {version}")
    print("[INFO] Image source: pull")
    feishu = None
    images = {}
    for variable, sheets in PROFILES.items():
        if variable in overrides:
            images[variable] = overrides[variable]
            profile = variable.removeprefix("VVOICE_").removesuffix("_IMAGE").lower().replace("_", "-")
            print(f"[INFO] {profile} (candidate) v-voice -> {images[variable]}")
            continue
        if feishu is None:
            feishu = Feishu()
        errors = []
        for sheet in sheets:
            try:
                images[variable] = feishu.latest_image(sheet)
            except Exception as exc:  # noqa: BLE001 - 汇总每个 sheet 的读取错误
                errors.append(str(exc))
                continue
            profile = variable.removeprefix("VVOICE_").removesuffix("_IMAGE").lower().replace("_", "-")
            print(f"[INFO] {profile} ({sheet}) v-voice -> {images[variable]}")
            break
        if variable not in images:
            raise RuntimeError("; ".join(errors))
    verify_release_images(images, version)
    if args.check_release_images:
        print(f"PASS: release image tags version={version} profiles={len(images)}")
        return
    dependency_lock = load_dependency_lock()
    stage = DIST / "staging"
    if stage.exists():
        shutil.rmtree(stage)
    render(version, images, stage, dependency_lock)
    output = package(version, stage)
    print(output)


if __name__ == "__main__":
    main()
