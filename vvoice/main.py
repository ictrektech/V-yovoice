from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Literal

import numpy as np
from fastapi import Body, FastAPI, File, Form, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from .audio import StreamingPcmDecoder, decode_audio, encode_audio
from .catalog import catalog, find_model
from .config import settings
from .hotwords import (
    HOTWORD_SET_FORMATS,
    HotwordStore,
    MAX_HOTWORDS_FILE_BYTES,
    merge_phrases,
    parse_hotwords,
    render_hotword_format,
)
from .modelhub import cancel_model, list_models, pull_model
from .runtime import (
    detect_provider,
    extract_embedding,
    feed_online_chunk,
    finish_online_stream,
    online_session,
    registry,
    synthesize,
    transcribe,
)
from .speakers import DEFAULT_IDENTIFY_THRESHOLD, SpeakerStore
from .transcript import normalize_transcript, subtitle
from .admission import AdmissionMiddleware, run_blocking, admit_model


app = FastAPI(title="V-Voice", version=__version__, description="Shared ASR and TTS APIs with ONNX and native audio.cpp inference")
if os.getenv("VVOICE_SCHEDULER_REQUIRED") == "true":
    app.add_middleware(AdmissionMiddleware)

hotword_store = HotwordStore(settings.data_dir)
speaker_store = SpeakerStore(settings.data_dir)


class SpeechRequest(BaseModel):
    model: str = Field(description="Ready TTS model key from /api/v1/discovery")
    input: str = Field(min_length=1, max_length=20000, description="Text to synthesize")
    voice: str = Field("default", description="Voice ID returned by /v1/audio/voices for this model")
    response_format: Literal["mp3", "opus", "aac", "flac", "wav", "pcm"] = Field(
        "mp3", description="Binary output audio format"
    )
    speed: float = Field(1.0, ge=0.25, le=4.0, description="Speech speed multiplier")
    language: str = Field("", description="Language code; empty uses the model/voice default")
    reference_audio: str = Field("", max_length=28_000_000, description="audio.cpp only: base64 reference audio; not a server file path")
    reference_text: str = Field("", max_length=2000, description="audio.cpp only: reference audio transcript")
    voice_description: str = Field("", max_length=500, description="audio.cpp only: voice design instruction")
    emotion_text: str = Field("", max_length=500, description="IndexTTS only: emotion instruction; requires emotion_control capability")
    emotion_strength: float = Field(0.6, ge=0, le=1, description="IndexTTS only: emotion strength")


@app.get("/health")
async def health():
    if os.getenv("VVOICE_STUDIO_ENABLED") == "true":
        import httpx
        try:
            async with httpx.AsyncClient(timeout=2) as client:
                response = await client.get("http://127.0.0.1:7080/health")
                response.raise_for_status()
        except httpx.HTTPError:
            raise HTTPException(503, "Creative workbench unavailable") from None
    return {"status": "ok", "version": settings.app_version, "provider": detect_provider()}


@app.get("/runtime-config.js", include_in_schema=False)
@app.get("/service/runtime-config.js", include_in_schema=False)
async def runtime_config():
    """Runtime-injected frontend config; APP_VERSION arrives as a container env var."""
    body = f'window.__APP_VERSION__="{settings.app_version}";\n'
    return Response(body, media_type="text/javascript")


@app.get("/ready")
async def ready():
    return {"ready": True, "model_hub_root": settings.modelhub_root.is_dir()}


@app.get("/api/v1/about")
async def about():
    return {
        "app_id": settings.app_id,
        "app_version": settings.app_version,
        "profile": settings.profile,
        "provider": detect_provider(),
        "port": settings.port,
        "supported_asr_families": 20,
        "supported_tts_families": 7,
        "supported_speaker_families": 1,
        "streaming_asr": True,
        "max_loaded_models": settings.max_loaded_models,
        "max_concurrent_inference": settings.max_concurrent_inference,
        "max_concurrent_per_model": settings.max_concurrent_per_model,
    }


