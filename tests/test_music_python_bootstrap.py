"""旧 CUDA 语音环境不应被升级；音乐单独选择支持的 Python。"""
import os
from pathlib import Path
import subprocess

import pytest


@pytest.mark.parametrize('supported', [True, False])
def test_music_selects_supported_python_before_installing_packages(tmp_path, supported):
    python = tmp_path / 'python3'
    python.write_text('#!/bin/sh\nif [ "$1" = "-c" ]; then exit ' + ('0' if supported else '1') + '; fi\necho MAIN_PYTHON_PIP\nexit 77\n')
    python.chmod(0o755)
    curl = tmp_path / 'curl'
    curl.write_text('#!/bin/sh\necho "BOOTSTRAP_DOWNLOAD $*"\nexit 78\n')
    curl.chmod(0o755)
    uname = tmp_path / 'uname'
    uname.write_text('#!/bin/sh\necho x86_64\n')
    uname.chmod(0o755)
    env = {**os.environ, 'PATH': str(tmp_path) + os.pathsep + os.environ['PATH'],
           'VVOICE_PROVIDER': 'cuda'}
    installer = Path(__file__).resolve().parents[1] / 'docker/install_music_runtime.sh'
    result = subprocess.run(['bash', str(installer)], env=env, capture_output=True, text=True)
    assert result.returncode == (77 if supported else 78), result.stdout + result.stderr
    assert ('MAIN_PYTHON_PIP' in result.stdout) is supported
    if not supported:
        assert 'cpython-3.12.15%2B20261013-x86_64-unknown-linux-gnu-install_only.tar.gz' in result.stdout
