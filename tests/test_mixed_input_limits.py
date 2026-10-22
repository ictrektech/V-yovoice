"""混合审批必须保留旧接口，同时不放宽新模型的有界校准。"""
import copy
import io
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf
from fastapi import HTTPException
from fastapi.testclient import TestClient

from vvoice import admission, main, runtime


@pytest.fixture
def mixed(monkeypatch):
    legacy = ['kokoro-multilang', 'whisper-tiny',
              'speaker-campplus-zh-en', 'kokoro-82m-q8']
    config = {'url': 'http://scheduler.invalid/api/v1', 'token': 'x' * 32,
              'upstream_url': 'http://voice.invalid/v1', 'binding_revision': 1,
              'input_limits_version': 1, 'mixed_input_limits_version': 1,
              'models': {key: 'voice.infer' for key in [*legacy, 'sensevoice-int8']},
              'legacy_unbounded_models': legacy,
              'model_limits': {'sensevoice-int8': {'duration_seconds': 60,
                  'sample_rate': 24000, 'hotwords_characters': 0, 'input_bytes': 2097152}}}
    calls = []
    monkeypatch.setenv('VVOICE_SCHEDULER_REQUIRED', 'true')
    monkeypatch.setattr(admission, 'configuration', lambda: config)
    monkeypatch.setattr(admission.Execution, '_watch', lambda _: None)
    def controller(config, path, body, key=''):
        calls.append(path)
        return {'permit_id': 'fixture', 'state': 'active', 'lease_seconds': 30}
    monkeypatch.setattr(admission, 'controller', controller)
    return config, calls


def test_mixed_discovery_and_binding_document_declare_capability():
    assert main.scheduler_contract()['mixed_input_limits_version'] == 1
    properties = main.SchedulerBindingDocument.model_json_schema()['properties']
    assert {'mixed_input_limits_version', 'legacy_unbounded_models'} <= properties.keys()


def test_real_legacy_tts_validation_and_permit_survive_mixed_binding(mixed, monkeypatch):
    config, calls = mixed
    monkeypatch.setattr(runtime.registry, 'tts', lambda _: SimpleNamespace(
        generate=lambda *_: SimpleNamespace(samples=np.ones(1600, dtype=np.float32) * .1, sample_rate=16000)))
    monkeypatch.setattr(runtime, '_sherpa', lambda: SimpleNamespace(GenerationConfig=lambda: SimpleNamespace(extra={})))
    client = TestClient(admission.AdmissionMiddleware(main.app))
    response = client.post('/v1/audio/speech', json={'model': 'kokoro-multilang', 'input': 'Hello', 'response_format': 'wav'})
    assert response.status_code == 200, response.text
    assert response.content[:4] == b'RIFF'
    assert calls.count('/permits') == 1 and calls[-1].endswith('/release')


def test_legacy_large_audio_and_bounded_audio_use_their_own_limits(mixed, monkeypatch):
    config, calls = mixed
    config['legacy_unbounded_models'].append('sensevoice-int8')
    config['legacy_unbounded_models'].remove('kokoro-multilang')
    config['model_limits'] = {'kokoro-multilang': {'text_characters': 512, 'speed_min': 1, 'speed_max': 1}}
    monkeypatch.setattr(runtime, 'needs_split', lambda *_: False)
    monkeypatch.setattr(runtime, '_decode_segment', lambda *_: {'text': 'fixture'})
    source = io.BytesIO()
    sf.write(source, np.zeros(40 * 16000), 16000, format='WAV', subtype='PCM_16')
    assert len(source.getvalue()) > 1048576 + 65536
    client = TestClient(admission.AdmissionMiddleware(main.app))
    def transcribe():
        return client.post('/v1/audio/transcriptions', data={'model': 'sensevoice-int8'},
                           files={'file': ('audio.wav', source.getvalue(), 'audio/wav')})
    assert transcribe().status_code == 200
    assert calls.count('/permits') == 1
    calls.clear()
    config['legacy_unbounded_models'].remove('sensevoice-int8')
    config['model_limits']['sensevoice-int8'] = {'duration_seconds': 20, 'sample_rate': 24000,
                                               'hotwords_characters': 0, 'input_bytes': 1048576}
    assert transcribe().status_code == 413
    assert not calls


def test_retired_native_music_has_no_route_or_permit(mixed):
    _, calls = mixed
    client = TestClient(admission.AdmissionMiddleware(main.app))
    response = client.post('/v1/audio/music/generations', json={'model': 'musicgen-small', 'prompt': 'x' * 513, 'duration': 30})
    assert response.status_code in {404, 405}
    assert not calls


@pytest.mark.parametrize('change', [
    lambda c: c.pop('mixed_input_limits_version'),
    lambda c: c.update(mixed_input_limits_version=2),
    lambda c: c.update(mixed_input_limits_version=True),
    lambda c: c.update(legacy_unbounded_models='kokoro-multilang'),
    lambda c: c['legacy_unbounded_models'].append('kokoro-multilang'),
    lambda c: c['legacy_unbounded_models'].append('missing'),
    lambda c: c['legacy_unbounded_models'].append('sensevoice-int8'),
    lambda c: c['legacy_unbounded_models'].remove('whisper-tiny'),
])
def test_malformed_mixed_snapshots_fail_closed(mixed, change):
    config, _ = mixed
    change(config)
    with pytest.raises(HTTPException) as error:
        admission.model_limits('kokoro-multilang')
    assert error.value.status_code == 503


def test_creator_alias_does_not_grant_unapproved_sync_executor(mixed):
    _, calls = mixed
    assert admission.model_limits('audiocpp-kokoro-82m-q8') is None
    with pytest.raises(HTTPException):
        admission.Execution({}).enter('audiocpp-kokoro-82m-q8')
    assert not calls


def test_legacy_validation_is_pinned_before_binding_rotation(mixed, monkeypatch):
    config, calls = mixed
    execution = admission.Execution({})
    token = admission.current.set(execution)
    try:
        admission.validate_inputs('kokoro-multilang', text_characters=513, speed=1)
        changed = copy.deepcopy(config)
        changed['binding_revision'] += 1
        monkeypatch.setattr(admission, 'configuration', lambda: changed)
        with pytest.raises(HTTPException):
            execution.enter('kokoro-multilang')
        assert not calls
    finally:
        admission.current.reset(token)
