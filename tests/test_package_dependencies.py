"""打包只能采用已发布且满足实际协议要求的依赖，不猜测版本。"""
import importlib.util
import io
import json
import tempfile
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
    with patch(
        "urllib.request.urlopen",
        return_value=io.BytesIO(json.dumps(release).encode()),
    ), pytest.raises(RuntimeError):
        package.resolve_dependencies(value)
    assert value["dependencies"]["apps"][0]["version"] == "latest"


def test_unreachable_dependency_has_no_fallback():
    with patch("urllib.request.urlopen", side_effect=OSError("unreachable")), pytest.raises(OSError):
        package.resolve_dependencies(manifest())


def test_candidate_image_overrides_are_explicit_and_valid():
    reference = "registry.example.test/team/v-voice:l4t_0.0.35"
    assert package.parse_image_overrides([f"VVOICE_L4T_IMAGE={reference}"]) == {
        "VVOICE_L4T_IMAGE": reference
    }
    for value in (f"UNKNOWN_IMAGE={reference}", "VVOICE_L4T_IMAGE=not-a-registry-reference"):
        with pytest.raises(ValueError):
            package.parse_image_overrides([value])
    with pytest.raises(ValueError, match="duplicate"):
        package.parse_image_overrides([f"VVOICE_L4T_IMAGE={reference}"] * 2)


def test_dependency_lock_rejects_live_drift():
    value = manifest()
    release = published("0.0.121")
    with patch(
        "urllib.request.urlopen",
        return_value=io.BytesIO(json.dumps(release).encode()),
    ), pytest.raises(RuntimeError, match="Dependency drift"):
        package.resolve_dependencies(value, expected={"com.ictrek.v-scheduler": "0.0.120"})
    assert value["dependencies"]["apps"][0]["version"] == "latest"


def test_dependency_lock_round_trip_and_validation():
    value = manifest()
    release = published("0.0.120")
    with patch("urllib.request.urlopen", return_value=io.BytesIO(json.dumps(release).encode())):
        package.resolve_dependencies(value)
    with tempfile.TemporaryDirectory() as directory:
        lock = Path(directory) / "dependency-lock.json"
        assert package.write_dependency_lock(value, lock) == {
            "com.ictrek.v-scheduler": "0.0.120"
        }
        assert package.load_dependency_lock(lock) == {
            "com.ictrek.v-scheduler": "0.0.120"
        }
        with pytest.raises(RuntimeError, match="downgrade"):
            package.write_dependency_lock(manifest() | {
                "dependencies": {"apps": [{"id": "com.ictrek.v-scheduler", "version": ">=0.0.119"}]}
            }, lock)
        lock.write_text(json.dumps({"version": 1, "apps": {"other": "1.2.3"}}))
        with pytest.raises(RuntimeError, match="supported applications"):
            package.load_dependency_lock(lock)