@app.get("/api/v1/discovery")
async def discovery():
    rows = await list_models()
    models = []
    for row in rows:
        if row["status"] != "ready":
            continue
        kind = row["kind"]
        if kind == "speaker":
            models.append({
                "id": row["key"],
                "object": "model",
                "owned_by": "v-voice",
                "kind": "speaker",
                "capabilities": ["speaker", "speaker-identification", "speaker-verification"],
                "endpoints": ["audio/speakers", "audio/speakers/identify", "audio/speakers/verify"],
                "languages": row.get("languages") or [],
            })
            continue
        streaming = bool(row.get("streaming"))
        endpoints = (
            (["audio/transcriptions"] + (["audio/translations"] if row.get("translation", True) else [])) if kind == "asr" else ["audio/speech"]
        )
        capabilities = [
            kind,
            "transcription" if kind == "asr" else "speech",
            *(row.get("capabilities") or []),
            *(["hotwords"] if row.get("hotwords", {}).get("supported") else []),
            *(["streaming"] if streaming else []),
            *(
                ["word_timestamps", "segment_timestamps"]
                if row.get("timestamps", {}).get("word")
                else []
            ),
        ]
        if streaming:
            endpoints += ["audio/streaming/transcriptions", "audio/streaming/ws"]
        model = {
            "id": row["key"],
            "object": "model",
            "owned_by": "v-voice",
            "kind": kind,
            "capabilities": capabilities,
            "endpoints": endpoints,
            **({"hotwords": row["hotwords"]} if row.get("hotwords", {}).get("supported") else {}),
            **({"timestamps": row["timestamps"]} if row.get("timestamps") else {}),
            **(
                {
                    "streaming": {
                        "supported": True,
                        "transports": ["http-chunked", "websocket"],
                        "hotwords": bool(row.get("hotwords", {}).get("supported")),
                    }
                }
                if streaming
                else {}
            ),
            **(
                {
                    "voices": {
                        "endpoint": f"/v1/audio/voices?model={row['key']}",
                        "default": "default",
                        "count": len(row.get("voices") or {}),
                    }
                }
                if kind == "tts"
                else {}
            ),
        }
        models.append(model)
    return {
        "service_id": "v-voice",
        "name": "V-Voice",
        "protocol": "openai",
        "visibility": "public",
        "multi_tenant": False,
        "authentication": "none",
        "base_url": "http://v-voice-backend:7070/v1",
        "health_path": "/health",
        "models": models,
    }


@app.get("/api/v1/models")
async def managed_models():
    return [{**row, "loaded": registry.is_loaded(row["key"])} for row in await list_models()]


@app.post("/api/v1/models/{key}/pull", status_code=202)
async def pull(key: str, force: bool = False):
    try:
        return await pull_model(key, force)
    except KeyError:
        raise HTTPException(status_code=404, detail="model not found") from None
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Model Hub pull failed: {exc}") from exc


@app.post("/api/v1/models/{key}/stop")
async def stop(key: str):
    try:
        return await cancel_model(key)
    except KeyError:
        raise HTTPException(status_code=404, detail="model not found") from None
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Model Hub cancel failed: {exc}") from exc


@app.post("/api/v1/models/{key}/unload")
async def unload(key: str):
    registry.unload(key)
    return {"status": "unloaded", "model": key}


class HotwordSetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64, description="Display name of the hotword set")
    phrases: list[str] = Field(default_factory=list, description="Phrases; preferred over phrases_text when both are sent")
    phrases_text: str = Field("", max_length=8192, description="Comma/newline-separated phrases; used when phrases is empty")


class HotwordSetUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=64)
    phrases: list[str] | None = None


@app.get("/api/v1/hotwords", response_model=None)
async def list_hotword_sets():
    """List saved hotword sets with their derived per-model format tables."""
    return hotword_store.list_sets()


@app.post("/api/v1/hotwords", status_code=201)
async def create_hotword_set(payload: HotwordSetCreate):
    phrases = payload.phrases if payload.phrases else parse_hotwords(payload.phrases_text)
    try:
        return hotword_store.create(payload.name, phrases)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/v1/hotwords/import", status_code=201)
async def import_hotword_set(
    name: str = Form(..., description="Display name of the hotword set"),
    file: UploadFile = File(..., description="UTF-8 hotword table, one phrase per line"),
):
    data = await file.read(MAX_HOTWORDS_FILE_BYTES + 1)
    try:
        phrases = parse_hotwords("", data)
        return hotword_store.create(name, phrases)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/v1/hotwords/{set_id}")
async def get_hotword_set(set_id: str):
    item = hotword_store.get(set_id)
    if item is None:
        raise HTTPException(status_code=404, detail="hotword set not found")
    return hotword_store.describe(item)


