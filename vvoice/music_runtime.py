"""从 V-Music 迁入的原生音乐适配器；仅在隔离子进程中加载 Torch。"""
from __future__ import annotations

import gc
import io
import json
import os
import shutil
import threading
import tempfile
from collections import OrderedDict
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .music_catalog import find_model, model_root
from .music_config import settings


try:
    import torch
except ImportError:
    pass
else:
    torch.set_num_threads(settings.torch_threads)
    torch.set_num_interop_threads(settings.torch_interop_threads)


def detect_provider() -> str:
    if settings.provider != "auto":
        return settings.provider
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
    except ImportError:
        pass
    return "cpu"


class RuntimeRegistry:
    def __init__(self) -> None:
        self._items: OrderedDict[str, Any] = OrderedDict()
        self._lock = threading.RLock()
        self._global_gate = threading.BoundedSemaphore(settings.max_concurrent_jobs)
        self._model_gates: dict[str, threading.BoundedSemaphore] = {}

    @contextmanager
    def inference(self, key: str):
        with self._lock:
            gate = self._model_gates.setdefault(key, threading.BoundedSemaphore(1))
        with self._global_gate, gate:
            yield

    def is_loaded(self, key: str) -> bool:
        with self._lock:
            return key in self._items

    def unload(self, key: str) -> None:
        with self._lock:
            value = self._items.pop(key, None)
        del value
        self._release_memory()

    @staticmethod
    def _release_memory() -> None:
        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

    def _remember(self, key: str, value: Any) -> Any:
        evicted: list[Any] = []
        self._items[key] = value
        while len(self._items) > settings.max_loaded_models:
            _, old_value = self._items.popitem(last=False)
            evicted.append(old_value)
        if evicted:
            evicted.clear()
            del old_value
            self._release_memory()
        return value

    def _make_room(self, key: str) -> None:
        if key in self._items:
            return
        evicted: list[Any] = []
        while len(self._items) >= settings.max_loaded_models:
            _, old_value = self._items.popitem(last=False)
            evicted.append(old_value)
        if evicted:
            evicted.clear()
            del old_value
            self._release_memory()

    def stable_audio(self, key: str):
        with self._lock:
            if key in self._items:
                self._items.move_to_end(key)
                return self._items[key]

            self._make_room(key)

            item = find_model(key)
            root = model_root(item)
            config_path = root / "model_config.json"
            checkpoint_path = root / "model.safetensors"
            if not config_path.is_file() or not checkpoint_path.is_file():
                raise FileNotFoundError(f"model files are incomplete: {root}")

            import torch
            from stable_audio_3.loading_utils import load_diffusion_cond
            from stable_audio_3.model import StableAudioModel

            device = detect_provider()
            if device == "cuda" and not torch.cuda.is_available():
                raise RuntimeError("CUDA was requested but is not available")

            model_config = json.loads(config_path.read_text())
            for conditioner in model_config.get("model", {}).get("conditioning", {}).get("configs", []):
                if conditioner.get("type") == "t5gemma":
                    conditioner.setdefault("config", {})["repo_id"] = str(root)

            model = load_diffusion_cond(
                model_config,
                str(checkpoint_path),
                device=device,
                model_half=device == "cuda",
            )
            model.eval().requires_grad_(False)
            value = StableAudioModel(model, model_config, device, device == "cuda")
            return self._remember(key, value)

    def ace_step(self, key: str):
        with self._lock:
            if key in self._items:
                self._items.move_to_end(key)
                return self._items[key]

            self._make_room(key)

            item = find_model(key)
            root = model_root(item)
            if not (root / "acestep-v15-turbo" / "model.safetensors").is_file():
                raise FileNotFoundError(f"model files are incomplete: {root}")

            # 上游初始化会覆盖 checkpoint 中的 Python 文件；只能写入私有视图。
            # 权重仍链接到只读共享目录，模型代码仅来自镜像中固定版本的 ACE-Step。
            view = tempfile.TemporaryDirectory(prefix='vvoice-ace-checkpoints-')
            checkpoint = Path(view.name)
            for file in item['shared_files']:
                relative = file['path']
                if relative.endswith('.py'):
                    continue
                source, target = root / relative, checkpoint / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                if source.suffix in {'.safetensors', '.bin', '.pt', '.pth', '.ckpt'}:
                    target.symlink_to(source.resolve())
                else:
                    shutil.copy2(source, target)
            from acestep.model_downloader import _sync_model_code_files
            _sync_model_code_files('acestep-v15-turbo', checkpoint)
            os.environ["ACESTEP_CHECKPOINTS_DIR"] = str(checkpoint)
            from acestep.handler import AceStepHandler

            handler = AceStepHandler()
            handler._vvoice_checkpoint_view = view
            status, ok = handler.initialize_service(
                project_root=str(checkpoint.parent),
                config_path="acestep-v15-turbo",
                device=detect_provider(),
                use_flash_attention=False,
                offload_to_cpu=False,
                offload_dit_to_cpu=False,
            )
            if not ok:
                raise RuntimeError(status)
            value = (handler, None)
            return self._remember(key, value)

    def musicgen(self, key: str):
        with self._lock:
            if key in self._items:
                self._items.move_to_end(key)
                return self._items[key]

            self._make_room(key)

            item = find_model(key)
            root = model_root(item)
            if not (root / "model.safetensors").is_file():
                raise FileNotFoundError(f"model files are incomplete: {root}")

            import torch
            from transformers import AutoProcessor, MusicgenForConditionalGeneration

            device = detect_provider()
            dtype = torch.float16 if device == "cuda" else torch.float32
            processor = AutoProcessor.from_pretrained(root, local_files_only=True)
            model = MusicgenForConditionalGeneration.from_pretrained(
                root,
                local_files_only=True,
                torch_dtype=dtype,
            ).to(device)
            model.eval().requires_grad_(False)
            value = (processor, model)
            return self._remember(key, value)


