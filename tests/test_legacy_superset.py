"""迁移门禁：原 V-Voice 0.0.12 的描述符及公开接口不允许被精选目录取代。"""
import hashlib
import json
from pathlib import Path

from vvoice.catalog import catalog
from vvoice.main import app


def test_every_legacy_descriptor_is_retained_unchanged():
    source = Path(__file__).resolve().parents[1] / "catalog" / "models.json"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == "3f5eaa724ca756ead7f711096a41a2075cba9e935cea1952138cb12241e8c835"
    legacy = json.loads(source.read_text())["models"]
    current = {row["key"]: row for row in catalog()}
    for old in legacy:
        assert current[old["key"]] == old
    assert set(current) > {row["key"] for row in legacy}


def test_legacy_public_routes_remain_available():
    actual = {(method, route.path) for route in app.routes for method in getattr(route, "methods", [])}
    expected = {
        ("GET", "/v1/models"), ("GET", "/api/v1/discovery"),
        ("POST", "/v1/audio/transcriptions"), ("POST", "/v1/audio/translations"),
        ("POST", "/v1/audio/speech"), ("GET", "/v1/audio/voices"),
        ("POST", "/v1/audio/streaming/transcriptions"),
        ("POST", "/v1/audio/speakers/identify"), ("POST", "/v1/audio/speakers/verify"),
        ("GET", "/api/v1/hotwords"), ("GET", "/api/v1/speakers"),
        ("GET", "/api/v1/models"), ("POST", "/transcribe"),
    }
    assert expected <= actual


def test_all_downloadable_yovoice_speech_precisions_are_projected():
    root = Path(__file__).resolve().parents[1]
    upstream = json.loads((root / "internal/catalog/catalog.json").read_text())
    expected = {"audiocpp-" + row["id"] for row in upstream
                if row.get("task") not in {"gen", "instrument"}}
    assert expected <= {row["key"] for row in catalog()}


def test_creator_management_also_includes_music_and_soundfonts():
    from vvoice.creative import models
    rows = models(include_non_speech=True)
    assert len(rows) == 38
    assert {"tts", "music", "soundfont"} <= {row["kind"] for row in rows}
    assert sum(row["import_required"] for row in rows) == 2
