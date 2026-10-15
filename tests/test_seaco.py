from contextlib import contextmanager

import numpy as np
import pytest

from vvoice import runtime
from vvoice.catalog import catalog, validate_descriptor
from vvoice.seaco import SeacoRecognizer


def test_seaco_descriptor_is_additional_and_capability_honest():
    items = {item["key"]: item for item in catalog()}
    item = items["seaco-paraformer-zh"]
    assert items["paraformer-zh"]["runtime"]["factory"] == "from_paraformer"
    assert validate_descriptor(item)["hotwords"]["supported"]
    assert item["runtime"]["factory"] == "seaco_onnx"
    assert not item["translation"] and not item.get("streaming")
    assert not item["timestamps"]["word"]


class FakeEmbedder:
    def get_inputs(self):
        return [type("Input", (), {"name": "hotword", "shape": [None, 10]})()]

    def run(self, outputs, feeds):
        self.ids = feeds["hotword"].copy()
        # Each hotword's final token is observable in its embedding.
        return [np.repeat(self.ids.T[:, :, None], 512, axis=2).astype(np.float32)]


def test_hotword_embedding_is_request_scoped_and_rejects_truncation():
    recognizer = SeacoRecognizer.__new__(SeacoRecognizer)
    recognizer.vocab = {"<s>": 1, "<unk>": 4, "魔": 5, "搭": 6}
    recognizer.hotword_width = 10
    recognizer.embedder = FakeEmbedder()
    embedded = recognizer._hotword_embedding(["魔搭"])
    assert embedded.shape == (1, 2, 512)
    assert embedded[0, 0, 0] == 6
    assert recognizer._hotword_embedding([]).shape == (1, 1, 512)
    with pytest.raises(ValueError, match="at most 10"):
        recognizer._hotword_embedding(["魔" * 11])


def test_seaco_uses_existing_registry_and_does_not_call_sherpa(monkeypatch):
    calls = []

    class Recognizer:
        def transcribe(self, samples, rate, phrases):
            calls.append((rate, phrases))
            return {"text": "魔搭", "tokens": ["魔", "搭"], "timestamps": [], "language": "zh"}

    class Registry:
        @contextmanager
        def inference(self, key):
            yield

        def asr(self, key, **kwargs):
            return Recognizer()

    monkeypatch.setattr(runtime, "registry", Registry())
    result = runtime.transcribe("seaco-paraformer-zh", np.zeros(16000), 16000, hotwords=["魔搭"])
    assert calls == [(16000, ["魔搭"])]
    assert result["text"] == "魔搭" and result["words"] == []
    with pytest.raises(ValueError, match="not translation"):
        runtime.transcribe("seaco-paraformer-zh", np.zeros(16000), 16000, task="translate")
