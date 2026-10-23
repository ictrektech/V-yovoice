from __future__ import annotations

import json
import ctypes
import gc
import os
import threading
from collections import OrderedDict
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import numpy as np

from .catalog import find_model, model_root, resolve_files
from .config import settings
from .transcript import merge_segment_transcripts, normalize_transcript
from .vad import needs_split, _speech_segments


def _sherpa():
    import sherpa_onnx

    return sherpa_onnx


def _release_cpu_memory() -> None:
    # 只处理已无引用的对象及空闲 CPU 堆页；不代表 GPU/推理进程已停止。
    gc.collect()
    try:
        trim = ctypes.CDLL(None).malloc_trim
        trim.argtypes = [ctypes.c_size_t]
        trim.restype = ctypes.c_int
        trim(0)
    except (AttributeError, OSError):
        # 非 glibc 平台没有此接口，模型卸载仍应正常完成。
        pass


def detect_provider() -> str:
    if settings.provider != "auto":
        return settings.provider
    try:
        import onnxruntime as ort

        if "CUDAExecutionProvider" in ort.get_available_providers():
            return "cuda"
    except ImportError:
        pass
    return "cpu"


def _model_provider(key: str | None) -> str:
    return "cpu" if key in settings.cpu_models else detect_provider()


def _kwargs(item: dict[str, Any], include_common: bool = True) -> dict[str, Any]:
    runtime = item["runtime"]
    values = dict(runtime.get("options") or {})
    values.update(resolve_files(item))
    if include_common:
        # Some model/provider combinations are broken on specific accelerators
        # (e.g. int8 Paraformer broadcasting errors on Jetson CUDA EP); listed
        # models are pinned to CPU via VVOICE_CPU_MODELS.
        provider = _model_provider(item.get("key"))
        values.setdefault("provider", provider)
        values.setdefault("num_threads", settings.num_threads)
    return values