@app.patch("/api/v1/hotwords/{set_id}")
async def update_hotword_set(set_id: str, payload: HotwordSetUpdate):
    try:
        item = hotword_store.update(set_id, payload.name, payload.phrases)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if item is None:
        raise HTTPException(status_code=404, detail="hotword set not found")
    return item


@app.delete("/api/v1/hotwords/{set_id}")
async def delete_hotword_set(set_id: str):
    if not hotword_store.delete(set_id):
        raise HTTPException(status_code=404, detail="hotword set not found")
    return {"status": "deleted", "id": set_id}


@app.get("/api/v1/hotwords/{set_id}/export")
async def export_hotword_set(set_id: str, format: str = Query("text", description="text, qwen3, or zipformer")):
    item = hotword_store.get(set_id)
    if item is None:
        raise HTTPException(status_code=404, detail="hotword set not found")
    if format not in HOTWORD_SET_FORMATS:
        raise HTTPException(status_code=422, detail=f"format must be one of {list(HOTWORD_SET_FORMATS)}")
    body = render_hotword_format(item["phrases"], format)
    return PlainTextResponse(
        body,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{set_id}-{format}.txt"'},
    )


@app.get("/v1/models")
async def openai_models():
    return {
        "object": "list",
        "data": (await discovery())["models"],
    }


