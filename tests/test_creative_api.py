from fastapi.testclient import TestClient
import numpy as np

from vvoice import main
from vvoice.creative import models

client = TestClient(main.app)


def test_creative_capabilities_match_native_variants():
    rows = {row["key"]: row for row in models()}
    assert "voice_cloning" in rows["audiocpp-qwen3-tts-base-0.6b-q8"]["capabilities"]
    assert rows["audiocpp-qwen3-tts-voicedesign-q8"]["capabilities"] == ["voice_design"]
    assert "emotion_control" in rows["audiocpp-index-2.5-q8"]["capabilities"]
    assert "Vivian" in rows["audiocpp-qwen3-tts-customvoice-q8"]["voices"]
    assert all(row["modelscope_repo"].startswith("vivibit/") for row in rows.values())


def test_creative_discovery_is_dynamic_and_public(monkeypatch):
    rows = models(include_non_speech=True)
    ready = True

    async def listed():
        return [{**row, "status": "ready" if ready else "not_installed"} for row in rows]

    monkeypatch.setattr(main, "list_models", listed)
    result = client.get("/api/v1/discovery").json()["models"]
    index = next(row for row in result if row["id"] == "audiocpp-index-2.5-q8")
    assert index["endpoints"] == ["audio/speech"]
    assert "audiocpp-sheetsage2-orig" not in {row["id"] for row in result}
    assert "audiocpp-lyric-align-q8" not in {row["id"] for row in result}
    assert next(row for row in rows if row["key"] == "audiocpp-sheetsage2-orig")["capabilities"] == ["midi"]
    assert "emotion_control" in index["capabilities"]
    assert index["voices"]["endpoint"].startswith("/v1/audio/voices?")
    ready = False
    assert client.get("/api/v1/discovery").json()["models"] == []


def test_standard_speech_preserves_creative_extensions(monkeypatch):
    captured = {}

    def synthesize(model, text, voice, speed, language, **options):
        captured.update(model=model, text=text, voice=voice, **options)
        return np.zeros(32, dtype=np.float32), 24000

    monkeypatch.setattr(main, "synthesize", synthesize)
    payload = {"model": "audiocpp-index-2.5-q8", "input": "Hello", "response_format": "wav",
               "reference_audio": "UklGRg==", "reference_text": "Reference", "emotion_text": "calm",
               "emotion_strength": 0.4}
    response = client.post("/v1/audio/speech", json=payload)
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert captured["reference_audio"] == payload["reference_audio"]
    assert captured["emotion_text"] == "calm"
    assert captured["emotion_strength"] == 0.4
    schema = client.get("/openapi.json").json()["components"]["schemas"]["SpeechRequest"]["properties"]
    assert all(key in schema for key in ("reference_audio", "reference_text", "voice_description", "emotion_text"))
