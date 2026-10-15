from __future__ import annotations

from pathlib import Path

import pytest

from vvoice.catalog import ASR_FACTORIES, SPEAKER_FACTORIES, STREAMING_FACTORIES, TTS_FAMILIES, catalog, model_files_ready, validate_descriptor
from vvoice.runtime import synthesize


def test_catalog_covers_every_runtime_interface() -> None:
    assert len(ASR_FACTORIES) == 21
    assert STREAMING_FACTORIES <= ASR_FACTORIES
    assert SPEAKER_FACTORIES == {"speaker_embedding"}
    assert TTS_FAMILIES == {"vits", "matcha", "kokoro", "zipvoice", "kitten", "pocket", "supertonic", "audio_cpp"}
    assert {item["kind"] for item in catalog()} == {"asr", "tts", "speaker"}


def test_streaming_descriptors_use_online_factories_only() -> None:
    streaming = [item for item in catalog() if item.get("streaming")]
    assert {item["key"] for item in streaming} == {"zipformer-en-streaming", "zipformer-zh-streaming"}
    for item in streaming:
        assert item["runtime"]["factory"] in STREAMING_FACTORIES
        assert item["kind"] == "asr"
        assert item["runtime"]["options"]["enable_endpoint_detection"] is True
    with pytest.raises(ValueError, match="not supported by OnlineRecognizer"):
        validate_descriptor(
            {
                "key": "bad-streaming",
                "kind": "asr",
                "streaming": True,
                "runtime": {"factory": "from_sense_voice", "files": {"model": "m.onnx"}},
            }
        )
    with pytest.raises(ValueError, match="streaming is only valid for ASR"):
        validate_descriptor(
            {
                "key": "bad-streaming-tts",
                "kind": "tts",
                "streaming": True,
                "runtime": {"family": "vits", "files": {"model": "m.onnx"}},
            }
        )


def test_speaker_descriptor_is_validated() -> None:
    item = next(model for model in catalog() if model["key"] == "speaker-campplus-zh-en")
    assert item["kind"] == "speaker"
    assert item["runtime"]["factory"] in SPEAKER_FACTORIES
    with pytest.raises(ValueError, match="unsupported speaker factory"):
        validate_descriptor(
            {
                "key": "bad-speaker",
                "kind": "speaker",
                "runtime": {"factory": "from_whisper", "files": {"model": "m.onnx"}},
            }
        )


def test_every_catalog_entry_is_vivibit_modelscope_repo() -> None:
    for item in catalog():
        assert item["modelscope_repo"].startswith("vivibit/v-voice-")
        assert not Path(next(iter(item["runtime"]["files"].values()))).is_absolute()


def test_qwen3_asr_uses_native_sherpa_onnx_factory() -> None:
    item = next(model for model in catalog() if model["key"] == "qwen3-asr-0.6b")
    assert item["runtime"]["factory"] == "from_qwen3_asr"
    assert item["runtime"]["files"]["encoder"] == "encoder.int8.onnx"
    assert item["modelscope_repo"] == "vivibit/v-voice-qwen3-asr-0.6b-int8"
    assert item["hotwords"] == {"supported": True, "formats": ["text", "file"], "score": False}


def test_zipformer_hotwords_use_bpe_modified_beam_search() -> None:
    item = next(model for model in catalog() if model["key"] == "zipformer-en")
    assert item["hotwords"]["score"] is True
    assert item["runtime"]["options"]["decoding_method"] == "modified_beam_search"
    assert item["runtime"]["options"]["modeling_unit"] == "bpe"
    assert item["runtime"]["files"]["bpe_vocab"] == "bpe.vocab"


def test_unknown_voice_is_rejected_before_loading_runtime() -> None:
    with pytest.raises(ValueError, match="unknown voice"):
        synthesize("kokoro-multilang", "hello", "not-a-real-voice", 1.0)


def test_descriptor_rejects_escape_path() -> None:
    with pytest.raises(ValueError, match="invalid runtime file"):
        validate_descriptor(
            {
                "key": "bad",
                "kind": "asr",
                "runtime": {"factory": "from_whisper", "files": {"encoder": "../secret"}},
            }
        )


def test_model_files_ready_reports_new_catalog_files_missing_from_old_install(monkeypatch, tmp_path) -> None:
    item = {
        "key": "zipformer-en",
        "kind": "asr",
        "modelscope_repo": "vivibit/v-voice-zipformer-en-int8",
        "runtime": {
            "factory": "from_transducer",
            "files": {"encoder": "encoder.onnx", "bpe_vocab": "bpe.vocab"},
        },
    }
    (tmp_path / "encoder.onnx").touch()
    (tmp_path / "vvoice-model.json").write_text(
        '{"key":"zipformer-en","kind":"asr","runtime":{"factory":"from_transducer",'
        '"files":{"encoder":"encoder.onnx"}}}',
        encoding="utf-8",
    )
    monkeypatch.setattr("vvoice.catalog.model_root", lambda _: tmp_path)

    ready, error = model_files_ready(item)

    assert ready is False
    assert "bpe.vocab" in error
