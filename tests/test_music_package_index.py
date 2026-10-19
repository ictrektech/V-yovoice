"""音乐安装器不得继承基础镜像已失效的 pip 索引。"""
import os
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which('bash') is None, reason='bash build script')
@pytest.mark.parametrize('override', ['', 'https://approved.example/simple'])
def test_music_installer_isolates_inherited_pip_configuration(tmp_path, override):
    python = tmp_path / 'python3'
    python.write_text('#!/bin/sh\nprintf "%s|%s|%s|%s\\n" "$PIP_INDEX_URL" "$PIP_EXTRA_INDEX_URL" "$PIP_CONFIG_FILE" "$*"\nexit 77\n')
    python.chmod(0o755)
    env = {**os.environ, 'PATH': str(tmp_path) + os.pathsep + os.environ['PATH'],
           'PIP_INDEX_URL': 'https://obsolete.example/jetson',
           'PIP_EXTRA_INDEX_URL': 'https://obsolete.example/extra',
           'PIP_CONFIG_FILE': '/obsolete/pip.conf', 'VVOICE_MUSIC_PIP_INDEX_URL': override}
    installer = Path(__file__).resolve().parents[1] / 'docker/install_music_runtime.sh'
    result = subprocess.run(['bash', str(installer)], env=env, capture_output=True, text=True)
    assert result.returncode == 77
    index, extra, config, arguments = result.stdout.strip().split('|')
    expected = override or 'https://pypi.tuna.tsinghua.edu.cn/simple'
    assert index == expected
    assert extra == '' and config == '/dev/null'
    assert '--index-url ' + expected in arguments
