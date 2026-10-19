#!/usr/bin/env python3
"""外层真实许可覆盖的隔离 CPU 语音测量；不开放业务 API，不自行批准预算。"""
import json
import os
from pathlib import Path
import resource
import time


def main():
    if os.getenv('VVOICE_EXTERNAL_CALIBRATION_PERMIT') != 'active':
        raise SystemExit('Outer Scheduler calibration permit required')
    if os.getenv('VVOICE_SCHEDULER_REQUIRED') != 'false':
        raise SystemExit('Use an isolated native worker, not the production API process')
    import numpy as np
    import soundfile as sf
    from vvoice.config import settings
    from vvoice.runtime import _model_provider, registry, synthesize, transcribe
    from vvoice import runtime
    from vvoice.catalog import find_model, model_files_ready
    models = ('kokoro-multilang', 'sensevoice-int8', 'paraformer-zh')
    assert all(_model_provider(model) == 'cpu' for model in models), 'CPU model configuration mismatch'
    # 只观察实际传给原生工厂的参数，不重写 provider，不替换真实推理。
    native = runtime._sherpa()
    native_providers = []
    class RecognizerFactories:
        def __getattr__(self, name):
            original = getattr(native.OfflineRecognizer, name)
            def create(**kwargs):
                assert kwargs.get('provider') == 'cpu', 'ASR native factory is not CPU'
                native_providers.append(dict(factory=name, provider=kwargs['provider']))
                return original(**kwargs)
            return create
    class NativeProxy:
        OfflineRecognizer = RecognizerFactories()
        def OfflineTts(self, config):
            assert config.model.provider == 'cpu', 'TTS native factory is not CPU'
            native_providers.append(dict(factory='OfflineTts', provider=config.model.provider))
            return native.OfflineTts(config)
        def __getattr__(self, name):
            return getattr(native, name)
    proxy = NativeProxy()
    runtime._sherpa = lambda: proxy
    for model in models:
        ready, reason = model_files_ready(find_model(model))
        assert ready, model + ': ' + reason
    root = Path('/data')
    assert root.is_dir() and not (root / 'calibration-result.json').exists(), 'Fresh private output required'
    readings = []
    def measure(phase, round_number):
        available = next(int(line.split()[1]) * 1024 for line in Path('/proc/meminfo').read_text().splitlines()
                         if line.startswith('MemAvailable:'))
        rss = int(Path('/proc/self/statm').read_text().split()[1]) * os.sysconf('SC_PAGE_SIZE')
        readings.append(dict(phase=phase, round=round_number, rss_bytes=rss, host_available_bytes=available))
    started = time.monotonic()
    text = ('Hello, this is a speech synthesis calibration test. ' * 20)[:512]
    (root / 'native-started').touch()
    outputs = []
    for round_number in range(1, 4):
        measure('before_load', round_number)
        audio, rate = synthesize(models[0], text, 'default', 1.0, 'en')
        assert len(audio) and rate > 0
        sf.write(root / f'cpu-voice-{round_number}.wav', audio, rate, subtype='PCM_16')
        frames = len(audio)
        samples = np.tile(audio, max(1, int(np.ceil(20 * rate / len(audio)))))[:20 * rate].copy()
        del audio
        measure('after_tts', round_number)
        registry.unload(models[0])
        measure('after_tts_unload', round_number)
        for model in models[1:]:
            result = transcribe(model, samples, rate)
            assert result.get('text'), model + ': empty ASR output'
            measure('after_' + model, round_number)
            registry.unload(model)
            measure('after_' + model + '_unload', round_number)
        del samples
        registry.unload()
        assert not any(registry.is_loaded(model) for model in models)
        measure('after_all_unload', round_number)
        outputs.append(dict(round=round_number, tts_frames=frames, tts_sample_rate=rate,
                            asr_nonempty=True, asr_duration_seconds=20))
    assert len(native_providers) == 9, 'Expected three real native model loads per round'
    result = dict(models=list(models), inputs=dict(tts_characters=len(text), tts_speed=1.0,
                  asr_duration_seconds=20, observed_concurrency=1), output=outputs,
                  profile=settings.profile, provider=settings.provider, cpu_models=list(settings.cpu_models),
                  effective_providers={model: _model_provider(model) for model in models},
                  native_factory_providers=native_providers,
                  rss_baseline_phase='native_library_imported_before_model_load',
                  num_threads=settings.num_threads, max_loaded_models=settings.max_loaded_models,
                  max_concurrent_inference=settings.max_concurrent_inference,
                  readings=readings, runtime_unloaded=True,
                  process_max_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                  seconds=time.monotonic() - started,
                  note='Heap reclamation is best effort, not process/GPU stop evidence; outer owner must confirm container exit.')
    temporary = root / 'calibration-result.tmp'
    temporary.write_text(json.dumps(result))
    temporary.chmod(0o600)
    temporary.replace(root / 'calibration-result.json')
    deadline = time.monotonic() + 60
    while not (root / 'stop').exists() and time.monotonic() < deadline:
        time.sleep(0.2)


if __name__ == '__main__':
    main()
