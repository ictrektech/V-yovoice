# V-Voice

The unified workbench includes speech, songs, scores and a Background music page.
Native music supports ACE-Step 1.5 Turbo, Stable Audio 3 Small-Music / Medium and
MusicGen Small. Install them in Model management → Creator models and soundfonts
through V-Scheduler / ModelScope, then preview and download WAV/FLAC.
The public music extension is `POST /v1/audio/music/generations`; MusicGen supports
up to 30 seconds. Installed models still require V-Voice-specific resource
calibration and scheduling approval. Existing song, score and speech features remain.

The additional `seaco-paraformer-zh` model is installed through V-Scheduler from
`vivibit/v-voice-seaco-paraformer-zh-int8`. It uses CPU ONNX Runtime on every profile,
with two INT8 ONNX graphs and no PyTorch/FunASR inference dependency. It supports
Chinese batch transcription and request-scoped neural hotwords (inline, UTF-8 file,
or saved sets); each phrase is limited to 10 characters after removing spaces.
No bias score is needed. Translation, streaming and word timestamps are not exposed.
The existing `paraformer-zh` remains available.

V-Voice is a public ASR / streaming ASR / TTS / speaker-recognition service powered
by ONNX runtimes. Models are installed through V-Scheduler's built-in model repository
and shared globally. Its gateway discovers public capabilities through the discovery endpoint.
No separate Model Hub or V-Router installation is required.

Host OpenAI-compatible endpoint: `http://<VOS-IP>:22700/v1`.

Models are hot-loaded on their first inference request, with up to two resident
runtime instances by default. Global and per-model-key inference concurrency both
default to two; excess requests wait. The console About button shows the app
version (injected from the package `APP_VERSION` env var), profile, and provider;
the hotwords page manages saved hotword sets with model-format export; the speaker
page enrolls voiceprints and runs 1:N identification / 1:1 verification; TTS audio
can be downloaded directly.

## Streaming recognition

`zipformer-zh-streaming` and `zipformer-en-streaming` accept streamed audio and
recognize in realtime:

```bash
# HTTP chunked: incremental decode, final transcript when the body ends
curl 'http://<VOS-IP>:22700/v1/audio/streaming/transcriptions?model=zipformer-zh-streaming&format=pcm' \
  --header 'Transfer-Encoding: chunked' --data-binary @audio.pcm

# WebSocket: binary PCM frames return partials; send {"type":"finish"} for the final
# ws://<VOS-IP>:22700/v1/audio/streaming/ws?model=zipformer-en-streaming
```

## Speaker recognition

`speaker-campplus-zh-en` (zh+en) provides voiceprints: enroll via the management
endpoint `POST /api/v1/speakers` (name + audio, >=10s recommended), then identify
1:N with `POST /v1/audio/speakers/identify`, verify 1:1 with `POST
/v1/audio/speakers/verify`, and list the library via `GET /v1/audio/speakers`.
Cosine-similarity threshold defaults to 0.6. Enrollment persists once
(app storage `data/speakers.json`) and stays comparable indefinitely.

Combined mode (ASR + speaker attribution in one call): transcription and
streaming endpoints accept the optional `speaker_model` (plus
`speaker_threshold`); the same audio is attributed while being transcribed and
`verbose_json` / the streaming final message carry a `speaker` block. Omitting
the parameter keeps requests fully OpenAI-compatible:

```bash
curl 'http://<VOS-IP>:22700/v1/audio/transcriptions' \
  -F file=@sample.wav -F model=sensevoice-int8 \
  -F speaker_model=speaker-campplus-zh-en -F response_format=verbose_json
```

## Hotword ASR API

Qwen3-ASR (0.6B / 1.7B), `zipformer-en`, and both streaming Zipformers accept
hotwords: one-shot `hotwords` text, an uploaded UTF-8 `hotwords_file`, and the
repeatable saved-set reference `hotwords_set` are merged and deduplicated (max 64
phrases / 4096 UTF-8 bytes). Zipformer models also accept `hotwords_score` from 0
to 10 (default 1.5). Saved sets are managed through `/api/v1/hotwords`; uploaded
tables are converted in the background into `text` / `qwen3` / `zipformer` formats.

```bash
curl 'http://<VOS-IP>:22700/v1/audio/transcriptions' \
  -F file=@sample.wav -F model=qwen3-asr-0.6b \
  -F 'hotwords=Huawei,Ascend,V-Voice' -F hotwords_set=hw_1a2b3c4d \
  -F language=en -F response_format=verbose_json
```

SenseVoice, Paraformer, and Zipformer return OpenAI-style `words[]` and
`segments[]` in `verbose_json`; Qwen3-ASR and Whisper Tiny return empty arrays
without fabricating timestamps. SenseVoice adds `lang` / `emotion` / `event`
paralinguistic labels; ASR output never contains a speaker field — use the speaker
endpoints for attribution. Query `/v1/audio/voices?model=<model key>` before TTS
and use a returned voice ID.

Audio longer than 30 seconds is automatically split with VAD before decoding (`VVOICE_VAD_SPLIT_SECONDS`, 0 disables), preventing long-audio degradation; `verbose_json` includes `segments_decoded`.

See `http://<VOS-IP>:22700/docs` or `/openapi.json` for the live complete schema
and docs/v-router-discovery.md in the repository for the V-Router contract.
