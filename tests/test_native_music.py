"""音乐迁移契约：保留模型、参数和格式，绝不绕过统一调度。"""
import io
from pathlib import Path
from types import SimpleNamespace
from types import ModuleType
import sys

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from vvoice import music, music_catalog
from vvoice.admission import AdmissionMiddleware

app = FastAPI()
app.include_router(music.router)
client = TestClient(app)


def test_all_original_models_keep_modelscope_repositories_and_pinned_files():
    rows = music_catalog.catalog()
    assert {row['key'] for row in rows} == {'ace-step-1.5-turbo', 'stable-audio-3-small-music', 'stable-audio-3-medium', 'musicgen-small'}
    for row in rows:
        assert row['modelscope_repo'] == 'vivibit/v-music-' + row['key']
        assert row['backend'] == 'pytorch'
        assert row['runtime']['adapter']
        assert row['size'] > 0
        assert row['shared_files']
        assert set(row['required_files']).issubset({file['path'] for file in row['shared_files']})
        for file in row['shared_files']:
            assert not Path(file['path']).is_absolute() and '..' not in Path(file['path']).parts
            assert len(file['sha256']) == 64 and file['size'] >= 0


@pytest.mark.parametrize('fmt,signature', [('wav', b'RIFF'), ('flac', b'fLaC')])
def test_public_music_api_preserves_parameters_and_binary_format(monkeypatch, fmt, signature):
    monkeypatch.delenv('VVOICE_SCHEDULER_REQUIRED', raising=False)
    monkeypatch.setattr(music, 'detect_provider', lambda: 'cuda')
    captured = {}

    async def admit(model):
        captured['admitted'] = model

    def generate(request):
        captured.update(request.model_dump())
        return signature + b'test-fixture'

    monkeypatch.setattr(music, 'admit_model', admit)
    monkeypatch.setattr(music.runtime, 'generate', generate)
    payload = dict(model='stable-audio-3-small-music', prompt='quiet piano', duration=10, negative_prompt='speech', seed=42, bpm=80, key='C major', time_signature='4/4', instrumental=False, response_format=fmt)
    response = client.post('/v1/audio/music/generations', json=payload)
    assert response.status_code == 200 and response.content.startswith(signature)
    assert response.headers['content-type'] == 'audio/' + fmt
    assert response.headers['cache-control'] == 'no-store'
    assert captured == {**payload, 'admitted': payload['model']}


@pytest.mark.parametrize('payload,status', [({'model': 'missing'}, 404), ({'model': 'musicgen-small', 'duration': 31}, 422), ({'prompt': ' '}, 422), ({'bpm': 0}, 422)])
def test_invalid_requests_never_acquire_compute(monkeypatch, payload, status):
    monkeypatch.setattr(music, 'detect_provider', lambda: 'cuda')
    async def forbidden(_):
        raise AssertionError('invalid request acquired a permit')
    monkeypatch.setattr(music, 'admit_model', forbidden)
    response = client.post('/v1/audio/music/generations', json={**dict(model='stable-audio-3-small-music', prompt='quiet piano', duration=10), **payload})
    assert response.status_code == status


def test_music_requires_own_calibration_before_compute(monkeypatch):
    monkeypatch.setenv('VVOICE_SCHEDULER_REQUIRED', 'true')
    monkeypatch.setattr(music, 'detect_provider', lambda: 'cuda')
    monkeypatch.setattr(music, 'configuration', lambda: {'input_limits_version': 1, 'execution_settings': {'music': {'runtime': 'foreign-v-music'}}})
    with pytest.raises(HTTPException) as rejected:
        music.validate_request(music.MusicRequest(model='musicgen-small', prompt='piano'))
    assert rejected.value.status_code == 503


def test_music_json_upload_is_bounded_before_permit(monkeypatch):
    monkeypatch.setenv('VVOICE_SCHEDULER_REQUIRED', 'true')
    isolated = FastAPI()
    isolated.include_router(music.router)
    isolated.add_middleware(AdmissionMiddleware)
    response = TestClient(isolated).post('/v1/audio/music/generations', json={'model': 'musicgen-small', 'prompt': 'x' * 70000})
    assert response.status_code == 413


