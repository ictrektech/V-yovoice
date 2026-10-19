"""显式 CPU 模型列表应覆盖每种语音模型工厂。"""
from types import SimpleNamespace

import pytest

from vvoice import runtime


@pytest.mark.parametrize('kind,pinned', [('asr', True), ('tts', True), ('speaker', True),
                                        ('asr', False), ('tts', False), ('speaker', False)])
def test_cpu_model_pin_reaches_native_factory(monkeypatch, kind, pinned):
    key = 'fixture-' + kind
    monkeypatch.setattr(runtime, 'settings', SimpleNamespace(cpu_models=(key,) if pinned else (),
                                                         num_threads=4, max_loaded_models=2))
    monkeypatch.setattr(runtime, 'detect_provider', lambda: 'cuda')
    descriptor = {'key': key, 'runtime': {'family': 'vits', 'factory': 'from_sense_voice'}}
    monkeypatch.setattr(runtime, 'find_model', lambda *_: descriptor)
    monkeypatch.setattr(runtime, 'resolve_files', lambda *_: {'model': '/fixture.onnx'})
    def config(**kwargs):
        return SimpleNamespace(validate=lambda: True, **kwargs)
    sherpa = SimpleNamespace(OfflineRecognizer=SimpleNamespace(from_sense_voice=config),
                             OfflineTtsVitsModelConfig=config, OfflineTtsModelConfig=config,
                             OfflineTtsConfig=config, OfflineTts=lambda value: value,
                             SpeakerEmbeddingExtractorConfig=config,
                             SpeakerEmbeddingExtractor=lambda value: value)
    monkeypatch.setattr(runtime, '_sherpa', lambda: sherpa)
    registry = runtime.RuntimeRegistry(max_concurrent=1, max_concurrent_per_model=1)
    value = getattr(registry, kind)(key)
    actual = value.model.provider if kind == 'tts' else value.provider
    assert actual == ('cpu' if pinned else 'cuda')
