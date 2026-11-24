"""构建预览只输出计划，不能下载、编译、推送或写入飞书。"""
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "docker/build_image.sh"


class BuildImageDryRunTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        commands = self.root / "commands"
        commands.mkdir()
        for name in ("dirname", "tr"):
            (commands / name).symlink_to(shutil.which(name))
        for name, value in (("uname", '"$VVOICE_TEST_ARCH"'), ("date", "20261026")):
            tool = commands / name
            tool.write_text(f'#!/bin/bash\nprintf "%s\\n" {value}\n')
            tool.chmod(0o755)
        self.log = self.root / "unexpected-commands"
        for name in ("docker", "go", "npx", "npm", "rsync", "curl", "python3",
                     "mkdir", "mv", "sha256sum", "bash"):
            tool = commands / name
            tool.write_text('#!/bin/bash\nprintf "%s\\n" "$0" >> "$VVOICE_TEST_LOG"\nexit 97\n')
            tool.chmod(0o755)
        self.build_root = self.root / "build output"
        self.env = {**os.environ, "PATH": str(commands), "VVOICE_TEST_ARCH": "aarch64",
                    "VVOICE_TEST_LOG": str(self.log), "VVOICE_BUILD_ROOT": str(self.build_root),
                    "REGISTRY": "registry.example.test/team", "VVOICE_STUDIO_BASE_IMAGE": ""}

    def preview(self, *args, arch="aarch64", default_version=False, **overrides):
        if not default_version and "--version" not in args:
            args = (*args, "--version", "1.2.3")
        result = subprocess.run(
            ["/bin/bash", str(SCRIPT), *args], cwd=self.root,
            env={**self.env, "VVOICE_TEST_ARCH": arch, **overrides},
            text=True, capture_output=True, timeout=5,
        )
        self.assertFalse(self.log.exists(), self.log.read_text() if self.log.exists() else "")
        self.assertFalse(self.build_root.exists())
        return result

    def test_profiles_without_external_commands(self):
        for sheet, arch, prefix, cuda, speech_cuda, speech_architectures, audio_architectures in [
            ("AMD_with_mxn100", "x86_64", "amd", "OFF", "OFF", "", ""),
            ("AMD_with_cuda", "x86_64", "amd_cu128", "ON", "ON", "80-real;86-real;89-real;90-real", ""),
            ("ARM_without_cuda", "aarch64", "arm", "OFF", "OFF", "", ""),
            ("SOPHON_bm1688", "arm64", "arm", "OFF", "OFF", "", ""),
            ("ARM_with_cuda", "aarch64", "arm_cu130", "ON", "OFF", "", ""),
            ("l4t", "aarch64", "l4t", "ON", "ON", "87-real", "87-real"),
            ("thor_spark", "aarch64", "thor", "ON", "ON", "110-real", "110-real"),
        ]:
            with self.subTest(sheet=sheet):
                result = self.preview("--sheet", sheet, "--dry-run", arch=arch)
                self.assertEqual(result.returncode, 0, result.stderr)
                image = f"registry.example.test/team/v-voice:{prefix}_1.2.3"
                self.assertIn(f"IMAGE={image}", result.stdout)
                self.assertIn(f"CUDA={cuda}", result.stdout)
                self.assertIn(
                    f"AUDIOCPP_CUDA_ARCHITECTURES={audio_architectures}",
                    result.stdout,
                )
                self.assertIn(f"SPEECCPP_CUDA={speech_cuda}", result.stdout)
                self.assertIn(
                    f"SPEECCPP_CUDA_ARCHITECTURES={speech_architectures}",
                    result.stdout,
                )
                self.assertIn(f"docker push {image}", result.stdout)
                self.assertIn(f"FEISHU_SHEETS={sheet}", result.stdout)
                self.assertEqual("FEISHU_SHEETS=SOPHON_bm1688" in result.stdout,
                                 sheet in {"ARM_without_cuda", "SOPHON_bm1688"})

    def test_selected_steps(self):
        for mode, prepare, build, publish in [
            ([], True, True, True),
            (["--build-only"], True, True, False),
            (["--publish-only", "--version", "1.2.3"], False, False, True),
            (["--prepare-only"], True, False, False),
            (["--assets-only"], False, False, False),
            (["--application-only"], False, False, False),
            (["--build-only", "--reuse-prepared-artifacts"], False, True, False),
        ]:
            with self.subTest(mode=mode):
                result = self.preview("--dry-run", "--sheet", "l4t", *mode)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual("准备 Go 服务" in result.stdout, prepare)
                self.assertEqual("构建基础语音服务" in result.stdout, build)
                self.assertEqual("docker push" in result.stdout, publish)
                self.assertEqual("FEISHU_SHEETS=" in result.stdout, publish)
                if "--assets-only" in mode:
                    self.assertIn("更新前端资产", result.stdout)
                if "--application-only" in mode:
                    self.assertIn("实际构建时必须提供 VVOICE_STUDIO_BASE_IMAGE", result.stdout)
                if "--reuse-prepared-artifacts" in mode:
                    self.assertIn("复用已准备的构建产物", result.stdout)

    def test_application_base_image(self):
        image = "registry.example.test/team/v-voice:l4t_verified"
        result = self.preview("--sheet", "l4t", "--application-only", "--dry-run",
                              VVOICE_STUDIO_BASE_IMAGE=image)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"基于 {image} 更新应用代码", result.stdout)

    def test_default_version_and_publish_requires_explicit_version(self):
        version = (SCRIPT.parents[1] / "ictrek.app/VERSION").read_text().strip().split(".")
        version[-1] = str(int(version[-1]) + 1)
        result = self.preview("--sheet", "l4t", "--dry-run", default_version=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"IMAGE=registry.example.test/team/v-voice:l4t_{'.'.join(version)}", result.stdout)
        result = self.preview("--sheet", "l4t", "--publish-only", "--dry-run", default_version=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires the same explicit --version", result.stderr)

    def test_invalid_arguments(self):
        for args, arch in [
            (["--dry-run"], "aarch64"),
            (["--sheet", "unknown", "--dry-run"], "aarch64"),
            (["--sheet", "AMD_with_cuda", "--dry-run"], "aarch64"),
            (["--sheet", "l4t", "--dry-run"], "riscv64"),
            (["--sheet", "l4t", "--dry-run", "--unknown"], "aarch64"),
        ]:
            with self.subTest(args=args, arch=arch):
                self.assertNotEqual(self.preview(*args, arch=arch).returncode, 0)


class BuildImageIncrementalTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.commands = self.root / "commands"
        self.commands.mkdir()
        uname = self.commands / "uname"
        uname.write_text('#!/bin/bash\nprintf "aarch64\\n"\n')
        uname.chmod(0o755)
        self.log = self.root / "docker.log"
        docker = self.commands / "docker"
        docker.write_text(
            '#!/bin/bash\n'
            'printf "%s\\n" "$*" >> "$VVOICE_TEST_LOG"\n'
            'if [[ "$1" == image && "$2" == inspect ]]; then\n'
            '  printf "sha256:incremental\\n"\n'
            'fi\n',
        )
        docker.chmod(0o755)
        self.build_root = self.root / "build"
        artifacts = self.build_root / "artifacts"
        for path in (artifacts / "web/index.html", artifacts / "frontend/index.html",
                     artifacts / "linux-arm64/vvoice-studio"):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("artifact")
        self.target = "registry.example.test/team/v-voice:l4t_1.2.3"
        self.env = {
            **os.environ,
            "PATH": f"{self.commands}:{os.environ['PATH']}",
            "VVOICE_TEST_LOG": str(self.log),
            "VVOICE_BUILD_ROOT": str(self.build_root),
            "VVOICE_STUDIO_BASE_IMAGE": self.target,
            "REGISTRY": "registry.example.test/team",
        }

    def test_incremental_build_uses_temporary_tag_then_retags_target(self):
        expected_build = self.target + "-incremental"
        for mode in ("--assets-only", "--application-only"):
            with self.subTest(mode=mode):
                self.log.unlink(missing_ok=True)
                result = subprocess.run(
                    ["/bin/bash", str(SCRIPT), "--sheet", "l4t", "--version", "1.2.3", mode],
                    cwd=self.root, env=self.env, text=True, capture_output=True, timeout=5,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                calls = [shlex.split(line) for line in self.log.read_text().splitlines()]
                build_index = next(index for index, args in enumerate(calls) if args[:1] == ["buildx"])
                build = calls[build_index]
                self.assertEqual(build[build.index("-t") + 1], expected_build)
                self.assertIn(f"VVOICE_STUDIO_BASE_IMAGE={self.target}", build)
                tag_index = calls.index(["tag", expected_build, self.target])
                self.assertLess(build_index, tag_index)
                self.assertIn(
                    ["image", "inspect", "--format", "{{.Id}}", self.target],
                    calls[tag_index + 1:],
                )


if __name__ == "__main__":
    unittest.main()