class RuntimeRegistry:
    def __init__(self, max_concurrent: int | None = None, max_concurrent_per_model: int | None = None) -> None:
        self._items: OrderedDict[str, Any] = OrderedDict()
        self._lock = threading.RLock()
        self._global_gate = threading.BoundedSemaphore(max_concurrent or settings.max_concurrent_inference)
        self._per_model_limit = max_concurrent_per_model or settings.max_concurrent_per_model
        self._model_gates: dict[str, threading.BoundedSemaphore] = {}

    @contextmanager
    def inference(self, key: str):
        with self._lock:
            gate = self._model_gates.setdefault(key, threading.BoundedSemaphore(self._per_model_limit))
        if os.getenv("VVOICE_SCHEDULER_REQUIRED") == "true":
            from .admission import current
            execution = current.get()
            if execution is None:
                from fastapi import HTTPException
                raise HTTPException(503, "Inference requires a scheduled request context")
            execution.enter(key)
        with self._global_gate, gate:
            yield

    def unload(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._items.clear()
            else:
                for cache_key in [
                    candidate
                    for candidate in self._items
                    if candidate == f"asr:{key}"
                    or candidate.startswith(f"asr:{key}:")
                    or candidate.startswith(f"asr-online:{key}")
                    or candidate == f"tts:{key}"
                    or candidate == f"speaker:{key}"
                ]:
                    self._items.pop(cache_key, None)
        _release_cpu_memory()

    def is_loaded(self, key: str) -> bool:
        with self._lock:
            return any(
                candidate == f"asr:{key}"
                or candidate.startswith(f"asr:{key}:")
                or candidate.startswith(f"asr-online:{key}")
                or candidate == f"tts:{key}"
                or candidate == f"speaker:{key}"
                for candidate in self._items
            )

    def _cached(self, key: str, factory) -> Any:
        with self._lock:
            if key in self._items:
                self._items.move_to_end(key)
                return self._items[key]
            value = factory()
            self._items[key] = value
            evicted = False
            while len(self._items) > settings.max_loaded_models:
                self._items.popitem(last=False)
                evicted = True
        if evicted:
            _release_cpu_memory()
        return value

    def asr(
        self,
        key: str,
        language: str = "",
        task: str = "transcribe",
        hotwords_score: float | None = None,
    ):
        item = find_model(key, "asr")
        factory_name = item["runtime"]["factory"]
        overrides: dict[str, Any] = {}
        if factory_name == "from_whisper":
            overrides["task"] = task
            overrides["language"] = language
        elif factory_name == "from_sense_voice" and language:
            overrides["language"] = language
        if factory_name == "from_transducer" and hotwords_score is not None:
            overrides["hotwords_score"] = hotwords_score

        def load():
            if factory_name == "seaco_onnx":
                from .seaco import SeacoRecognizer
                return SeacoRecognizer(resolve_files(item), settings.num_threads)
            recognizer = _sherpa().OfflineRecognizer
            factory = getattr(recognizer, factory_name)
            values = _kwargs(item)
            values.update(overrides)
            return factory(**values)

        cache_variant = json.dumps(overrides, sort_keys=True, separators=(",", ":"))
        return self._cached(f"asr:{key}:{cache_variant}", load)

    def online_asr(
        self,
        key: str,
        hotwords_score: float | None = None,
    ):
        item = find_model(key, "asr")
        if not item.get("streaming"):
            raise ValueError(f"model {key} does not support streaming recognition")
        factory_name = item["runtime"]["factory"]
        overrides: dict[str, Any] = {}
        if factory_name == "from_transducer" and hotwords_score is not None:
            overrides["hotwords_score"] = hotwords_score

        def load():
            recognizer = _sherpa().OnlineRecognizer
            factory = getattr(recognizer, factory_name)
            values = _kwargs(item)
            values.update(overrides)
            return factory(**values)

        cache_variant = json.dumps(overrides, sort_keys=True, separators=(",", ":"))
        return self._cached(f"asr-online:{key}:{cache_variant}", load)

    def speaker(self, key: str):
        item = find_model(key, "speaker")

        def load():
            sherpa = _sherpa()
            config = sherpa.SpeakerEmbeddingExtractorConfig(
                model=resolve_files(item)["model"],
                num_threads=settings.num_threads,
                provider=_model_provider(key),
            )
            if not config.validate():
                raise ValueError(f"invalid speaker model descriptor: {key}")
            return sherpa.SpeakerEmbeddingExtractor(config)

        return self._cached(f"speaker:{key}", load)

    def tts(self, key: str):
        item = find_model(key, "tts")

        def load():
            sherpa = _sherpa()
            runtime = item["runtime"]
            family = runtime["family"]
            class_name = "OfflineTts" + family.title().replace("voice", "voice") + "ModelConfig"
            family_class = getattr(sherpa, class_name)
            model = sherpa.OfflineTtsModelConfig(
                **{
                    family: family_class(**_kwargs(item, include_common=False)),
                    "provider": _model_provider(key),
                    "num_threads": settings.num_threads,
                    "debug": bool(runtime.get("debug", False)),
                }
            )
            config = sherpa.OfflineTtsConfig(
                model=model,
                rule_fsts=",".join(str(model_root(item) / name) for name in runtime.get("rule_fsts", [])),
                max_num_sentences=int(runtime.get("max_num_sentences", 1)),
            )
            if not config.validate():
                raise ValueError(f"invalid TTS model descriptor: {key}")
            return sherpa.OfflineTts(config)

        return self._cached(f"tts:{key}", load)


registry = RuntimeRegistry()


def _decode_segment(
    key: str,
    item: dict[str, Any],
    samples: np.ndarray,
    sample_rate: int,
    language: str,
    task: str,
    phrases: list[str],
    score: float | None,
) -> dict[str, Any]:
    """Decode one (already sized) utterance with the offline recognizer."""
    with registry.inference(key):
        recognizer = registry.asr(key, language=language, task=task, hotwords_score=score)
        factory_name = item["runtime"]["factory"]
        if factory_name == "seaco_onnx":
            if task != "transcribe":
                raise ValueError("SeACo supports transcription, not translation")
            result = recognizer.transcribe(samples, sample_rate, phrases)
        else:
            stream = (
                recognizer.create_stream("/".join(phrases))
                if phrases and factory_name == "from_transducer"
                else recognizer.create_stream()
            )
            if language and factory_name == "from_qwen3_asr":
                stream.set_option("language", language)
            if phrases and factory_name == "from_qwen3_asr":
                stream.set_option("hotwords", ",".join(phrases))
            stream.accept_waveform(sample_rate, samples.astype(np.float32))
            recognizer.decode_stream(stream)
            result = stream.result
    if isinstance(result, dict):
        parsed = result
    elif isinstance(result, str):
        try:
            parsed = json.loads(result)
        except json.JSONDecodeError:
            parsed = {"text": result}
    else:
        parsed = {name: getattr(result, name) for name in ("text", "tokens", "timestamps", "lang", "emotion", "event") if hasattr(result, name)}
    duration = len(samples) / sample_rate if sample_rate > 0 else 0.0
    parsed = normalize_transcript(parsed, duration)
    parsed.setdefault("language", parsed.get("lang") or language or None)
    return parsed


def transcribe(
    key: str,
    samples: np.ndarray,
    sample_rate: int,
    language: str = "",
    task: str = "transcribe",
    hotwords: list[str] | None = None,
    hotwords_score: float | None = None,
) -> dict[str, Any]:
    from .admission import validate_inputs
    validate_inputs(key, duration_seconds=len(samples) / sample_rate if sample_rate > 0 else float("nan"), sample_rate=sample_rate, hotwords_characters=sum(len(phrase) for phrase in hotwords or []))
    item = find_model(key, "asr")
    if item.get("streaming"):
        return _transcribe_online(key, item, samples, sample_rate, hotwords, hotwords_score)
    phrases, effective_score = _effective_hotwords(item, hotwords, hotwords_score)

    # Long audio degrades badly when decoded as one utterance (offline models
    # are trained on short speech), so split on voice activity and merge.
    if needs_split(samples, sample_rate):
        try:
            segments = _speech_segments(samples, sample_rate)
        except Exception:
            segments = []
        if segments:
            parts = []
            offsets = []
            for offset, chunk in segments:
                parts.append(_decode_segment(key, item, chunk, sample_rate, language, task, phrases, effective_score))
                offsets.append(offset)
            merged = merge_segment_transcripts(parts, offsets, len(samples) / sample_rate)
            merged.setdefault("language", merged.get("lang") or language or None)
            merged["task"] = task
            merged["segments_decoded"] = len(parts)
            return merged

    parsed = _decode_segment(key, item, samples, sample_rate, language, task, phrases, effective_score)
    parsed["task"] = task
    return parsed


def _effective_hotwords(item: dict[str, Any], hotwords: list[str] | None, hotwords_score: float | None):
    hotword_config = item.get("hotwords") or {}
    phrases = hotwords or []
    if not hotword_config.get("supported"):
        return [], None
    score = hotwords_score if hotword_config.get("score") else None
    if phrases and hotword_config.get("score") and score is None:
        score = float(hotword_config.get("default_score", 1.5))
    return phrases, score


def _transcribe_online(
    key: str,
    item: dict[str, Any],
    samples: np.ndarray,
    sample_rate: int,
    hotwords: list[str] | None,
    hotwords_score: float | None,
) -> dict[str, Any]:
    """Whole-utterance decode through the OnlineRecognizer for streaming models."""
    phrases, score = _effective_hotwords(item, hotwords, hotwords_score)
    with online_session(key, phrases, score) as (recognizer, stream):
        stream.accept_waveform(sample_rate, samples.astype(np.float32))
        result = finish_online_stream(recognizer, stream)
    duration = len(samples) / sample_rate if sample_rate > 0 else 0.0
    parsed = normalize_transcript(result, duration)
    parsed.setdefault("language", None)
    parsed["task"] = "transcribe"
    parsed["streaming"] = True
    return parsed


@contextmanager
def online_session(
    key: str,
    hotwords: list[str] | None = None,
    hotwords_score: float | None = None,
):
    """Yield (recognizer, stream) for a streaming model, holding the model gate."""
    item = find_model(key, "asr")
    if not item.get("streaming"):
        raise ValueError(f"model {key} does not support streaming recognition")
    phrases, score = _effective_hotwords(item, hotwords, hotwords_score)
    with registry.inference(key):
        recognizer = registry.online_asr(key, hotwords_score=score)
        prompt = "/".join(phrases) if phrases else None
        stream = recognizer.create_stream(prompt) if prompt else recognizer.create_stream()
        yield recognizer, stream


def feed_online_chunk(recognizer, stream, samples: np.ndarray, sample_rate: int, emit_partials: bool = False) -> dict[str, Any] | None:
    """Push one audio chunk into a streaming recognizer and decode what is ready.

    Returns partial info (text, endpoint flag) when emit_partials is enabled.
    """
    if len(samples):
        stream.accept_waveform(sample_rate, samples.astype(np.float32))
    while recognizer.is_ready(stream):
        recognizer.decode_stream(stream)
    if not emit_partials:
        return None
    return {
        "text": recognizer.get_result(stream),
        "is_endpoint": bool(recognizer.is_endpoint(stream)) if hasattr(recognizer, "is_endpoint") else False,
    }


def finish_online_stream(recognizer, stream) -> dict[str, Any]:
    stream.input_finished()
    while recognizer.is_ready(stream):
        recognizer.decode_stream(stream)
    tokens = list(recognizer.tokens(stream)) if hasattr(recognizer, "tokens") else []
    timestamps = list(recognizer.timestamps(stream)) if hasattr(recognizer, "timestamps") else []
    return {
        "text": recognizer.get_result(stream),
        "tokens": tokens,
        "timestamps": timestamps,
    }


def extract_embedding(key: str, samples: np.ndarray, sample_rate: int) -> np.ndarray:
    """Compute a speaker embedding for decoded audio with a catalog speaker model."""
    with registry.inference(key):
        extractor = registry.speaker(key)
        stream = extractor.create_stream()
        stream.accept_waveform(sample_rate, samples.astype(np.float32))
        stream.input_finished()
        if not extractor.is_ready(stream):
            raise ValueError("audio is too short for speaker embedding extraction")
        embedding = np.asarray(extractor.compute(stream), dtype=np.float32)
    if not embedding.size:
        raise RuntimeError("speaker embedding extraction returned empty vector")
    return embedding


def synthesize(key: str, text: str, voice: str, speed: float, language: str = "", **options) -> tuple[np.ndarray, int]:
    from .admission import validate_inputs
    validate_inputs(key, text_characters=len(text), speed=speed)
    item = find_model(key, "tts")
    if item["runtime"]["family"] == "audio_cpp":
        from .creative import synthesize as creative_synthesize
        resolve_files(item)
        with registry.inference(key):
            return creative_synthesize(item, text, voice, speed, language, **options)
    voice_map = item.get("voices") or {"default": {"sid": 0}}
    selected = voice_map.get(voice)
    if selected is None:
        raise ValueError(f"unknown voice {voice!r} for model {key}")
    with registry.inference(key):
        tts = registry.tts(key)
        sherpa = _sherpa()
        config = sherpa.GenerationConfig()
        config.sid = int(selected.get("sid", 0))
        config.speed = speed
        config.silence_scale = float(selected.get("silence_scale", 0.2))
        config.num_steps = int(selected.get("num_steps", item["runtime"].get("num_steps", 4)))
        lang = language or selected.get("language") or item.get("default_language") or ""
        if lang:
            config.extra["lang"] = lang
        default_reference = selected.get("reference_audio") or item["runtime"].get("reference_audio")
        if default_reference:
            import soundfile as sf

            samples, rate = sf.read(model_root(item) / default_reference, dtype="float32", always_2d=False)
            if samples.ndim > 1:
                samples = samples[:, 0]
            config.reference_audio = samples
            config.reference_sample_rate = rate
            config.reference_text = selected.get("reference_text") or item["runtime"].get("reference_text", "")
        audio = tts.generate(text, config)
    if len(audio.samples) == 0:
        raise RuntimeError("sherpa-onnx returned empty audio")
    return np.asarray(audio.samples, dtype=np.float32), int(audio.sample_rate)
