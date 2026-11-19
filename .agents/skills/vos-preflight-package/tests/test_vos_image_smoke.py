"""V-yovoice 镜像冒烟脚本的离线测试。"""

import argparse
import importlib.util
from pathlib import Path
import unittest


spec = importlib.util.spec_from_file_location(
    "vos_image_smoke",
    Path(__file__).resolve().parents[1] / "scripts/vos_image_smoke.py",
)
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class VosImageSmokeTest(unittest.TestCase):
    def test_dry_run_uses_amd_gpu_runtime(self):
        command = smoke.ssh_command(
            "czy@tc232", "registry.example/v-voice:amd", "amd-cuda"
        )
        self.assertIn("bash -s", command)
        self.assertIn("--gpus all", command)

    def test_dry_run_uses_nvidia_runtime_for_jetson_profiles(self):
        for profile in ("l4t", "thor"):
            with self.subTest(profile=profile):
                command = smoke.ssh_command(
                    "czy@device", "registry.example/v-voice:" + profile, profile
                )
                self.assertIn("bash -s", command)
                self.assertIn("--runtime nvidia", command)

    def test_profiles_select_expected_cuda_family(self):
        self.assertEqual(smoke.PROFILES["amd-cuda"]["architecture"], "amd64")
        self.assertFalse(smoke.PROFILES["amd-cuda"]["requires_onnx_cuda"])
        self.assertEqual(smoke.PROFILES["l4t"]["architecture"], "arm64")
        self.assertTrue(smoke.PROFILES["l4t"]["requires_onnx_cuda"])
        self.assertEqual(smoke.PROFILES["thor"]["sherpa_suffix"], "+cuda13")
        self.assertTrue(smoke.PROFILES["thor"]["requires_onnx_cuda"])

    def test_dry_run_can_pin_the_source_catalog(self):
        digest = "a" * 64
        command = smoke.ssh_command(
            "czy@device",
            "registry.example/v-voice:l4t",
            "l4t",
            digest,
        )
        self.assertIn(digest, command)
        self.assertIn("catalog_sha256", command)

    def test_sha256_argument_rejects_invalid_digests(self):
        self.assertEqual(smoke.sha256_argument("A" * 64), "a" * 64)
        for value in ("a" * 63, "g" * 64):
            with self.subTest(value=value), self.assertRaises(
                argparse.ArgumentTypeError
            ):
                smoke.sha256_argument(value)


if __name__ == "__main__":
    unittest.main()