registry = RuntimeRegistry()


def generate_music(
    key: str,
    prompt: str,
    duration: float,
    negative_prompt: str,
    seed: int | None,
    response_format: str,
    bpm: int | None = None,
    key_name: str = "",
    time_signature: str = "",
    instrumental: bool = True,
) -> tuple[bytes, str]:
    item = find_model(key)
    adapter = item["runtime"].get("adapter")

    if adapter == "ace-step-1.5":
        from acestep.inference import (
            GenerationConfig,
            GenerationParams,
            generate_music as ace_generate_music,
        )

        meter = {"2/4": "2", "3/4": "3", "4/4": "4", "6/8": "6"}.get(
            time_signature, time_signature
        )
        params = GenerationParams(
            caption=prompt,
            lyrics="[Instrumental]" if instrumental else "",
            instrumental=instrumental,
            bpm=bpm,
            keyscale=key_name,
            timesignature=meter,
            duration=duration,
            seed=seed if seed is not None else -1,
            thinking=False,
            use_cot_metas=False,
            use_cot_caption=False,
            use_cot_language=False,
            inference_steps=8,
            shift=3.0,
        )
        config = GenerationConfig(
            batch_size=1,
            use_random_seed=seed is None,
            seeds=None if seed is None else [seed],
            audio_format=response_format,
        )
        with registry.inference(key), tempfile.TemporaryDirectory(prefix="v-music-ace-") as output:
            handler, llm_handler = registry.ace_step(key)
            result = ace_generate_music(
                handler, llm_handler, params, config, save_dir=output
            )
            if not result.success or not result.audios:
                raise RuntimeError(result.error or "ACE-Step generation failed")
            audio_path = result.audios[0].get("path")
            if not audio_path:
                raise RuntimeError("ACE-Step did not return an audio file")
            return Path(audio_path).read_bytes(), f"audio/{'x-wav' if response_format == 'wav' else 'flac'}"

    if adapter == "musicgen":
        import soundfile as sf
        import torch

        with registry.inference(key):
            processor, model = registry.musicgen(key)
            if seed is not None:
                torch.manual_seed(seed)
                if torch.cuda.is_available():
                    torch.cuda.manual_seed_all(seed)
            inputs = processor(text=[prompt], padding=True, return_tensors="pt")
            inputs = {name: value.to(model.device) for name, value in inputs.items()}
            with torch.inference_mode():
                audio = model.generate(
                    **inputs,
                    do_sample=True,
                    guidance_scale=3.0,
                    max_new_tokens=max(1, round(duration * 50)),
                )
            waveform = audio[0, 0].detach().to("cpu", dtype=torch.float32).numpy()
            output = io.BytesIO()
            sf.write(
                output,
                waveform,
                model.config.audio_encoder.sampling_rate,
                format=response_format.upper(),
            )
            return output.getvalue(), f"audio/{'x-wav' if response_format == 'wav' else 'flac'}"

    if adapter != "stable-audio-3":
        raise RuntimeError(f"runtime adapter is not available for {key}")

    import soundfile as sf
    import torch

    with registry.inference(key):
        runtime = registry.stable_audio(key)
        prompt_details = [prompt]
        if instrumental:
            prompt_details.append("instrumental, no vocals")
        if bpm:
            prompt_details.append(f"{bpm} BPM")
        if key_name:
            prompt_details.append(f"key: {key_name}")
        if time_signature:
            prompt_details.append(f"time signature: {time_signature}")
        audio = runtime.generate(
            prompt=", ".join(prompt_details),
            negative_prompt=negative_prompt or None,
            duration=duration,
            seed=seed if seed is not None else -1,
            batch_size=1,
            steps=8,
        )
        waveform = audio[0].detach().to("cpu", dtype=torch.float32).numpy().T
        output = io.BytesIO()
        sf.write(output, waveform, runtime.model.sample_rate, format=response_format.upper())
        return output.getvalue(), f"audio/{'x-wav' if response_format == 'wav' else 'flac'}"
