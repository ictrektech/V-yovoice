"""完整镜像必须通过匿名目录审计；缺文件或摘要不符时拒绝完成发布。"""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location(
    "creative_publisher", Path(__file__).resolve().parents[1] / "scripts/publish_creative_models.py"
)
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)


def test_upstream_model_files_remain_complete():
    files = publisher.file_specs()
    assert len(files) == 46
    assert sum(file["import_only"] for file in files) == 2
    assert len({file["path"] for file in files}) == len(files)
    assert all(file["family"] for file in files)


@pytest.mark.parametrize("broken", [None, "missing", "hash", "size"])
def test_anonymous_audit_requires_every_downloadable_file(monkeypatch, tmp_path, capsys, broken):
    rows = [SimpleNamespace(path=file["path"], sha256=file["sha256"], size=file["size"])
            for file in publisher.file_specs() if not file["import_only"]]
    if broken == "missing":
        rows.pop()
    elif broken == "hash":
        rows[0].sha256 = "0" * 64
    elif broken == "size":
        rows[0].size -= 1

    class Hub:
        def list_repo_files(self, repo, kind):
            assert repo == "vivibit/v-voice-audiocpp-gguf" and kind == "model"
            return rows

    monkeypatch.setitem(sys.modules, "modelscope_hub", SimpleNamespace(HubApi=Hub))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(sys, "argv", ["publisher", "--build-root", str(tmp_path / "dev/build/audit"),
                                     "--downloadable-only", "--audit-only"])
    if broken:
        with pytest.raises(RuntimeError, match="Anonymous ModelScope verification failed"):
            publisher.main()
    else:
        publisher.main()
        assert "Anonymous catalog audit passed: 44 files" in capsys.readouterr().out