async def _transcription(
    file: UploadFile,
    model: str,
    language: str,
    response_format: str,
    task: str,
    hotwords: str = "",
    hotwords_file: UploadFile | None = None,
    hotwords_score: float | None = None,
    hotwords_set: list[str] | None = None,
    timestamp_granularities: list[str] | None = None,
    speaker_model: str = "",
    speaker_threshold: float | None = None,
):
    if file.size is not None and file.size > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail="audio file is too large")
    try:
        item = find_model(model, "asr")
        await admit_model(model)
        data = await file.read(settings.max_upload_mb * 1024 * 1024 + 1)
        if len(data) > settings.max_upload_mb * 1024 * 1024:
            raise HTTPException(status_code=413, detail="audio file is too large")
        hotword_config = item.get("hotwords") or {}
        set_phrases: list[str] = []
        applied_sets: list[dict] = []
        for set_id in hotwords_set or []:
            saved = hotword_store.get(set_id)
            if saved is None:
                raise ValueError(f"unknown hotwords_set: {set_id}")
            set_phrases.extend(saved["phrases"])
            applied_sets.append({"id": saved["id"], "name": saved["name"]})
        hotwords_requested = bool(
            hotwords.strip() or hotwords_file is not None or hotwords_score is not None or applied_sets
        )
        hotwords_file_data = None
        if hotwords_file is not None and hotword_config.get("supported"):
            hotwords_file_data = await hotwords_file.read(MAX_HOTWORDS_FILE_BYTES + 1)
        if hotword_config.get("supported"):
            phrases = merge_phrases(set_phrases, parse_hotwords(hotwords, hotwords_file_data))
        else:
            phrases = []
        effective_score = hotwords_score if hotword_config.get("score") else None
        if effective_score is not None and not 0.0 <= effective_score <= 10.0:
            raise ValueError("hotwords_score must be between 0 and 10")
        invalid_granularities = set(timestamp_granularities or []) - {"word", "segment"}
        if invalid_granularities:
            raise ValueError(f"unsupported timestamp granularity: {sorted(invalid_granularities)}")
        samples, rate = await run_blocking(decode_audio, data, file.filename or "audio")
        result = await run_blocking(
            transcribe, model, samples, rate, language, task, phrases, effective_score
        )
        result["hotwords"] = {
            "requested": hotwords_requested,
            "supported": bool(hotword_config.get("supported")),
            "applied": bool(phrases),
            "sets": applied_sets,
            "score_applied": effective_score if phrases else None,
            "ignored": hotwords_requested and not phrases,
        }
        attribution = _speaker_block(samples, rate, speaker_model, speaker_threshold)
        if attribution is not None:
            result["speaker"] = attribution
    except KeyError:
        raise HTTPException(status_code=404, detail="ASR model not found") from None
    except FileNotFoundError as exc:
        raise HTTPException(status_code=409, detail=f"model is not ready: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=500, detail=f"transcription failed: {exc}") from exc
    if response_format == "text":
        return PlainTextResponse(result["text"])
    if response_format in {"srt", "vtt"}:
        return PlainTextResponse(subtitle(result, response_format))
    if response_format == "json":
        return {"text": result["text"]}
    return JSONResponse(result)


ASR_RESPONSES = {
    404: {"description": "ASR model key does not exist or is not an ASR model"},
    409: {"description": "Model exists but its files are not ready"},
    413: {"description": "Audio upload is larger than the configured limit"},
    422: {"description": "Invalid field, hotword file, hotword limit, score, or model capability"},
    500: {"description": "Audio decoding or inference failed"},
}


@app.post("/v1/audio/transcriptions", responses=ASR_RESPONSES)
async def transcriptions(
    file: UploadFile = File(..., description="Audio file to recognize"),
    model: str = Form(..., description="Ready ASR model key from /api/v1/discovery"),
    language: str = Form("", description="Language code; empty lets the model decide"),
    response_format: str = Form("json", description="json, verbose_json, text, srt, or vtt"),
    hotwords: str = Form("", description="Comma/newline-separated phrases; SeACo, Qwen3-ASR or Zipformer"),
    hotwords_file: UploadFile | None = File(None, description="UTF-8 text, one phrase per line"),
    hotwords_score: float | None = Form(
        None, description="Zipformer contextual-bias score from 0 to 10; ignored by other models"
    ),
    hotwords_set: list[str] | None = Form(
        None,
        description="Repeatable saved hotword set id from /api/v1/hotwords; merged with hotwords and hotwords_file",
    ),
    timestamp_granularities: list[str] | None = Form(
        None,
        alias="timestamp_granularities[]",
        description="Repeat with word and/or segment; verbose_json includes every available timestamp granularity",
    ),
    speaker_model: str = Form(
        "", description="Optional ready speaker model key; adds a speaker attribution block to verbose_json"
    ),
    speaker_threshold: float | None = Form(
        None, ge=0.0, le=1.0, description="Cosine similarity threshold for the speaker block; default 0.6"
    ),
):
    return await _transcription(
        file, model, language, response_format, "transcribe", hotwords, hotwords_file, hotwords_score,
        hotwords_set, timestamp_granularities, speaker_model, speaker_threshold,
    )


@app.post("/v1/audio/translations", responses=ASR_RESPONSES)
async def translations(
    file: UploadFile = File(..., description="Audio file to translate"),
    model: str = Form(..., description="Ready ASR model key from /api/v1/discovery"),
    language: str = Form("", description="Input language code; empty lets the model decide"),
    response_format: str = Form("json", description="json, verbose_json, text, srt, or vtt"),
    hotwords: str = Form("", description="Comma/newline-separated phrases; SeACo, Qwen3-ASR or Zipformer"),
    hotwords_file: UploadFile | None = File(None, description="UTF-8 text, one phrase per line"),
    hotwords_score: float | None = Form(
        None, description="Zipformer contextual-bias score from 0 to 10; ignored by other models"
    ),
    hotwords_set: list[str] | None = Form(
        None,
        description="Repeatable saved hotword set id from /api/v1/hotwords; merged with hotwords and hotwords_file",
    ),
    timestamp_granularities: list[str] | None = Form(
        None,
        alias="timestamp_granularities[]",
        description="Repeat with word and/or segment; verbose_json includes every available timestamp granularity",
    ),
    speaker_model: str = Form(
        "", description="Optional ready speaker model key; adds a speaker attribution block to verbose_json"
    ),
    speaker_threshold: float | None = Form(
        None, ge=0.0, le=1.0, description="Cosine similarity threshold for the speaker block; default 0.6"
    ),
):
    return await _transcription(
        file, model, language, response_format, "translate", hotwords, hotwords_file, hotwords_score,
        hotwords_set, timestamp_granularities, speaker_model, speaker_threshold,
    )


async def _streaming_hotwords(model: str, hotwords: str, hotwords_set: list[str] | None, hotwords_score: float | None):
    """Validate a streaming model and merge its hotword inputs."""
    item = find_model(model, "asr")
    if not item.get("streaming"):
        raise HTTPException(status_code=422, detail=f"model {model} does not support streaming recognition")
    hotword_config = item.get("hotwords") or {}
    set_phrases: list[str] = []
    applied_sets: list[dict] = []
    for set_id in hotwords_set or []:
        saved = hotword_store.get(set_id)
        if saved is None:
            raise HTTPException(status_code=422, detail=f"unknown hotwords_set: {set_id}")
        set_phrases.extend(saved["phrases"])
        applied_sets.append({"id": saved["id"], "name": saved["name"]})
    phrases = merge_phrases(set_phrases, parse_hotwords(hotwords)) if hotword_config.get("supported") else []
    effective_score = hotwords_score if hotword_config.get("score") else None
    if effective_score is not None and not 0.0 <= effective_score <= 10.0:
        raise HTTPException(status_code=422, detail="hotwords_score must be between 0 and 10")
    return item, phrases, effective_score, applied_sets


@app.post("/v1/audio/streaming/transcriptions", responses=ASR_RESPONSES)
async def streaming_transcriptions(
    request: Request,
    model: str = Query(..., description="Ready streaming ASR model key from /api/v1/discovery"),
    language: str = Query("", description="Kept for contract symmetry; streaming models auto-detect"),
    format: str = Query("pcm", description="pcm (raw s16le mono), wav (uncompressed mono RIFF), or auto (buffered, decoded at end)"),
    sample_rate: int = Query(16000, gt=0, le=192000, description="Sample rate for format=pcm; wav uses its header"),
    response_format: str = Query("verbose_json", description="verbose_json, json, or text"),
    hotwords: str = Query("", description="One-shot comma/newline-separated phrases for hotword-capable streaming models"),
    hotwords_set: list[str] | None = Query(None, description="Repeatable saved hotword set id from /api/v1/hotwords"),
    hotwords_score: float | None = Query(None, description="Contextual-bias score from 0 to 10; streaming Zipformer only"),
    speaker_model: str = Query("", description="Optional ready speaker model key; adds a speaker attribution block to the final response"),
    speaker_threshold: float | None = Query(None, ge=0.0, le=1.0, description="Cosine similarity threshold for the speaker block; default 0.6"),
):
    """Realtime streaming transcription over a chunked HTTP request body.

    The body is audio transmitted incrementally; V-Voice feeds every chunk into
    the OnlineRecognizer as it arrives and returns the final transcript when the
    body ends. Use ``format=pcm`` or ``wav`` for true incremental decoding;
    ``auto`` buffers the whole body and decodes once.
    """
    try:
        item, phrases, effective_score, applied_sets = await _streaming_hotwords(
            model, hotwords, hotwords_set, hotwords_score
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="ASR model not found") from None
    except FileNotFoundError as exc:
        raise HTTPException(status_code=409, detail=f"model is not ready: {exc}") from exc

    if format not in {"pcm", "wav", "auto"}:
        raise HTTPException(status_code=422, detail="format must be pcm, wav, or auto")
    decoder = StreamingPcmDecoder(format, sample_rate)
    total = 0
    chunks: list = []
    try:
        with online_session(model, phrases, effective_score) as (recognizer, stream):
            async for chunk in request.stream():
                for samples in decoder.feed(chunk):
                    total += len(samples)
                    chunks.append(samples)
                    await run_blocking(
                        feed_online_chunk, recognizer, stream, samples, decoder.rate or sample_rate
                    )
            tail = decoder.flush()
            if tail is not None:
                samples, tail_rate = tail
                if len(samples):
                    total += len(samples)
                    chunks.append(samples)
                    await run_blocking(
                        feed_online_chunk, recognizer, stream, samples, tail_rate or sample_rate
                    )
            raw = await run_blocking(finish_online_stream, recognizer, stream)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=409, detail=f"model is not ready: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=500, detail=f"streaming transcription failed: {exc}") from exc

    duration = total / (decoder.rate or sample_rate) if sample_rate > 0 else 0.0
    result = normalize_transcript(raw, duration)
    result["streaming"] = True
    result["hotwords"] = {
        "requested": bool(phrases or applied_sets or hotwords_score is not None),
        "supported": bool((item.get("hotwords") or {}).get("supported")),
        "applied": bool(phrases),
        "sets": applied_sets,
        "score_applied": effective_score if phrases else None,
        "ignored": not phrases and bool(hotwords or applied_sets),
    }
    attribution = _speaker_block(np.concatenate(chunks), decoder.rate or sample_rate, speaker_model, speaker_threshold) if chunks else None
    if attribution is not None:
        result["speaker"] = attribution
    if response_format == "text":
        return PlainTextResponse(result["text"])
    if response_format == "json":
        return {"text": result["text"]}
    return JSONResponse(result)


@app.websocket("/v1/audio/streaming/ws")
async def streaming_ws(
    websocket: WebSocket,
    model: str = Query(..., description="Ready streaming ASR model key"),
    format: str = Query("pcm", description="pcm (raw s16le mono) or wav; partial results require endpoint-enabled models"),
    sample_rate: int = Query(16000, gt=0, le=192000),
    hotwords: str = Query(""),
    hotwords_set: list[str] | None = Query(None),
    hotwords_score: float | None = Query(None),
    speaker_model: str = Query("", description="Optional speaker model key; the final message gains a speaker attribution block"),
    speaker_threshold: float | None = Query(None, ge=0.0, le=1.0),
):
    """Realtime streaming ASR over WebSocket.

    Protocol: send binary audio frames (raw s16le mono PCM unless format=wav),
    receive JSON ``{"type": "partial", "text": ..., "is_endpoint": ...}`` while
    streaming; send the text frame ``{"type": "finish"}`` (or close) to receive
    ``{"type": "final", "text": ..., "duration": ...}``. Errors close the socket
    with code 4404/4409/4422/4500 and a JSON ``{"type": "error", "detail": ...}``.
    """
    await websocket.accept()
    try:
        try:
            item, phrases, effective_score, _ = await _streaming_hotwords(model, hotwords, hotwords_set, hotwords_score)
            if speaker_model:
                find_model(speaker_model, "speaker")
        except KeyError:
            await websocket.send_json({"type": "error", "detail": f"model not found: {speaker_model or model}"})
            await websocket.close(code=4404)
            return
        except HTTPException as exc:
            await websocket.send_json({"type": "error", "detail": exc.detail})
            await websocket.close(code=4400 + (exc.status_code % 100))
            return
        if format not in {"pcm", "wav"}:
            await websocket.send_json({"type": "error", "detail": "format must be pcm or wav"})
            await websocket.close(code=4422)
            return
        decoder = StreamingPcmDecoder(format, sample_rate)
        finished = False
        chunks: list = []
        with online_session(model, phrases, effective_score) as (recognizer, stream):
            while not finished:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    break
                if message.get("bytes") is not None:
                    partial = None
                    for samples in decoder.feed(message["bytes"]):
                        chunks.append(samples)
                        partial = await run_blocking(
                            feed_online_chunk, recognizer, stream, samples, decoder.rate or sample_rate, True
                        )
                    if partial and partial["text"]:
                        await websocket.send_json({
                            "type": "partial",
                            "text": partial["text"],
                            "is_endpoint": partial["is_endpoint"],
                        })
                    continue
                text = message.get("text")
                if text is None:
                    continue
                try:
                    control = json.loads(text)
                except json.JSONDecodeError:
                    control = {"type": text}
                if control.get("type") == "finish":
                    tail = decoder.flush()
                    if tail is not None and len(tail[0]):
                        await run_blocking(
                            feed_online_chunk, recognizer, stream, tail[0], tail[1] or sample_rate
                        )
                    raw = await run_blocking(finish_online_stream, recognizer, stream)
                    final = {"type": "final", **raw}
                    attribution = _speaker_block(np.concatenate(chunks), decoder.rate or sample_rate, speaker_model, speaker_threshold) if chunks else None
                    if attribution is not None:
                        final["speaker"] = attribution
                    await websocket.send_json(final)
                    finished = True
    except WebSocketDisconnect:
        return
    except Exception as exc:
        try:
            await websocket.send_json({"type": "error", "detail": str(exc)})
            await websocket.close(code=4500)
        except Exception:
            pass
        return
    try:
        await websocket.close()
    except Exception:
        pass


async def _decode_upload(file: UploadFile, filename: str = "audio") -> tuple:
    data = await file.read(settings.max_upload_mb * 1024 * 1024 + 1)
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail="audio file is too large")
    return await run_blocking(decode_audio, data, file.filename or filename)


