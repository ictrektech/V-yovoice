from __future__ import annotations

import threading
from contextlib import contextmanager

import numpy as np

from vvoice import runtime
from vvoice.runtime import RuntimeRegistry


def test_same_model_inference_is_serialized() -> None:
    registry = RuntimeRegistry(max_concurrent=2, max_concurrent_per_model=1)
    first_entered = threading.Event()
    release_first = threading.Event()
    second_entered = threading.Event()

    def first() -> None:
        with registry.inference("sensevoice-int8"):
            first_entered.set()
            release_first.wait(timeout=2)

    def second() -> None:
        first_entered.wait(timeout=2)
        with registry.inference("sensevoice-int8"):
            second_entered.set()

    first_thread = threading.Thread(target=first)
    second_thread = threading.Thread(target=second)
    first_thread.start()
    second_thread.start()
    assert first_entered.wait(timeout=1)
    assert not second_entered.wait(timeout=0.05)
    release_first.set()
    assert second_entered.wait(timeout=1)
    first_thread.join(timeout=1)
    second_thread.join(timeout=1)


class _FakeStream:
    result = '{"text":"ok"}'

    def __init__(self) -> None:
        self.options: dict[str, str] = {}

    def set_option(self, key: str, value: str) -> None:
        self.options[key] = value

    def accept_waveform(self, sample_rate: int, samples: np.ndarray) -> None:
        assert sample_rate == 16000
        assert samples.dtype == np.float32


class _FakeRecognizer:
    def __init__(self) -> None:
        self.stream = _FakeStream()
        self.hotwords_argument: str | None = None

    def create_stream(self, hotwords: str | None = None) -> _FakeStream:
        self.hotwords_argument = hotwords
        return self.stream

    def decode_stream(self, stream: _FakeStream) -> None:
        assert stream is self.stream


class _FakeRegistry:
    def __init__(self) -> None:
        self.recognizer = _FakeRecognizer()
        self.asr_kwargs: dict[str, object] = {}

    @contextmanager
    def inference(self, key: str):
        yield

    def asr(self, key: str, **kwargs):
        self.asr_kwargs = kwargs
        return self.recognizer


def test_qwen3_hotwords_are_set_per_stream(monkeypatch) -> None:
    fake = _FakeRegistry()
    monkeypatch.setattr(runtime, "registry", fake)
    monkeypatch.setattr(
        runtime,
        "find_model",
        lambda key, kind=None: {
            "key": key,
            "kind": "asr",
            "hotwords": {"supported": True, "score": False},
            "runtime": {"factory": "from_qwen3_asr"},
        },
    )

    result = runtime.transcribe("qwen3-asr-0.6b", np.zeros(8), 16000, hotwords=["华为", "V-Voice"])

    assert result["text"] == "ok"
    assert fake.recognizer.stream.options["hotwords"] == "华为,V-Voice"
    assert fake.recognizer.hotwords_argument is None


def test_zipformer_hotwords_and_score_are_applied(monkeypatch) -> None:
    fake = _FakeRegistry()
    monkeypatch.setattr(runtime, "registry", fake)
    monkeypatch.setattr(
        runtime,
        "find_model",
        lambda key, kind=None: {
            "key": key,
            "kind": "asr",
            "hotwords": {"supported": True, "score": True, "default_score": 1.5},
            "runtime": {"factory": "from_transducer"},
        },
    )

    runtime.transcribe("zipformer-en", np.zeros(8), 16000, hotwords=["OPENAI", "V VOICE"], hotwords_score=2.0)

    assert fake.recognizer.hotwords_argument == "OPENAI/V VOICE"
    assert fake.asr_kwargs["hotwords_score"] == 2.0


def test_unsupported_model_ignores_hotwords(monkeypatch) -> None:
    fake = _FakeRegistry()
    monkeypatch.setattr(runtime, "registry", fake)
    monkeypatch.setattr(
        runtime,
        "find_model",
        lambda key, kind=None: {"key": key, "kind": "asr", "runtime": {"factory": "from_sense_voice"}},
    )
    result = runtime.transcribe(
        "sensevoice-int8", np.zeros(8), 16000, hotwords=["华为"], hotwords_score=2.0
    )
    assert result["text"] == "ok"
    assert fake.recognizer.hotwords_argument is None
