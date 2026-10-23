#!/usr/bin/env python3
"""导出开发页面的完整模型目录；只读源码描述，不加载推理框架或模型权重。"""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vvoice.catalog import catalog
from vvoice.creative import models


def metadata(item):
    value = {key: field for key, field in item.items() if key != "runtime"}
    value["required_files"] = item.get("shared_files") or [
        {"path": path} for relative in ["vvoice-model.json", *item["runtime"]["files"].values()]
        for path in relative.split(",")
    ]
    return value


print(json.dumps({"speech": [metadata(item) for item in catalog()],
                 "creative": [metadata(item) for item in models(include_non_speech=True)]}))
