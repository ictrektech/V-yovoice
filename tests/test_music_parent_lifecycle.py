"""容器 PID 1 可以是合法宿主；父进程变化仍必须拒绝。"""
import io
from types import ModuleType, SimpleNamespace

import pytest

from vvoice import music_worker


def prepare(monkeypatch, tmp_path, parents, prctl=0):
    output = tmp_path / 'test.wav'
    values = iter(parents)
    monkeypatch.setattr(music_worker.sys, 'platform', 'linux')
    monkeypatch.setattr(music_worker.os, 'getppid', lambda: next(values))
    monkeypatch.setattr(music_worker.ctypes, 'CDLL', lambda _: SimpleNamespace(prctl=lambda *_: prctl))
    monkeypatch.setattr(music_worker.sys, 'argv', ['worker', str(output)])
    monkeypatch.setattr(music_worker.sys, 'stdin', io.StringIO('{"model":"test"}'))
    runtime = ModuleType('vvoice.music_runtime')
    runtime.generate_music = lambda *_args, **_kwargs: (b'test-only-audio-fixture', 'audio/wav')
    monkeypatch.setitem(music_worker.sys.modules, 'vvoice.music_runtime', runtime)
    return output


@pytest.mark.parametrize('parent', [1, 123])
def test_stable_parent_can_be_container_init(monkeypatch, tmp_path, parent):
    output = prepare(monkeypatch, tmp_path, [parent, parent])
    music_worker.main()
    assert output.read_bytes() == b'test-only-audio-fixture'


@pytest.mark.parametrize('parents,prctl', [([123, 1], 0), ([1, 2], 0), ([1], -1)])
def test_changed_parent_or_failed_death_signal_is_rejected(monkeypatch, tmp_path, parents, prctl):
    output = prepare(monkeypatch, tmp_path, parents, prctl)
    with pytest.raises(SystemExit, match='parent process unavailable'):
        music_worker.main()
    assert not output.exists()
