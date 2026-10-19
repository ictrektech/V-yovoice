"""音乐运行时使用独立线程参数，不改变现有 ONNX/audio.cpp 配置。"""
import os
from dataclasses import dataclass
from .config import settings as voice_settings


@dataclass(frozen=True)
class MusicSettings:
    provider: str = voice_settings.provider
    torch_threads: int = max(1, int(os.getenv('VVOICE_MUSIC_TORCH_THREADS', '4')))
    torch_interop_threads: int = max(1, int(os.getenv('VVOICE_MUSIC_TORCH_INTEROP_THREADS', '1')))
    max_loaded_models: int = 1
    max_concurrent_jobs: int = 1


settings = MusicSettings()
# 仅音乐子进程导入此模块；不覆盖父进程的 ONNX 线程设置。
for variable in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS'):
    os.environ[variable] = str(settings.torch_threads)
