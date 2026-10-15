from __future__ import annotations

import numpy as np
from fastapi.testclient import TestClient

from vvoice.main import app


client = TestClient(app)


def test_health_and_about() -> None:
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    about = client.get("/api/v1/about")
    assert about.status_code == 200
    assert about.json()["supported_asr_families"] == 20
    assert about.json()["supported_tts_families"] == 7
    assert about.json()["supported_speaker_families"] == 1
    assert about.json()["streaming_asr"] is True
    assert about.json()["max_loaded_models"] >= 1
    assert about.json()["max_concurrent_inference"] >= 1


def test_scheduler_contract_includes_legacy_and_all_creator_models_without_credentials():
    from vvoice.main import scheduler_contract
    contract = scheduler_contract()
    assert contract["app_id"] == "com.ictrek.v-voice"
    assert contract["protocol_version"] == 1
    assert contract["binding_endpoint"] == "/api/v1/scheduler/binding"
    sync = {row["id"]: row for row in contract["sync_models"]}
    assert {"sensevoice-int8", "seaco-paraformer-zh", "speaker-campplus-zh-en", "audiocpp-kokoro-82m-q8"} <= sync.keys()
    assert len(contract["async_models"]) == 38
    assert all(row["task_type"] == "voice.generate" for row in contract["async_models"])
    assert "token" not in str(contract)


def test_unknown_models_are_rejected_before_runtime_load() -> None:
    response = client.post(
        "/v1/audio/speech",
        json={"model": "unknown", "input": "hello", "voice": "default", "response_format": "wav"},
    )
    assert response.status_code == 404


def test_discovery_is_public_and_lists_ready_models(monkeypatch) -> None:
    async def fake_models():
        return [
            {"key": "sensevoice-int8", "kind": "asr", "status": "ready"},
            {
                "key": "qwen3-asr-0.6b",
                "kind": "asr",
                "status": "ready",
                "hotwords": {"supported": True, "formats": ["text", "file"], "score": False},
            },
            {"key": "kokoro-multilang", "kind": "tts", "status": "not_installed"},
        ]

    monkeypatch.setattr("vvoice.main.list_models", fake_models)
    response = client.get("/api/v1/discovery")
    assert response.status_code == 200
    payload = response.json()
    assert payload["visibility"] == "public"
    assert payload["multi_tenant"] is False
    assert payload["authentication"] == "none"
    assert payload["base_url"] == "http://v-voice-backend:7070/v1"
    assert [item["id"] for item in payload["models"]] == ["sensevoice-int8", "qwen3-asr-0.6b"]
    assert payload["models"][1]["capabilities"] == ["asr", "transcription", "hotwords"]
    assert payload["models"][1]["hotwords"]["score"] is False


def test_discovery_lists_streaming_and_speaker_models(monkeypatch) -> None:
    async def fake_models():
        return [
            {
                "key": "zipformer-en-streaming",
                "kind": "asr",
                "status": "ready",
                "streaming": True,
                "hotwords": {"supported": True, "formats": ["text", "file"], "score": True, "default_score": 1.5},
                "timestamps": {"word": True, "segment": True, "source": "sherpa_token_timestamps"},
            },
            {
                "key": "speaker-campplus-zh-en",
                "kind": "speaker",
                "status": "ready",
                "languages": ["zh", "en"],
            },
        ]

    monkeypatch.setattr("vvoice.main.list_models", fake_models)
    payload = client.get("/api/v1/discovery").json()
    assert [item["id"] for item in payload["models"]] == ["zipformer-en-streaming", "speaker-campplus-zh-en"]

    streaming = payload["models"][0]
    assert "streaming" in streaming["capabilities"]
    assert streaming["endpoints"] == [
        "audio/transcriptions",
        "audio/translations",
        "audio/streaming/transcriptions",
        "audio/streaming/ws",
    ]
    assert streaming["streaming"] == {"supported": True, "transports": ["http-chunked", "websocket"], "hotwords": True}

    speaker = payload["models"][1]
    assert speaker["kind"] == "speaker"
    assert speaker["capabilities"] == ["speaker", "speaker-identification", "speaker-verification"]
    assert speaker["endpoints"] == ["audio/speakers", "audio/speakers/identify", "audio/speakers/verify"]


