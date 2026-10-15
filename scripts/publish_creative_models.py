#!/usr/bin/env python3
"""构建机上的 GGUF / 音色库镜像工具；只上传 ModelScope，保留原始校验值与许可。"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
REVISION = "6d5436fc85f7a20c2e9f4e472b7f3a532f686444"


def file_specs():
    rows = json.loads((ROOT / "internal/catalog/catalog.json").read_text())
    files = {}
    for model in rows:
        source_repo = model.get("repo") or "audio-cpp/audio.cpp-gguf"
        for f in model.get("files") or [{"path": model["remotePath"], "size": model["size"], "sha256": model["sha256"]}]:
            relative = f["path"] or f"imports/{model['id']}.gguf"
            target = f"mirrors/{source_repo}/{relative}" if model.get("repo") else relative
            spec = {**f, "path": target, "source_path": f["path"], "repo": source_repo,
                    "family": model["family"],
                    "revision": model.get("revision") or REVISION, "import_only": not bool(f["path"])}
            if target in files and files[target] != spec:
                raise ValueError(f"conflicting file: {target}")
            files[target] = spec
    return list(files.values())


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(8 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verified(path, spec):
    return path.is_file() and path.stat().st_size == spec["size"] and digest(path) == spec["sha256"]


@lru_cache(maxsize=1)
def mirror_files():
    from modelscope_hub import HubApi
    return {(f.sha256, f.size): f.path for f in HubApi().list_repo_files("HereIsMark/audio.cpp-gguf", "model") if f.sha256}


def download(spec, target, cache, hf_token):
    from modelscope_hub import HubApi
    target.parent.mkdir(parents=True, exist_ok=True)
    if verified(target, spec):
        return
    if spec["import_only"]:
        raise RuntimeError(f"import-only file required: {spec['path']} (SHA256 {spec['sha256']})")
    # 优先读取已存在的 ModelScope 镜像；任何来源都必须匹配固定目录中的 SHA256。
    try:
        mirror_path = mirror_files().get((spec["sha256"], spec["size"]))
        if not mirror_path:
            mirror_path = spec["source_path"] if spec["repo"] == "audio-cpp/audio.cpp-gguf" else spec["repo"].rsplit("/", 1)[-1] + "/" + spec["source_path"]
        path = HubApi().download_file("HereIsMark/audio.cpp-gguf", "model", mirror_path,
                                     cache_dir=cache, expected_sha256=spec["sha256"])
        shutil.copyfile(path, target)
        if verified(target, spec):
            return
    except Exception:
        print(f"ModelScope source unavailable: {spec['path']}", flush=True)
    # 仅在构建机使用 Hugging Face 原地址与 hf-mirror；令牌不写日志或源码。
    repo = spec["repo"]
    kind = "datasets/" if repo.startswith("datasets/") else ""
    repo = repo.removeprefix("datasets/")
    part = target.with_name(target.name + ".partial")
    for domain in ("huggingface.co", "hf-mirror.com"):
        url = f"https://{domain}/{kind}{repo}/resolve/{spec['revision']}/{urllib.parse.quote(spec['source_path'], safe='/')}"
        headers = {"User-Agent": "V-Voice model publisher"}
        if hf_token:
            headers["Authorization"] = "Bearer " + hf_token
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=180) as response, part.open("wb") as output:
                shutil.copyfileobj(response, output, 8 << 20)
            if verified(part, spec):
                part.replace(target)
                return
        except Exception:
            print(f"Source download failed: {domain} {spec['path']}", flush=True)
    raise RuntimeError(f"No verified source for {spec['path']}; check upstream access/license agreement")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-root", type=Path, required=True)
    parser.add_argument("--credentials", type=Path)
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--audit-only", action="store_true", help="verify anonymous remote hashes; with --publish, finalize only the complete source/license index after staged uploads")
    parser.add_argument("--downloadable-only", action="store_true", help="stage published upstream files; import-only variants remain supported but require an administrator-supplied verified file")
    parser.add_argument("--model", action="append", default=[], help="stage a named model's files; does not change supported catalog")
    args = parser.parse_args()
    specs = file_specs()
    if args.downloadable_only:
        specs = [f for f in specs if not f["import_only"]]
    if args.model:
        rows = json.loads((ROOT / "internal/catalog/catalog.json").read_text())
        requested = {row["id"]: row for row in rows if row["id"] in args.model}
        if set(requested) != set(args.model):
            raise SystemExit("Unknown model ID")
        hashes = {f["sha256"] for row in requested.values() for f in row.get("files") or [row]}
        specs = [f for f in specs if f["sha256"] in hashes]
    if args.plan:
        print(json.dumps({"files": specs, "total_bytes": sum(f["size"] for f in specs)}, indent=2))
        return
    build_root = args.build_root.resolve()
    if not build_root.is_relative_to((Path.home() / "dev/build").resolve()):
        raise SystemExit("Model artifacts must stay under ~/dev/build on a build host")
    if os.uname().sysname != "Linux":
        raise SystemExit("Model downloads/uploads run on a Linux build host, not the local Mac")
    credentials = {}
    if args.credentials:
        if args.credentials.stat().st_mode & 0o077:
            raise SystemExit("Credential file must be private (0600)")
        credentials = json.loads(args.credentials.read_text())
    weights = build_root / "weights"
    weights.mkdir(parents=True, exist_ok=True)
    repo = json.loads((ROOT / "internal/catalog/vos.json").read_text())["modelscope_repo"]
    if args.audit_only:
        from modelscope_hub import HubApi
        remote = {f.path: f for f in HubApi().list_repo_files(repo, "model")}
        for spec in specs:
            f = remote.get(spec["path"])
            if f is None or f.size != spec["size"] or f.sha256 != spec["sha256"]:
                raise RuntimeError(f"Anonymous ModelScope verification failed: {spec['path']}")
        print(f"Anonymous catalog audit passed: {len(specs)} files", flush=True)
        if not args.publish:
            return
    def stage(spec):
        print(f"Verify/download {spec['path']}", flush=True)
        download(spec, weights / spec["path"], build_root / "cache", credentials.get("hf", ""))
    if not args.audit_only:
        with ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(stage, specs))
    shutil.copyfile(ROOT / "THIRD_PARTY_NOTICES.md", weights / "THIRD_PARTY_NOTICES.md")
    shutil.copyfile(ROOT / "web/public/model-license.txt", weights / "INDEXTTS-MODEL-LICENSE.txt")
    (weights / "source-index.json").write_text(json.dumps(specs, indent=2) + "\n")
    (weights / "SHA256SUMS").write_text("".join(f"{f['sha256']}  {f['path']}\n" for f in specs))
    if not args.publish:
        return
    if not credentials.get("modelscope"):
        raise SystemExit("Private ModelScope credential required")
    # 发布前要求运营方已经随镜像材料准备原始许可证全文；不把混合许可标为 Apache。
    license_index_path = weights / "licenses/source-index.json"
    if not license_index_path.is_file():
        raise SystemExit("Original model licenses and their source-index.json are required before publication")
    license_index = json.loads(license_index_path.read_text())
    for spec in specs:
        family = spec["family"]
        notice = license_index.get(spec["path"], license_index.get(family, {}))
        relative = Path(notice.get("path", ""))
        if not notice.get("source_urls") or relative.is_absolute() or ".." in relative.parts:
            raise SystemExit(f"Unverified original license: {family}")
        text = weights / "licenses" / relative
        if not text.is_file() or text.stat().st_size < 100 or digest(text) != notice.get("sha256"):
            raise SystemExit(f"Missing or changed original license: {family}")
    # 只发布本次完整校验的文件，不把其他线程的半成品或未选择的权重一并上传。
    publication = Path(tempfile.mkdtemp(prefix="publish-", dir=build_root))
    for spec in ([] if args.audit_only else specs):
        target = publication / spec["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.hardlink_to(weights / spec["path"])
    for name in ("THIRD_PARTY_NOTICES.md", "INDEXTTS-MODEL-LICENSE.txt", "source-index.json", "SHA256SUMS"):
        shutil.copyfile(weights / name, publication / name)
    shutil.copytree(weights / "licenses", publication / "licenses")
    from modelscope_hub import HubApi
    api = HubApi(token=credentials["modelscope"])
    try:
        api.get_repo(repo, "model")
    except Exception:
        api.create_repo(repo, "model", visibility="public", license="other", description="V-Voice audio.cpp models; original model licenses apply")
    api.upload_folder(repo, "model", publication, sync_remote_repo=False, disable_tqdm=True, max_workers=2,
                      commit_message="Mirror verified audio.cpp model files and original notices")
    remote = {f.path: f for f in HubApi().list_repo_files(repo, "model")}
    for spec in specs:
        f = remote.get(spec["path"])
        if f is None or f.size != spec["size"] or f.sha256 != spec["sha256"]:
            raise RuntimeError(f"Anonymous ModelScope verification failed: {spec['path']}")
    print(f"Verified ModelScope publication: {repo}, {len(specs)} files", flush=True)


if __name__ == "__main__":
    main()
