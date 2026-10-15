#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tarfile
import tempfile
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path):
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download(url: str, target: Path) -> None:
    accelerator = os.getenv("GITHUB_ACCELERATOR", "https://gh-proxy.com/")
    candidates = [f"{accelerator.rstrip('/')}/{url}" if url.startswith("https://github.com/") else url, url]
    errors = []
    for candidate in candidates:
        try:
            request = urllib.request.Request(candidate, headers={"User-Agent": "V-Voice model publisher"})
            with urllib.request.urlopen(request, timeout=120) as response, target.open("wb") as output:
                shutil.copyfileobj(response, output, length=8 * 1024 * 1024)
            return
        except Exception as exc:
            target.unlink(missing_ok=True)
            errors.append(f"{candidate}: {exc}")
    raise RuntimeError("model download failed: " + "; ".join(errors))


def prepare(item: dict, source_spec: str | dict, output: Path) -> None:
    if isinstance(source_spec, dict) and source_spec.get("export") == "seaco":
        from export_seaco import export_model
        export_model(source_spec, output, download)
        finalize_package(item, output, f"https://modelscope.cn/models/{source_spec['modelscope_repo']}")
        return
    if isinstance(source_spec, str):
        url = source_spec
        extras = {}
    else:
        url = source_spec.get("archive")
        extras = source_spec.get("extras", {})
    unpacked = output.parent / f"{item['key']}-unpacked"
    if url:
        archive = output.parent / f"{item['key']}.tar.bz2"
        download(url, archive)
        if unpacked.exists():
            shutil.rmtree(unpacked)
        unpacked.mkdir()
        with tarfile.open(archive) as handle:
            handle.extractall(unpacked, filter="data")
        roots = [path for path in unpacked.iterdir() if path.is_dir()]
        source = roots[0] if len(roots) == 1 else unpacked
        shutil.copytree(source, output)
        archive.unlink()
    else:
        # Single-file sources (for example speaker-embedding models) have no
        # upstream archive; extras download straight into the package root.
        if output.exists():
            shutil.rmtree(output)
        output.mkdir(parents=True)
    for relative, extra_url in extras.items():
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        download(extra_url, target)
    if unpacked.exists():
        shutil.rmtree(unpacked)
    finalize_package(item, output, url)
    if url:
        archive.unlink(missing_ok=True)
    shutil.rmtree(unpacked, ignore_errors=True)


def finalize_package(item: dict, output: Path, url: str | None) -> None:
    runtime_name = "ONNX Runtime (SeACo)" if item["runtime"].get("factory") == "seaco_onnx" else "sherpa-onnx"
    descriptor = dict(item)
    (output / "vvoice-model.json").write_text(
        json.dumps(descriptor, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output / "configuration.json").write_text(
        json.dumps(
            {
                "framework": "onnx",
                "task": {
                    "asr": "automatic-speech-recognition",
                    "tts": "text-to-speech",
                    "speaker": "speaker-recognition",
                }[item["kind"]],
                "allow_remote": True,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (output / "README.md").write_text(
        f"# {item['name']}\n\nPublic {runtime_name} package for V-Voice.\n\n"
        + (f"Upstream archive: {url}\n\n" if url else "Upstream files: see SHA256SUMS.\n\n")
        + f"Runtime: {runtime_name}; no PyTorch required.\n",
        encoding="utf-8",
    )
    required = []
    for value in item["runtime"]["files"].values():
        required.extend(part.strip() for part in value.split(","))
    required.extend(item["runtime"].get("rule_fsts", []))
    missing = [name for name in required if not (output / name).exists()]
    if missing:
        raise RuntimeError(f"{item['key']}: archive is missing descriptor files: {missing}")
    checksums = []
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS":
            checksums.append(f"{sha256(path)}  {path.relative_to(output).as_posix()}")
    (output / "SHA256SUMS").write_text("\n".join(checksums) + "\n", encoding="utf-8")


def publish(item: dict, folder: Path, token: str) -> None:
    from modelscope_hub import HubApi

    repo = item["modelscope_repo"]
    authenticated = HubApi(token=token, endpoint="https://modelscope.cn")
    if not authenticated.repo_exists(repo, "model"):
        authenticated.create_repo(
            repo,
            "model",
            visibility="public",
            license="apache-2.0",
            description=f"{item['name']} for V-Voice ONNX inference",
        )
    authenticated.upload_folder(
        repo,
        "model",
        str(folder),
        path_in_repo="",
        commit_message="Publish V-Voice ONNX package",
        max_workers=8,
    )

    # A token-free metadata read and descriptor download are the release gate.
    anonymous = HubApi(endpoint="https://modelscope.cn", token="")
    anonymous.get_repo(repo, "model")
    downloaded = Path(anonymous.download_file(repo, "model", "vvoice-model.json"))
    remote = load_json(downloaded)
    if remote.get("key") != item["key"]:
        raise RuntimeError(f"{repo}: anonymous descriptor verification failed")
    print(f"PUBLIC VERIFIED {repo}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare and publicly publish V-Voice model packages")
    parser.add_argument("keys", nargs="*", help="catalog keys; defaults to all")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument(
        "--publish-prepared",
        action="store_true",
        help="publish existing prepared folders from --work-dir without downloading them again",
    )
    parser.add_argument("--work-dir", type=Path)
    args = parser.parse_args()

    if args.prepare_only and args.publish_prepared:
        raise SystemExit("--prepare-only and --publish-prepared are mutually exclusive")
    if args.publish_prepared and args.work_dir is None:
        raise SystemExit("--publish-prepared requires --work-dir")

    models = load_json(ROOT / "catalog/models.json")["models"]
    sources = load_json(ROOT / "catalog/sources.json")
    wanted = set(args.keys or sources)
    unknown = wanted - {item["key"] for item in models}
    if unknown:
        raise SystemExit(f"unknown model keys: {sorted(unknown)}")
    token = os.getenv("MODELSCOPE_API_TOKEN", "")
    if not args.prepare_only and not token:
        raise SystemExit("MODELSCOPE_API_TOKEN is required")

    work_parent = args.work_dir
    context = tempfile.TemporaryDirectory(prefix="vvoice-models-") if work_parent is None else None
    work = Path(context.name) if context else work_parent.resolve()
    work.mkdir(parents=True, exist_ok=True)
    try:
        for item in models:
            if item["key"] not in wanted:
                continue
            folder = work / item["key"]
            if args.publish_prepared:
                descriptor = folder / "vvoice-model.json"
                if not descriptor.is_file() or load_json(descriptor).get("key") != item["key"]:
                    raise RuntimeError(f"{item['key']}: prepared folder is missing a matching descriptor")
            else:
                if folder.exists():
                    shutil.rmtree(folder)
                prepare(item, sources[item["key"]], folder)
                print(f"PREPARED {item['key']} {folder}")
            if not args.prepare_only:
                publish(item, folder, token)
    finally:
        if context:
            context.cleanup()


if __name__ == "__main__":
    main()
