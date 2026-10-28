#!/usr/bin/env python3
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class ImageVersionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'docker').mkdir()
        (self.root / 'ictrek.app').mkdir()
        (self.root / 'bin').mkdir()
        shutil.copy(Path(__file__).resolve().parents[1] / 'docker/build_image.sh', self.root / 'docker')
        (self.root / 'ictrek.app/VERSION').write_text('0.0.30\n')
        uname = self.root / 'bin/uname'
        uname.write_text('#!/bin/sh\necho x86_64\n')
        uname.chmod(0o755)

    def run_build(self, *args):
        return subprocess.run(
            ['bash', str(self.root / 'docker/build_image.sh'), '--sheet', 'AMD_with_cuda', *args, '--dry-run'],
            env={**os.environ, 'PATH': str(self.root / 'bin') + os.pathsep + os.environ['PATH']},
            capture_output=True, text=True,
        )

    def test_default_and_explicit_version(self):
        default = self.run_build()
        self.assertEqual(default.returncode, 0, default.stderr)
        self.assertIn(':amd_cu128_0.0.31', default.stdout)
        explicit = self.run_build('--version', '0.1.7', '--publish-only')
        self.assertEqual(explicit.returncode, 0, explicit.stderr)
        self.assertIn(':amd_cu128_0.1.7', explicit.stdout)

    def test_invalid_version_and_ambiguous_publish(self):
        for args in [('--version', '0.01.3'), ('--publish-only',)]:
            with self.subTest(args=args):
                self.assertNotEqual(self.run_build(*args).returncode, 0)
        (self.root / 'ictrek.app/VERSION').write_text('invalid')
        self.assertNotEqual(self.run_build().returncode, 0)


if __name__ == '__main__':
    unittest.main()
