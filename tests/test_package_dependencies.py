"""打包只能采用已发布且满足实际协议要求的依赖，不猜测版本。"""
import importlib.util
import io
import json
from pathlib import Path
from unittest.mock import patch

import pytest

spec = importlib.util.spec_from_file_location(
    "voice_package", Path(__file__).resolve().parents[1] / "ictrek.app/scripts/package.py"
)
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


def manifest():
    return {"dependencies": {"apps": [{"id": "com.ictrek.v-scheduler", "version": "latest"}]}}


def published(version="0.0.26", **changes):
    return {"tag_name": "v" + version, "published_at": "2026-10-15T00:00:00Z",
            "assets": [{"name": f"v_scheduler_{version}_pull.tar"}], **changes}


def test_dependency_uses_actual_published_package():
    value = manifest()
    with patch("urllib.request.urlopen", return_value=io.BytesIO(json.dumps(published()).encode())):
        package.resolve_dependencies(value)
    assert value["dependencies"]["apps"][0]["version"] == ">=0.0.26"


@pytest.mark.parametrize("release", [published("0.0.23"), published(draft=True),
                                    published(assets=[]), published(published_at=None)])
def test_unpublished_or_incompatible_dependency_fails_closed(release):
    value = manifest()
    with patch("urllib.request.urlopen", return_value=io.BytesIO(json.dumps(release).encode())):
        with pytest.raises(RuntimeError):
            package.resolve_dependencies(value)
    assert value["dependencies"]["apps"][0]["version"] == "latest"


def test_unreachable_dependency_has_no_fallback():
    with patch("urllib.request.urlopen", side_effect=OSError("unreachable")):
        with pytest.raises(OSError):
            package.resolve_dependencies(manifest())