def test_streaming_transcriptions_endpoint(monkeypatch) -> None:
    import numpy as np

    from vvoice import main as main_module

    sessions = []

    class FakeStream:
        def accept_waveform(self, rate, samples):
            pass

        def input_finished(self):
            pass

    class FakeRecognizer:
        def is_ready(self, stream):
            return False

        def decode_stream(self, stream):
            pass

        def get_result(self, stream):
            return "hello streaming"

        def tokens(self, stream):
            return ["▁hello", "▁streaming"]

        def timestamps(self, stream):
            return [0.1, 0.4]

    class FakeSession:
        def __enter__(self):
            sessions.append(True)
            return FakeRecognizer(), FakeStream()

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(main_module, "online_session", lambda *args, **kwargs: FakeSession())
    monkeypatch.setattr(main_module, "feed_online_chunk", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        main_module, "finish_online_stream",
        lambda recognizer, stream: {"text": "hello streaming", "tokens": ["▁hello", "▁streaming"], "timestamps": [0.1, 0.4]},
    )

    pcm = (np.zeros(3200, dtype=np.int16)).tobytes()
    response = client.post(
        "/v1/audio/streaming/transcriptions?model=zipformer-en-streaming&format=pcm",
        content=pcm,
        headers={"Content-Type": "application/octet-stream"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["text"] == "hello streaming"
    assert body["streaming"] is True
    assert body["words"][0]["word"] == "hello"

    offline = client.post(
        "/v1/audio/streaming/transcriptions?model=sensevoice-int8&format=pcm",
        content=pcm,
        headers={"Content-Type": "application/octet-stream"},
    )
    assert offline.status_code == 422
    assert "does not support streaming" in offline.json()["detail"]


def test_transcription_with_speaker_attribution(monkeypatch, tmp_path) -> None:
    import numpy as np

    from vvoice import main as main_module
    from vvoice.speakers import SpeakerStore

    store = SpeakerStore(tmp_path)
    store.create("张三", np.array([1.0, 0.0], dtype=np.float32), "speaker-campplus-zh-en")
    monkeypatch.setattr(main_module, "speaker_store", store)
    monkeypatch.setattr(main_module, "decode_audio", lambda data, name: (np.zeros(1600), 16000))
    monkeypatch.setattr(main_module, "transcribe", lambda *args, **kwargs: {"text": "ok"})
    monkeypatch.setattr(
        main_module, "extract_embedding",
        lambda model, samples, rate: np.array([1.0, 0.0], dtype=np.float32),
    )

    response = client.post(
        "/v1/audio/transcriptions",
        data={"model": "sensevoice-int8", "response_format": "verbose_json", "speaker_model": "speaker-campplus-zh-en"},
        files={"file": ("sample.wav", b"audio", "audio/wav")},
    )
    assert response.status_code == 200
    speaker = response.json()["speaker"]
    assert speaker["identified"] is True
    assert speaker["speaker"]["name"] == "张三"
    assert speaker["score"] == 1.0
    assert speaker["threshold"] == 0.6

    unknown = client.post(
        "/v1/audio/transcriptions",
        data={"model": "sensevoice-int8", "speaker_model": "speaker-missing"},
        files={"file": ("sample.wav", b"audio", "audio/wav")},
    )
    assert unknown.status_code == 404

    without = client.post(
        "/v1/audio/transcriptions",
        data={"model": "sensevoice-int8", "response_format": "json"},
        files={"file": ("sample.wav", b"audio", "audio/wav")},
    )
    assert without.status_code == 200
    assert "speaker" not in without.json()


def test_streaming_transcriptions_with_speaker_attribution(monkeypatch, tmp_path) -> None:
    import numpy as np

    from vvoice import main as main_module
    from vvoice.speakers import SpeakerStore

    class FakeStream:
        def accept_waveform(self, rate, samples):
            pass

        def input_finished(self):
            pass

    class FakeRecognizer:
        def is_ready(self, stream):
            return False

        def decode_stream(self, stream):
            pass

        def get_result(self, stream):
            return "hello streaming"

        def tokens(self, stream):
            return ["▁hello"]

        def timestamps(self, stream):
            return [0.1]

    class FakeSession:
        def __enter__(self):
            return FakeRecognizer(), FakeStream()

        def __exit__(self, *args):
            return False

    store = SpeakerStore(tmp_path)
    store.create("李四", np.array([0.0, 1.0], dtype=np.float32), "speaker-campplus-zh-en")
    monkeypatch.setattr(main_module, "speaker_store", store)
    monkeypatch.setattr(main_module, "online_session", lambda *args, **kwargs: FakeSession())
    monkeypatch.setattr(main_module, "feed_online_chunk", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        main_module, "finish_online_stream",
        lambda recognizer, stream: {"text": "hello streaming", "tokens": ["▁hello"], "timestamps": [0.1]},
    )
    monkeypatch.setattr(
        main_module, "extract_embedding",
        lambda model, samples, rate: np.array([0.0, 1.0], dtype=np.float32),
    )

    pcm = (np.zeros(3200, dtype=np.int16)).tobytes()
    response = client.post(
        "/v1/audio/streaming/transcriptions?model=zipformer-en-streaming&format=pcm&speaker_model=speaker-campplus-zh-en",
        content=pcm,
        headers={"Content-Type": "application/octet-stream"},
    )
    assert response.status_code == 200
    speaker = response.json()["speaker"]
    assert speaker["identified"] is True
    assert speaker["speaker"]["name"] == "李四"


def test_speaker_endpoints_manage_and_match_voiceprints(monkeypatch, tmp_path) -> None:
    import numpy as np

    from vvoice import main as main_module
    from vvoice.speakers import SpeakerStore

    store = SpeakerStore(tmp_path)
    monkeypatch.setattr(main_module, "speaker_store", store)
    monkeypatch.setattr(
        main_module, "extract_embedding",
        lambda model, samples, rate: np.array([1.0, 0.0, 0.0], dtype=np.float32),
    )
    monkeypatch.setattr(main_module, "find_model", lambda key, kind: {"key": key, "kind": kind})
    monkeypatch.setattr(main_module, "decode_audio", lambda data, name: (np.zeros(1600), 16000))

    enrolled = client.post(
        "/api/v1/speakers",
        data={"name": "张三", "model": "speaker-campplus-zh-en"},
        files={"file": ("zhangsan.wav", b"audio", "audio/wav")},
    )
    assert enrolled.status_code == 201
    body = enrolled.json()
    assert body["name"] == "张三"
    assert body["dimension"] == 3

    listed = client.get("/v1/audio/speakers")
    assert listed.status_code == 200
    assert listed.json()["speakers"][0]["id"] == body["id"]
    assert "embedding" not in listed.json()["speakers"][0]

    identified = client.post(
        "/v1/audio/speakers/identify",
        data={"model": "speaker-campplus-zh-en", "threshold": "0.5"},
        files={"file": ("sample.wav", b"audio", "audio/wav")},
    )
    assert identified.status_code == 200
    result = identified.json()
    assert result["identified"] is True
    assert result["speaker"]["id"] == body["id"]
    assert result["score"] == 1.0

    verified = client.post(
        "/v1/audio/speakers/verify",
        data={"speaker": "张三", "model": "speaker-campplus-zh-en", "threshold": "0.5"},
        files={"file": ("sample.wav", b"audio", "audio/wav")},
    )
    assert verified.status_code == 200
    assert verified.json()["verified"] is True

    missing = client.post(
        "/v1/audio/speakers/verify",
        data={"speaker": "sp_nobody", "model": "speaker-campplus-zh-en"},
        files={"file": ("sample.wav", b"audio", "audio/wav")},
    )
    assert missing.status_code == 404

    deleted = client.delete(f"/api/v1/speakers/{body['id']}")
    assert deleted.status_code == 200
    assert client.get("/v1/audio/speakers").json()["speakers"] == []


def test_voices_are_machine_readable_for_dependent_picklists(monkeypatch) -> None:
    monkeypatch.setattr(
        "vvoice.main.find_model",
        lambda model, kind: {
            "voices": {
                "default": {"sid": 0, "language": "en"},
                "speaker_1": {"sid": 1, "language": "en"},
            }
        },
    )

    response = client.get("/v1/audio/voices", params={"model": "kitten-nano-en"})

    assert response.status_code == 200
    assert response.json() == {
        "object": "list",
        "model": "kitten-nano-en",
        "default_voice": "default",
        "voices": [
            {"id": "default", "name": "default", "sid": 0, "language": "en"},
            {"id": "speaker_1", "name": "speaker_1", "sid": 1, "language": "en"},
        ],
        "data": [
            {"id": "default", "name": "default", "sid": 0, "language": "en"},
            {"id": "speaker_1", "name": "speaker_1", "sid": 1, "language": "en"},
        ],
    }


def test_transcription_passes_inline_and_file_hotwords(monkeypatch) -> None:
    captured = {}

    monkeypatch.setattr("vvoice.main.decode_audio", lambda data, name: (np.zeros(8), 16000))

    def fake_transcribe(model, samples, rate, language, task, hotwords, hotwords_score):
        captured.update(model=model, hotwords=hotwords, hotwords_score=hotwords_score)
        return {"text": "ok"}

    monkeypatch.setattr("vvoice.main.transcribe", fake_transcribe)
    response = client.post(
        "/v1/audio/transcriptions",
        data={"model": "zipformer-en", "hotwords": "OpenAI,V-Voice", "hotwords_score": "1.5"},
        files={
            "file": ("sample.wav", b"audio", "audio/wav"),
            "hotwords_file": ("hotwords.txt", b"sherpa-onnx\nOpenAI\n", "text/plain"),
        },
    )
    assert response.status_code == 200
    assert captured == {
        "model": "zipformer-en",
        "hotwords": ["OpenAI", "V-Voice", "sherpa-onnx"],
        "hotwords_score": 1.5,
    }


def test_unsupported_asr_model_ignores_hotwords(monkeypatch) -> None:
    monkeypatch.setattr("vvoice.main.decode_audio", lambda data, name: (np.zeros(8), 16000))
    monkeypatch.setattr(
        "vvoice.main.find_model",
        lambda model, kind: {"key": model, "kind": kind},
    )
    monkeypatch.setattr(
        "vvoice.main.transcribe",
        lambda model, samples, rate, language, task, hotwords, hotwords_score: {"text": "ok"},
    )
    response = client.post(
        "/v1/audio/transcriptions",
        data={"model": "sensevoice-int8", "hotwords": "华为", "hotwords_score": "20"},
        files={
            "file": ("sample.wav", b"audio", "audio/wav"),
            "hotwords_file": ("hotwords.txt", b"\xff", "text/plain"),
        },
    )
    assert response.status_code == 200
    assert response.json() == {"text": "ok"}


def test_runtime_config_exposes_injected_app_version(monkeypatch) -> None:
    import dataclasses

    from vvoice import main as main_module

    monkeypatch.setattr(main_module, "settings", dataclasses.replace(main_module.settings, app_version="0.4.2"))
    response = client.get("/runtime-config.js")
    assert response.status_code == 200
    assert response.text == 'window.__APP_VERSION__="0.4.2";\n'
    assert response.headers["content-type"].startswith("text/javascript")


def test_hotword_set_crud_and_export(monkeypatch, tmp_path) -> None:
    from vvoice.hotwords import HotwordStore

    monkeypatch.setattr("vvoice.main.hotword_store", HotwordStore(tmp_path))

    created = client.post(
        "/api/v1/hotwords",
        json={"name": "公司术语", "phrases": ["华为", "昇腾"]},
    )
    assert created.status_code == 201
    body = created.json()
    set_id = body["id"]
    assert body["phrase_count"] == 2
    assert [fmt["format"] for fmt in body["formats"]] == ["text", "qwen3", "zipformer"]

    imported = client.post(
        "/api/v1/hotwords/import",
        data={"name": "上传热词表"},
        files={"file": ("hotwords.txt", "华为\nsherpa-onnx\n".encode(), "text/plain")},
    )
    assert imported.status_code == 201
    assert imported.json()["phrases"] == ["华为", "sherpa-onnx"]

    listed = client.get("/api/v1/hotwords")
    assert {item["name"] for item in listed.json()} == {"公司术语", "上传热词表"}

    detail = client.get(f"/api/v1/hotwords/{set_id}")
    assert detail.status_code == 200
    assert detail.json()["phrases"] == ["华为", "昇腾"]

    patched = client.patch(f"/api/v1/hotwords/{set_id}", json={"phrases": ["V-Voice"], "name": "更新"})
    assert patched.status_code == 200
    assert patched.json()["phrases"] == ["V-Voice"]

    exported = client.get(f"/api/v1/hotwords/{set_id}/export", params={"format": "qwen3"})
    assert exported.status_code == 200
    assert exported.text == "V-Voice\n"
    assert exported.headers["content-disposition"].startswith("attachment")

    assert client.get(f"/api/v1/hotwords/{set_id}/export", params={"format": "whisper"}).status_code == 422
    assert client.get("/api/v1/hotwords/hw_missing").status_code == 404

    deleted = client.delete(f"/api/v1/hotwords/{set_id}")
    assert deleted.status_code == 200
    assert client.get(f"/api/v1/hotwords/{set_id}").status_code == 404


def test_hotword_set_validation_errors(monkeypatch, tmp_path) -> None:
    from vvoice.hotwords import HotwordStore

    monkeypatch.setattr("vvoice.main.hotword_store", HotwordStore(tmp_path))
    assert client.post("/api/v1/hotwords", json={"name": "空", "phrases": []}).status_code == 422
    assert (
        client.post(
            "/api/v1/hotwords/import",
            data={"name": "坏文件"},
            files={"file": ("hotwords.txt", b"\xff", "text/plain")},
        ).status_code
        == 422
    )


def test_transcription_merges_saved_hotword_sets_with_request_input(monkeypatch, tmp_path) -> None:
    from vvoice.hotwords import HotwordStore

    store = HotwordStore(tmp_path)
    saved = store.create("公司术语", ["华为", "昇腾"])
    monkeypatch.setattr("vvoice.main.hotword_store", store)
    monkeypatch.setattr("vvoice.main.decode_audio", lambda data, name: (np.zeros(8), 16000))
    captured = {}

    def fake_transcribe(model, samples, rate, language, task, hotwords, hotwords_score):
        captured.update(model=model, hotwords=hotwords, hotwords_score=hotwords_score)
        return {"text": "ok"}

    monkeypatch.setattr("vvoice.main.transcribe", fake_transcribe)
    response = client.post(
        "/v1/audio/transcriptions",
        data={
            "model": "qwen3-asr-0.6b",
            "hotwords": "昇腾,V-Voice",
            "hotwords_set": saved["id"],
            "response_format": "verbose_json",
        },
        files={"file": ("sample.wav", b"audio", "audio/wav")},
    )
    assert response.status_code == 200
    assert captured["hotwords"] == ["华为", "昇腾", "V-Voice"]
    result = response.json()
    assert result["hotwords"]["sets"] == [{"id": saved["id"], "name": "公司术语"}]
    assert result["hotwords"]["applied"] is True

    unknown = client.post(
        "/v1/audio/transcriptions",
        data={"model": "qwen3-asr-0.6b", "hotwords_set": "hw_missing"},
        files={"file": ("sample.wav", b"audio", "audio/wav")},
    )
    assert unknown.status_code == 422
