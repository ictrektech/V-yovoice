"""用真实原生堆构造卸载后 RSS 保留，不执行模型推理。"""
import json
import gc
import subprocess
import sys
import textwrap
import weakref

import pytest


@pytest.mark.skipif(sys.platform != 'linux', reason='Linux RSS/glibc evidence')
def test_unload_returns_free_native_heap_pages():
    script = textwrap.dedent('''
        import ctypes, json, os
        from pathlib import Path
        from vvoice.runtime import RuntimeRegistry
        libc = ctypes.CDLL(None)
        if not hasattr(libc, 'malloc_trim'):
            raise SystemExit(77)
        libc.malloc.argtypes = [ctypes.c_size_t]
        libc.malloc.restype = ctypes.c_void_p
        libc.free.argtypes = [ctypes.c_void_p]
        libc.mallopt(-4, 0)
        def rss():
            return int(Path('/proc/self/statm').read_text().split()[1]) * os.sysconf('SC_PAGE_SIZE')
        class NativeModel:
            def __init__(self):
                self.pointer = libc.malloc(64 * 1024 * 1024)
                assert self.pointer
                ctypes.memset(self.pointer, 1, 64 * 1024 * 1024)
            def __del__(self):
                libc.free(self.pointer)
        registry = RuntimeRegistry()
        baseline = rss()
        address = registry._cached('tts:fixture', NativeModel).pointer
        guard = libc.malloc(64 * 1024 * 1024)
        assert guard and guard > address
        ctypes.memset(guard, 1, 4096)
        loaded = rss()
        registry.unload('fixture')
        after = rss()
        libc.free(guard)
        print(json.dumps(dict(baseline=baseline, loaded=loaded, after=after)))
        assert loaded - baseline > 48 * 1024 * 1024
        assert after - baseline < 16 * 1024 * 1024, 'unload retained free native heap pages'
    ''')
    result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True, timeout=30)
    if result.returncode == 77:
        pytest.skip('glibc malloc_trim unavailable')
    assert result.returncode == 0, result.stdout + result.stderr
    evidence = json.loads(result.stdout)
    assert evidence['after'] < evidence['loaded']


@pytest.mark.parametrize('eviction', [False, True])
def test_unload_and_lru_collect_unreachable_cycles(monkeypatch, eviction):
    from vvoice import runtime
    from types import SimpleNamespace
    monkeypatch.setattr(runtime, 'settings', SimpleNamespace(max_loaded_models=1))
    registry = runtime.RuntimeRegistry(max_concurrent=1, max_concurrent_per_model=1)
    class CyclicModel:
        def __init__(self):
            self.cycle = self
    was_enabled = gc.isenabled()
    gc.disable()
    try:
        value = CyclicModel()
        reference = weakref.ref(value)
        registry._cached('tts:fixture', lambda: value)
        del value
        if eviction:
            registry._cached('tts:replacement', object)
        else:
            registry.unload('fixture')
        assert reference() is None, 'unloaded model cycle still owns native resources'
    finally:
        if was_enabled:
            gc.enable()
        gc.collect()


def test_unload_keeps_referenced_active_model_alive():
    from vvoice.runtime import RuntimeRegistry
    registry = RuntimeRegistry()
    class ActiveModel:
        pass
    value = ActiveModel()
    reference = weakref.ref(value)
    registry._cached('tts:fixture', lambda: value)
    registry.unload('fixture')
    assert reference() is value


def test_unload_is_best_effort_without_glibc_trim(monkeypatch):
    from vvoice import runtime
    def unavailable(_):
        raise OSError('no glibc trim')
    monkeypatch.setattr(runtime.ctypes, 'CDLL', unavailable)
    registry = runtime.RuntimeRegistry()
    registry._cached('tts:fixture', object)
    registry.unload('fixture')
    assert not registry.is_loaded('fixture')