def _speaker_block(samples, sample_rate: int, speaker_model: str, threshold: float | None):
    """Attach speaker attribution to a transcription; OpenAI has no equivalent
    standard, so this is exposed as the optional speaker_model parameter."""
    if not speaker_model:
        return None
    try:
        find_model(speaker_model, "speaker")
    except KeyError:
        raise HTTPException(status_code=404, detail=f"speaker model not found: {speaker_model}") from None
    effective_threshold = DEFAULT_IDENTIFY_THRESHOLD if threshold is None else float(threshold)
    if not 0.0 <= effective_threshold <= 1.0:
        raise HTTPException(status_code=422, detail="speaker_threshold must be between 0 and 1")
    block = {"model": speaker_model, "threshold": effective_threshold, "identified": False, "speaker": None, "score": 0.0, "ranked": []}
    try:
        embedding = extract_embedding(speaker_model, samples, sample_rate)
        ranked = speaker_store.rank(embedding, limit=5)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=409, detail=f"speaker model is not ready: {exc}") from exc
    except Exception as exc:  # keep the transcription result; report attribution failure inline
        block["error"] = str(exc)
        return block
    best = ranked[0] if ranked else None
    identified = bool(best and best["score"] >= effective_threshold)
    block.update({
        "identified": identified,
        "speaker": best if identified else None,
        "score": best["score"] if best else 0.0,
        "ranked": ranked,
    })
    return block


