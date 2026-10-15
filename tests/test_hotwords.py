from __future__ import annotations

import json

import pytest

from vvoice.hotwords import (
    MAX_HOTWORDS,
    MAX_HOTWORDS_FILE_BYTES,
    HotwordStore,
    clean_phrases,
    merge_phrases,
    parse_hotwords,
    render_hotword_format,
)


def test_hotwords_merge_inline_and_utf8_file_with_stable_deduplication() -> None:
    assert parse_hotwords("华为, V-Voice\n昇腾", "昇腾\nsherpa-onnx\n".encode()) == [
        "华为",
        "V-Voice",
        "昇腾",
        "sherpa-onnx",
    ]


def test_hotwords_reject_oversized_or_non_utf8_files() -> None:
    with pytest.raises(ValueError, match="exceeds"):
        parse_hotwords(file_data=b"a" * (MAX_HOTWORDS_FILE_BYTES + 1))
    with pytest.raises(ValueError, match="UTF-8"):
        parse_hotwords(file_data=b"\xff")
    with pytest.raises(ValueError, match=f"at most {MAX_HOTWORDS}"):
        parse_hotwords(",".join(f"word-{index}" for index in range(MAX_HOTWORDS + 1)))


def test_clean_phrases_keeps_commas_inside_saved_phrases() -> None:
    assert clean_phrases([" 华为 ", "", "华为", "AT&T, Inc."]) == ["华为", "AT&T, Inc."]


def test_merge_phrases_deduplicates_sets_and_request_input_with_limits() -> None:
    merged = merge_phrases(["华为", "昇腾"], ["昇腾", "V-Voice"])
    assert merged == ["华为", "昇腾", "V-Voice"]
    with pytest.raises(ValueError, match="at most"):
        merge_phrases([f"w{index}" for index in range(MAX_HOTWORDS)], ["extra"])


def test_render_hotword_formats_match_model_expectations() -> None:
    phrases = ["华为", "昇腾"]
    assert render_hotword_format(phrases, "qwen3") == "华为,昇腾\n"
    assert render_hotword_format(phrases, "zipformer") == "华为\n昇腾\n"
    assert render_hotword_format(phrases, "text") == "华为\n昇腾\n"
    with pytest.raises(ValueError, match="unsupported"):
        render_hotword_format(phrases, "whisper")


def test_hotword_store_crud_materializes_model_format_tables(tmp_path) -> None:
    store = HotwordStore(tmp_path)

    created = store.create("公司术语", ["华为", "昇腾"])
    assert created["phrase_count"] == 2
    assert [fmt["format"] for fmt in created["formats"]] == ["text", "qwen3", "zipformer"]
    artifact = tmp_path / "hotwords-artifacts" / created["id"]
    assert json.loads((tmp_path / "hotwords.json").read_text(encoding="utf-8"))["sets"][0]["name"] == "公司术语"
    assert (artifact / "qwen3.txt").read_text(encoding="utf-8") == "华为,昇腾\n"
    assert (artifact / "zipformer.txt").read_text(encoding="utf-8") == "华为\n昇腾\n"

    updated = store.update(created["id"], name="更新术语", phrases=["V-Voice"])
    assert updated["name"] == "更新术语"
    assert updated["phrases"] == ["V-Voice"]
    assert (artifact / "qwen3.txt").read_text(encoding="utf-8") == "V-Voice\n"

    assert store.get(created["id"])["name"] == "更新术语"
    assert [item["id"] for item in store.list_sets()] == [created["id"]]
    assert store.update("hw_missing", phrases=["x"]) is None

    assert store.delete(created["id"]) is True
    assert store.list_sets() == []
    assert not artifact.exists()
    assert store.delete(created["id"]) is False


def test_hotword_store_rejects_empty_and_oversized_sets(tmp_path) -> None:
    store = HotwordStore(tmp_path)
    with pytest.raises(ValueError, match="at least one"):
        store.create("空", [])
    with pytest.raises(ValueError, match="at most"):
        store.create("超量", [f"word-{index}" for index in range(MAX_HOTWORDS + 1)])
    with pytest.raises(ValueError, match="name is required"):
        store.create("  ", ["华为"])
    assert store.list_sets() == []
