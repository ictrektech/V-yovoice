"""移除仅支持 Torch 的能力，不修改已安装的模型和用户数据。"""
from pathlib import Path

from fastapi.testclient import TestClient

from vvoice import main
from vvoice.creative import models
from vvoice.modelhub import management_catalog


RETIRED = {'ace-step-1.5-turbo', 'stable-audio-3-small-music', 'stable-audio-3-medium', 'musicgen-small'}


def test_retired_music_is_not_advertised_or_managed():
    contract = main.scheduler_contract()
    assert not RETIRED & {row['id'] for row in contract['sync_models']}
    assert not RETIRED & {row['key'] for row in management_catalog()}
    assert 'music' not in contract.get('execution_settings', {})
    assert any(row['runtime']['family'] == 'audio_cpp' for row in models(include_non_speech=True))


def test_retired_endpoints_are_absent_from_routes_and_openapi():
    client = TestClient(main.app)
    assert client.post('/v1/audio/music/generations', json={}).status_code == 404
    assert client.get('/api/v1/music-models').status_code == 404
    assert '/v1/audio/music/generations' not in client.get('/openapi.json').json()['paths']


def test_final_runtime_does_not_inherit_torch_layers():
    root = Path(__file__).resolve().parents[1]
    studio = (root / 'docker/Dockerfile.studio').read_text()
    assert 'install_music_runtime' not in studio and 'VVOICE_MUSIC_PYTHON' not in studio
    for profile in ('thor', 'arm-cuda', 'l4t'):
        dockerfile = (root / f'docker/Dockerfile.{profile}').read_text()
        assert 'FROM ubuntu:24.04' in dockerfile
        assert 'COPY --from=cuda-runtime /cuda-runtime/' in dockerfile
        assert 'site-packages' not in dockerfile