@app.get("/api/v1/speakers")
async def managed_speakers():
    """List enrolled voiceprints (management plane)."""
    return speaker_store.list_speakers()


@app.post("/api/v1/speakers", status_code=201)
async def enroll_speaker(
    name: str = Form(..., description="Display name of the enrolled speaker"),
    file: UploadFile = File(..., description="Enrollment audio (speech from this speaker)"),
    model: str = Form("speaker-campplus-zh-en", description="Ready speaker model key"),
):
    """Enroll a speaker voiceprint from uploaded audio."""
    try:
        find_model(model, "speaker")
        await admit_model(model)
        samples, rate = await _decode_upload(file)
        embedding = await run_blocking(extract_embedding, model, samples, rate)
        return speaker_store.create(name, embedding, model)
    except KeyError:
        raise HTTPException(status_code=404, detail="speaker model not found") from None
    except FileNotFoundError as exc:
        raise HTTPException(status_code=409, detail=f"model is not ready: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=500, detail=f"speaker enrollment failed: {exc}") from exc


@app.delete("/api/v1/speakers/{speaker_id}")
async def delete_speaker(speaker_id: str):
    if not speaker_store.delete(speaker_id):
        raise HTTPException(status_code=404, detail="speaker not found")
    return {"status": "deleted", "id": speaker_id}


@app.get("/v1/audio/speakers")
async def audio_speakers(model: str = Query("speaker-campplus-zh-en", description="Ready speaker model key")):
    """Public list of enrolled voiceprints for dependent clients."""
    try:
        find_model(model, "speaker")
    except KeyError:
        raise HTTPException(status_code=404, detail="speaker model not found") from None
    speakers = speaker_store.list_speakers()
    return {"object": "list", "model": model, "default_threshold": DEFAULT_IDENTIFY_THRESHOLD, "speakers": speakers, "data": speakers}


@app.post("/v1/audio/speakers/identify")
async def speakers_identify(
    file: UploadFile = File(..., description="Audio to attribute to an enrolled speaker"),
    model: str = Form("speaker-campplus-zh-en", description="Ready speaker model key"),
    threshold: float = Form(DEFAULT_IDENTIFY_THRESHOLD, ge=0.0, le=1.0, description="Cosine similarity threshold"),
):
    """Identify which enrolled speaker (if any) spoke in the audio."""
    try:
        find_model(model, "speaker")
        await admit_model(model)
        samples, rate = await _decode_upload(file)
        embedding = await run_blocking(extract_embedding, model, samples, rate)
        ranked = speaker_store.rank(embedding, limit=5)
    except KeyError:
        raise HTTPException(status_code=404, detail="speaker model not found") from None
    except FileNotFoundError as exc:
        raise HTTPException(status_code=409, detail=f"model is not ready: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=500, detail=f"speaker identification failed: {exc}") from exc
    best = ranked[0] if ranked else None
    identified = bool(best and best["score"] >= threshold)
    return {
        "object": "speaker.identification",
        "model": model,
        "threshold": threshold,
        "identified": identified,
        "speaker": best if identified else None,
        "score": best["score"] if best else 0.0,
        "ranked": ranked,
    }


@app.post("/v1/audio/speakers/verify")
async def speakers_verify(
    file: UploadFile = File(..., description="Audio to verify against a speaker"),
    speaker: str = Form(..., description="Enrolled speaker id or exact name"),
    model: str = Form("speaker-campplus-zh-en", description="Ready speaker model key"),
    threshold: float = Form(DEFAULT_IDENTIFY_THRESHOLD, ge=0.0, le=1.0, description="Cosine similarity threshold"),
):
    """Verify the audio against one enrolled speaker voiceprint."""
    enrolled = speaker_store.find(speaker)
    if enrolled is None:
        raise HTTPException(status_code=404, detail="speaker not found")
    try:
        find_model(model, "speaker")
        await admit_model(model)
        samples, rate = await _decode_upload(file)
        embedding = await run_blocking(extract_embedding, model, samples, rate)
        ranked = speaker_store.rank(embedding)
        match = next((row for row in ranked if row["id"] == enrolled["id"]), None)
        score = match["score"] if match else 0.0
    except KeyError:
        raise HTTPException(status_code=404, detail="speaker model not found") from None
    except FileNotFoundError as exc:
        raise HTTPException(status_code=409, detail=f"model is not ready: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=500, detail=f"speaker verification failed: {exc}") from exc
    return {
        "object": "speaker.verification",
        "model": model,
        "speaker": SpeakerStore.describe(enrolled),
        "threshold": threshold,
        "score": score,
        "verified": bool(score >= threshold),
    }


@app.post("/transcribe")
async def legacy_transcribe(
    audio: bytes = Body(..., media_type="application/octet-stream"),
    model: str = Query("sensevoice-int8"),
    lang: str = Query(""),
):
    try:
        find_model(model, "asr")
        await admit_model(model)
        samples, rate = await run_blocking(decode_audio, audio, "audio.bin")
        result = await run_blocking(transcribe, model, samples, rate, lang, "transcribe")
        return {"text": result["text"]}
    except KeyError:
        raise HTTPException(status_code=404, detail="ASR model not found") from None
    except FileNotFoundError as exc:
        raise HTTPException(status_code=409, detail=f"model is not ready: {exc}") from exc
    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=500, detail=f"transcription failed: {exc}") from exc


@app.post("/v1/audio/speech")
async def speech(request: SpeechRequest):
    try:
        item = find_model(request.model, "tts")
        options = {}
        if item["runtime"]["family"] == "audio_cpp":
            options = {"reference_audio": request.reference_audio, "reference_text": request.reference_text, "voice_description": request.voice_description,
                       "emotion_text": request.emotion_text, "emotion_strength": request.emotion_strength}
        samples, rate = await run_blocking(
            synthesize, request.model, request.input, request.voice, request.speed, request.language, **options
        )
        body, media_type = await run_blocking(encode_audio, samples, rate, request.response_format)
        return Response(body, media_type=media_type, headers={"Content-Disposition": f'inline; filename="speech.{request.response_format}"'})
    except KeyError:
        raise HTTPException(status_code=404, detail="TTS model not found") from None
    except FileNotFoundError as exc:
        raise HTTPException(status_code=409, detail=f"model is not ready: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=500, detail=f"speech synthesis failed: {exc}") from exc


@app.get("/v1/audio/voices")
async def voices(model: str = "kokoro-multilang"):
    try:
        item = find_model(model, "tts")
    except KeyError:
        raise HTTPException(status_code=404, detail="TTS model not found") from None
    values = [{"id": key, "name": key, **value} for key, value in (item.get("voices") or {}).items()]
    return {
        "object": "list",
        "model": model,
        "default_voice": "default",
        "voices": values,
        "data": values,
    }


frontend = Path(__file__).resolve().parents[1] / "frontend" / "dist"
if os.getenv("VVOICE_STUDIO_ENABLED") == "true":
    from .studio import proxy as studio_proxy

    if frontend.is_dir():
        app.mount("/service/assets", StaticFiles(directory=frontend / "assets"), name="service-assets")

        @app.get("/service/{path:path}", include_in_schema=False)
        async def service_console(path: str):
            candidate = (frontend / path).resolve()
            if candidate.is_file() and frontend.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(frontend / "index.html")

    @app.api_route("/{path:path}", methods=["GET", "HEAD", "POST", "PUT", "DELETE"], include_in_schema=False)
    async def studio_transport(request: Request, path: str):
        return await studio_proxy(request, path)
elif frontend.is_dir():
    app.mount("/assets", StaticFiles(directory=frontend / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        candidate = (frontend / path).resolve()
        if candidate.is_file() and frontend.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(frontend / "index.html")
