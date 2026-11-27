"""发布包契约检查必须覆盖每个版本，而不是绑定历史候选版本。"""
import importlib.util
import io
import tarfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("voice_package", ROOT / "ictrek.app/scripts/package.py")
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


def image_references(version="1.2.3"):
    return {
        variable: f"{package.REPOSITORY}:{prefix}_{version}"
        for variable, prefix in package.IMAGE_PREFIXES.items()
    }


def write_package(path, *, package_version="1.2.3", images=None,
                  dependency=">=0.0.120", compose_images=None):
    if images is None:
        images = image_references(package_version)
    manifest = {
        "version": package_version,
        "dependencies": {
            "apps": [{"id": "com.ictrek.v-scheduler", "version": dependency}]
        },
    }
    if compose_images is None:
        compose_images = list(images.values())
    service_images = compose_images
    compose = {
        "services": {
            f"service-{index}": {"image": image}
            for index, image in enumerate(service_images, 1)
        }
    }
    files = {
        ".env": "".join(f"{key}={value}\n" for key, value in images.items()).encode(),
        "manifest.yml": yaml.safe_dump(manifest, sort_keys=False).encode(),
        "docker-compose.yml": yaml.safe_dump(compose, sort_keys=False).encode(),
        "configs.yml": b"[]\n",
        "routers.yml": b"[]\n",
        "icon.png": b"png",
        "README.zh-CN.md": b"zh\n",
        "README.en.md": b"en\n",
    }
    inner_bytes = io.BytesIO()
    with tarfile.open(fileobj=inner_bytes, mode="w:gz") as inner:
        for name, value in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(value)
            inner.addfile(info, io.BytesIO(value))
    payload = inner_bytes.getvalue()
    with tarfile.open(path, "w") as outer:
        info = tarfile.TarInfo("app.tar.gz")
        info.size = len(payload)
        outer.addfile(info, io.BytesIO(payload))


def test_valid_pull_package_is_accepted(tmp_path, capsys):
    path = tmp_path / "v_voice_1.2.3_pull.tar"
    write_package(path)

    package.verify_pull_package(path, "1.2.3")

    assert "profiles=6" in capsys.readouterr().out


@pytest.mark.parametrize("dependency", ["latest", ">=0.0.23"])
def test_dependency_must_be_resolved_and_meet_protocol_contract(tmp_path, dependency):
    path = tmp_path / "v_voice_1.2.3_pull.tar"
    write_package(path, dependency=dependency)

    with pytest.raises(RuntimeError, match="minimum|contract"):
        package.verify_pull_package(path, "1.2.3")


def test_images_must_use_the_approved_repository(tmp_path):
    images = image_references()
    images["VVOICE_L4T_IMAGE"] = "docker.io/library/alpine:latest"
    path = tmp_path / "v_voice_1.2.3_pull.tar"
    write_package(path, images=images)

    with pytest.raises(RuntimeError, match="approved repository"):
        package.verify_pull_package(path, "1.2.3")


@pytest.mark.parametrize("tag", ["arm_1.2.2", "amd_1.2.3"])
def test_profile_requires_its_image_for_the_release_version(tmp_path, tag):
    images = image_references()
    images["VVOICE_ARM_IMAGE"] = f"{package.REPOSITORY}:{tag}"
    path = tmp_path / "v_voice_1.2.3_pull.tar"
    write_package(path, images=images)

    with pytest.raises(RuntimeError, match="VVOICE_ARM_IMAGE requires the release image"):
        package.verify_pull_package(path, "1.2.3")


def test_compose_images_must_match_env(tmp_path):
    images = image_references()
    compose_images = list(images.values())
    compose_images[-1] = compose_images[0]
    path = tmp_path / "v_voice_1.2.3_pull.tar"
    write_package(path, images=images, compose_images=compose_images)

    with pytest.raises(RuntimeError, match="docker-compose"):
        package.verify_pull_package(path, "1.2.3")


def test_manifest_version_must_match_artifact_name(tmp_path):
    path = tmp_path / "v_voice_1.2.3_pull.tar"
    write_package(path, package_version="1.2.4")

    with pytest.raises(RuntimeError, match="manifest version"):
        package.verify_pull_package(path, "1.2.3")


def test_release_workflow_verifies_every_version():
    workflow = (ROOT / ".github/workflows/vos-release.yml").read_text()

    assert "0.0.35" not in workflow
    assert "Verify pull package contract" in workflow
    assert "--verify-package" in workflow