def test_administrator_required_for_all_native_management_actions():
    for action in ('pull', 'stop', 'unload'):
        assert client.post('/api/v1/music-models/musicgen-small/' + action).status_code == 401


def test_management_forwards_to_scheduler_repository(monkeypatch):
    async def admin(_): pass
    called = []
    async def pull(key, force): called.append((key, force)); return {'status': 'queued'}
    monkeypatch.setattr(music, 'administrator', admin)
    monkeypatch.setattr(music, 'pull_model', pull)
    response = client.post('/api/v1/music-models/musicgen-small/pull')
    assert response.status_code == 200 and called == [('musicgen-small', False)]


def test_missing_weights_never_start_torch(monkeypatch):
    monkeypatch.setattr(music, 'model_files_ready', lambda _: (False, 'incomplete'))
    runtime = music.MusicRuntime()
    with pytest.raises(HTTPException):
        runtime.generate(music.MusicRequest(model='musicgen-small', prompt='piano'))
    assert not runtime.loaded('musicgen-small') and not runtime.gate.locked()


def test_lease_loss_kills_and_waits_for_music_process_before_return(monkeypatch):
    monkeypatch.setattr(music, 'model_files_ready', lambda _: (True, ''))
    stopped = []
    class Process:
        stdin = io.BytesIO()
        returncode = None
        def poll(self): return self.returncode
    process = Process()
    monkeypatch.setattr(music.subprocess, 'Popen', lambda *args, **kwargs: process)
    runtime = music.MusicRuntime()
    def stop(child):
        assert child is process
        stopped.append(True)
        child.returncode = -9
    monkeypatch.setattr(runtime, 'kill', stop)
    token = music.current.set(SimpleNamespace(failed=True))
    try:
        with pytest.raises(HTTPException) as rejected:
            runtime.generate(music.MusicRequest(model='musicgen-small', prompt='piano'))
        assert rejected.value.status_code == 503
        assert stopped == [True] and not runtime.gate.locked()
        assert not runtime.loaded('musicgen-small')
    finally:
        music.current.reset(token)


def test_ace_runtime_only_updates_private_code_view(monkeypatch, tmp_path):
    from vvoice import music_runtime
    root = tmp_path / 'shared'
    model = root / 'acestep-v15-turbo'
    model.mkdir(parents=True)
    (model / 'model.safetensors').write_bytes(b'weight-fixture')
    (model / 'config.json').write_text('{}')
    (model / 'modeling.py').write_text('shared-code-must-not-change')
    item = {'shared_files': [{'path': 'acestep-v15-turbo/model.safetensors'}, {'path': 'acestep-v15-turbo/config.json'}]}
    monkeypatch.setattr(music_runtime, 'find_model', lambda _: item)
    monkeypatch.setattr(music_runtime, 'model_root', lambda _: root)
    downloader, handler_module = ModuleType('acestep.model_downloader'), ModuleType('acestep.handler')
    def sync(name, checkpoint):
        assert checkpoint != root
        (checkpoint / name / 'modeling.py').write_text('fixed-runtime-code')
    class Handler:
        def initialize_service(self, **kwargs):
            view = Path(music_runtime.os.environ['ACESTEP_CHECKPOINTS_DIR'])
            assert (view / 'acestep-v15-turbo/model.safetensors').is_symlink()
            assert (view / 'acestep-v15-turbo/modeling.py').read_text() == 'fixed-runtime-code'
            (view / 'acestep-v15-turbo/config.json').write_text('{"private":true}')
            return 'ready', True
    downloader._sync_model_code_files = sync
    handler_module.AceStepHandler = Handler
    monkeypatch.setitem(sys.modules, 'acestep', ModuleType('acestep'))
    monkeypatch.setitem(sys.modules, 'acestep.model_downloader', downloader)
    monkeypatch.setitem(sys.modules, 'acestep.handler', handler_module)
    monkeypatch.setenv('ACESTEP_CHECKPOINTS_DIR', '')
    handler, _ = music_runtime.RuntimeRegistry().ace_step('ace-step-1.5-turbo')
    assert (model / 'config.json').read_text() == '{}'
    assert (model / 'modeling.py').read_text() == 'shared-code-must-not-change'
    handler._vvoice_checkpoint_view.cleanup()
