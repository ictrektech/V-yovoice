"""Export the official SeACo checkpoint on a build host (never at inference time)."""
from __future__ import annotations

import functools
import hashlib
import json
import shutil
from pathlib import Path


def export_model(spec: dict, output: Path, download) -> None:
    import torch
    import yaml
    from funasr import AutoModel
    from onnxruntime.quantization import QuantType, quantize_dynamic

    upstream = output.parent / f"{output.name}-upstream"
    upstream.mkdir(parents=True, exist_ok=True)
    repo, revision = spec["modelscope_repo"], spec["revision"]
    for name in ("model.pt", "config.yaml", "configuration.json", "am.mvn", "tokens.json", "seg_dict", "example/asr_example.wav", "asr_example_hotword.wav"):
        target = upstream / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.is_file():
            download(f"https://modelscope.cn/models/{repo}/resolve/{revision}/{name}", target)
    hasher = hashlib.sha256()
    with (upstream / "model.pt").open("rb") as checkpoint:
        for block in iter(lambda: checkpoint.read(8 * 1024 * 1024), b""):
            hasher.update(block)
    digest = hasher.hexdigest()
    if digest != spec["checkpoint_sha256"]:
        raise ValueError("SeACo checkpoint SHA-256 does not match the pinned upstream")
    # FunASR's export uses dynamic_axes; retain the legacy exporter on Torch 2.9+.
    exported = upstream
    if not all((upstream / f"{name}.onnx").is_file() for name in ("model", "model_eb")):
        original_export = torch.onnx.export
        torch.onnx.export = functools.partial(original_export, dynamo=False)
        try:
            model = AutoModel(model=str(upstream), device="cpu", disable_update=True)
            exported = Path(model.export(type="onnx", quantize=False, device="cpu"))
        finally:
            torch.onnx.export = original_export
    output.mkdir(parents=True, exist_ok=True)
    for name in ("model", "model_eb"):
        quantize_dynamic(str(exported / f"{name}.onnx"), str(output / f"{name}.int8.onnx"),
                         weight_type=QuantType.QUInt8, op_types_to_quantize=["MatMul"])
    config = yaml.safe_load((upstream / "config.yaml").read_text())
    frontend = config["frontend_conf"]
    cmvn = []
    lines = (upstream / "am.mvn").read_text().splitlines()
    for index, line in enumerate(lines):
        if line.startswith(("<AddShift>", "<Rescale>")):
            values = lines[index + 1].split()
            cmvn.append([float(value) for value in values[3:-1]])
    (output / "frontend.json").write_text(json.dumps({"frontend": frontend, "cmvn": cmvn,
        "predictor_bias": config.get("model_conf", {}).get("predictor_bias", 0)}) + "\n")
    shutil.copyfile(upstream / "tokens.json", output / "tokens.json")
    (output / "PROVENANCE.json").write_text(json.dumps({"upstream": repo, "revision": revision, "checkpoint_sha256": digest,
        "exporter": "FunASR 1.2.6", "torch": torch.__version__, "quantization": "dynamic QUInt8 MatMul",
        "runtime": "ONNX Runtime; no PyTorch or FunASR runtime dependency"}, indent=2) + "\n")
