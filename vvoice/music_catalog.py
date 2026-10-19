"""保留 V-Music 模型 ID 和共享导出路径，区分原生权重与 GGUF。"""
import json
from functools import lru_cache
from pathlib import Path
from .config import settings


@lru_cache(maxsize=1)
def catalog() -> list[dict]:
    path = Path(__file__).resolve().parents[1] / 'catalog/music-models.json'
    rows = json.loads(path.read_text())['models']
    for row in rows:
        row['runtime'] = {**row['runtime'], 'family': 'native_music',
                          'files': {str(i): f['path'] for i, f in enumerate(row['shared_files'])}}
        row['size'] = sum(f['size'] for f in row['shared_files'])
        row['import_required'] = False
    return rows


def find_model(key: str) -> dict:
    for row in catalog():
        if row['key'] == key:
            return row
    raise KeyError(key)


def model_root(item: dict) -> Path:
    return settings.modelhub_root / 'export/ms' / item['modelscope_repo'] / 'current'


def runtime_settings() -> dict:
    import os
    return {'provider': settings.provider,
            'torch_threads': max(1, int(os.getenv('VVOICE_MUSIC_TORCH_THREADS', '4'))),
            'torch_interop_threads': max(1, int(os.getenv('VVOICE_MUSIC_TORCH_INTEROP_THREADS', '1'))),
            'max_concurrent_jobs': 1, 'max_loaded_models': 1,
            'steps': 8, 'runtime': 'pytorch-music-v1'}


def supported(item: dict, provider: str) -> bool:
    return provider in item['accelerators']
