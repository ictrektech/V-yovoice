"""大模型不应先分配 CUDA FP32 权重，再降到最终 FP16 精度。"""
import json
import sys
from types import ModuleType, SimpleNamespace

import pytest

from vvoice import music_runtime


@pytest.mark.parametrize('device', ['cpu', 'cuda'])
def test_stable_audio_casts_on_cpu_before_cuda_transfer(monkeypatch, tmp_path, device):
    events = []

    class Model:
        half = False

        def to(self, target):
            events.append(target)
            if target == 'cuda' and not self.half:
                raise AssertionError('temporary FP32 CUDA allocation before FP16 conversion')
            if target == 'float16':
                self.half = True
            return self

        def eval(self):
            return self

        def requires_grad_(self, enabled):
            assert not enabled
            return self

    model = Model()
    (tmp_path / 'model_config.json').write_text(json.dumps({'model': {}}))
    (tmp_path / 'model.safetensors').touch()
    monkeypatch.setattr(music_runtime, 'find_model', lambda _: {})
    monkeypatch.setattr(music_runtime, 'model_root', lambda _: tmp_path)
    monkeypatch.setattr(music_runtime, 'detect_provider', lambda: device)
    monkeypatch.setitem(sys.modules, 'torch', SimpleNamespace(
        float16='float16', cuda=SimpleNamespace(is_available=lambda: True)))

    def create(config):
        events.append('create')
        return model

    def copy(target, state):
        assert target is model and state == {'weights': 'verified-checkpoint'}
        events.append('copy')

    # 对照镜像固定版本的原始加载顺序，确保旧调用路径会暴露瞬态分配。
    def original_loader(config, path, device, model_half):
        target = create(config)
        copy(target, {'weights': 'verified-checkpoint'})
        target.to(device)
        if model_half:
            target.to('float16')
        return target

    modules = {
        'stable_audio_3': {},
        'stable_audio_3.factory': {'create_diffusion_cond_from_config': create},
        'stable_audio_3.loading_utils': {'load_diffusion_cond': original_loader, 'copy_state_dict': copy},
        'stable_audio_3.model': {'StableAudioModel': lambda target, *_: target},
        'safetensors': {},
        'safetensors.torch': {'load_file': lambda _: {'weights': 'verified-checkpoint'}},
    }
    for name, attributes in modules.items():
        module = ModuleType(name)
        module.__dict__.update(attributes)
        monkeypatch.setitem(sys.modules, name, module)
    assert music_runtime.RuntimeRegistry().stable_audio('fixture') is model
    assert events == ['create', 'copy'] + (['float16', 'cuda'] if device == 'cuda' else ['cpu'])
