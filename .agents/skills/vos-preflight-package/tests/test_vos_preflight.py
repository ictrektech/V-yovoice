"""V-yovoice 的 VOS 预检脚本离线测试。"""

import io
import importlib.util
from pathlib import Path
import tarfile
import tempfile
import unittest

import yaml


spec = importlib.util.spec_from_file_location(
    "vos_preflight", Path(__file__).resolve().parents[1] / "scripts/vos_preflight.py"
)
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)


def write_package(path: Path) -> None:
    manifest = {
        "id": "com.ictrek.test",
        "version": "0.1.2",
        "profiles": [{"name": "amd-cuda"}, {"name": "l4t"}, {"name": "thor"}],
        "dependencies": {
            "apps": [{"id": "com.ictrek.v-scheduler", "version": ">=0.0.102"}]
        },
    }
    app_payload = yaml.safe_dump(manifest).encode()
    app_tar = io.BytesIO()
    with tarfile.open(fileobj=app_tar, mode="w:gz") as archive:
        info = tarfile.TarInfo("manifest.yml")
        info.size = len(app_payload)
        archive.addfile(info, io.BytesIO(app_payload))
    outer = io.BytesIO()
    with tarfile.open(fileobj=outer, mode="w") as archive:
        payload = app_tar.getvalue()
        info = tarfile.TarInfo("app.tar.gz")
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))
    path.write_bytes(outer.getvalue())


class VosPreflightTest(unittest.TestCase):
    def test_parse_targets_requires_unique_host_profile_pairs(self):
        self.assertEqual(preflight.parse_targets(["a=amd-cuda", "b=l4t"]), [
            ("a", "amd-cuda"),
            ("b", "l4t"),
        ])
        for values in (["missing-profile"], ["a=amd-cuda", "a=thor"]):
            with self.subTest(values=values), self.assertRaises(ValueError):
                preflight.parse_targets(values)

    def test_read_package_reads_candidate_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory) / "candidate.tar"
            write_package(package)
            data = preflight.read_package(package)
        self.assertEqual(data["app_id"], "com.ictrek.test")
        self.assertEqual(data["version"], "0.1.2")
        self.assertEqual(data["profiles"], ["amd-cuda", "l4t", "thor"])
        self.assertEqual(data["dependencies"], [
            {"id": "com.ictrek.v-scheduler", "version": ">=0.0.102"}
        ])
        self.assertEqual(len(data["sha256"]), 64)

    def test_requirement_satisfied_supports_versions_used_by_packages(self):
        self.assertTrue(preflight.requirement_satisfied("0.0.102", ">=0.0.102"))
        self.assertTrue(preflight.requirement_satisfied("0.0.103", ">=0.0.102"))
        self.assertFalse(preflight.requirement_satisfied("0.0.101", ">=0.0.102"))
        self.assertTrue(preflight.requirement_satisfied("0.0.102", "=0.0.102"))
        with self.assertRaises(preflight.PreflightError):
            preflight.requirement_satisfied("0.0.102", "^0.0.102")


if __name__ == "__main__":
    unittest.main()
