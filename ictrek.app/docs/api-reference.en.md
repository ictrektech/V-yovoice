# V-Voice API reference

## Choose the correct API

VOS speech uses `http://v-voice-backend:7070`, default host mapping `http://<vos-host>:22700`, or same-origin `/app/com.ictrek.v-voice`. Append `/api-guide#en` for the complete guide, `/docs` for interactive fields, or `/openapi.json` for the active HTTP contract. The workbench API page retains its examples and links to this reference. Preserve the installed profile and shared weights; users do not deploy agents manually.

These are VOS service contracts. The desktop/CLI `/v1/generations` and MCP server use a separate configured token, data directory and startup flow documented in docs/api.md. A CLI token is not a VOS workbench identity. Newly added desktop features are not automatically enabled on VOS.

## Identity, keys and permissions

Native `/v1/*`, legacy `/transcribe`, hotword sets and speaker profiles are shared services without per-user isolation. They do not issue personal client API keys, and an arbitrary key does not establish VOS identity. Discovery declares authentication=none. Dependent apps should use V-Scheduler's unified `/v1/*` with a personal/model key or VOS identity; Scheduler owns public/private visibility. Provider keys, internal execution tokens and client access keys are different credentials.

Private `/studio-api/*` verifies a VOS Bearer token server-side through userinfo and isolates projects, history and reference voices. Workbench model.download/model.cancel require system_admin/platform_admin. Native Python model pull/stop/unload and shared hotword/speaker administration do not enforce the same per-user management authentication; use the existing trusted service boundary. Do not assume a workbench administrator check protects every native HTTP route.

POST `/api/v1/scheduler/binding` accepts only the Scheduler's VOS **application identity**, including rejection of administrator user tokens. GET returns only protocol_version, binding_revision, configured and approved_model_count. configured=true means a configuration exists, not that model approval, weights and calibration have passed inference. Internal executor calls require Scheduler execution credentials, execution ID and attempt/fence; ordinary Agents must not fabricate them.

## Models, downloading, budgets and stopping

`/api/v1/models` is the speech management catalog; `/api/v1/creative-models` includes music and soundfont variants. Existing files undergo background verification: verifying is not ready. ready concerns files, while ASR inference_ready checks node approval/calibration and does not guarantee free capacity. `/v1/models` and discovery publish ready ASR/TTS/speaker service models; the creative catalog does not imply every entry supports public synchronous speech.

Download202 is acceptance, not completion: poll status/progress/error. force=true requests update while retaining other installed variants in the shared repository. Import-only models return409 and require administrator-provided original weights. stop cancels downloads and returns status=cancelled/not_running plus tasks; unload releases a resident runtime without deleting weights. Use operation.cancel for the user's inference task. DELETE removes the corresponding saved data.

Query `/api/v1/models/{key}/input-limits` for approved limits. null means an existing compatible approval path, not unlimited resources. New approvals require calibration on the actual node. ASR uses duration_seconds, sample_rate, input_bytes and hotwords_characters; Kokoro uses text_characters and speed_min/max. Combined hotwords, speaker attribution or translation may return422 when uncalibrated. HTTP503 means missing model approval/binding/calibration,429 busy,413 input limit,422 invalid or unsupported input,409 weights not ready. Failure never grants automatic direct admission.

## ASR and TTS fields

Transcriptions/translations use multipart file and model. hotwords_set is repeatable; supported models merge saved sets, text and uploaded words. The field name `timestamp_granularities[]` includes brackets and accepts repeated word/segment values. json returns text only; verbose_json retains native available words/segments, hotwords and optional speaker information. Timestamps use seconds. text/srt/vtt return text. The smaller global upload and approved model limit applies.

Speech uses JSON, with model from discovery and voice from `/v1/audio/voices?model=...`. response_format selects binary audio; pcm has no WAV header. reference_audio is pure Base64 audio, not a server path. reference_text, voice_description and emotion_text/strength require the corresponding model capability and approval. Desktop support alone does not approve public synchronous execution.

## HTTP streaming and WebSocket

HTTP `/v1/audio/streaming/transcriptions` takes raw chunked audio and query parameters, not multipart. It returns one final response after upload ends, not SSE. pcm is s16le mono at sample_rate (default16000); wav uses its header; auto buffers until the end.

WebSocket `/v1/audio/streaming/ws?model=...` receives binary PCM/WAV frames and sends `{type:"partial",text,is_endpoint}`. Send text `{"type":"finish"}` and await `{type:"final",...native result}`. Disconnect is primarily cancellation and does not guarantee delivery of final output. Errors send `{type:"error",detail}` and close, commonly4404/4409/4422/4500; admission can map other44xx codes. WebSocket is documented here rather than in the HTTP OpenAPI route table.

## Private workbench RPC and tasks

POST `/studio-api/call` takes method, data and a32-character lowercase hexadecimal requestId. Keep the same ID and payload for a generation retry; conflicting reuse is not a new job. Check error even on HTTP200. result is method-specific. generation.start/cue, character.preview, generation.alignLyrics and melody.plan/cover/listen queue through Scheduler; acceptance does not mean audio is finished. Poll state.get result.state.activity/history and download `/studio-api/media/outputs/{fileName}` only after Scheduler-confirmed success. Foreign/unapproved outputs return404. References use the voices media kind.

Allowed browser methods: state.get; preferences.save (uiLocale only); draft.save/delete; generation.start/cue/alignLyrics/lyricTimes/lyricWords; character.save/preview/delete/discardPreview; voice.fromGeneration/suggest/update/record; timeline.import/fromGeneration; media.rename/delete; melody.inspect/transform/dismiss/plan/cover/listen/result; operation.cancel; diag.client; model.download/cancel/forget; runtime.unload. Other desktop RPCs are not generally available: arbitrary filesystem paths and external commands are prohibited. Exact data follows the same-version Draft/Character/State schemas in internal/schema and method branches in internal/desktop/rpc.go and internal/vos/server.go. Do not interpret every native result as a job ID.

```bash
# Shared speech through Scheduler, using its complete catalog ID.
curl --fail-with-body 'http://<vos-host>:22888/v1/audio/transcriptions' -H "Authorization: Bearer $SCHEDULER_KEY" -F 'model=<qualified-asr-model>' -F file=@sample.wav -F response_format=verbose_json
# Private workbench requires VOS identity, not a Scheduler model key.
curl --fail-with-body 'http://<vos-host>:22700/studio-api/call' -H "Authorization: Bearer $VOS_TOKEN" -H 'Content-Type: application/json' -d '{"method":"state.get","data":{},"requestId":"0123456789abcdef0123456789abcdef"}'
```


## Operations and responses

### GET /health

Identity: public operation / boundary described above

Response 200 — Native JSON response; extension catalog fields remain available.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `status` | string | Required |  |
| `version` | string | Required |  |
| `provider` | string | Required |  |

Response default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Optional |  |
| `error` | JSON | Optional |  |

`text/plain`

`string`

### GET /ready

Identity: public operation / boundary described above

Response 200 — Native JSON response; extension catalog fields remain available.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `ready` | boolean | Required |  |
| `model_hub_root` | boolean | Required |  |
| `scheduler` | object | Required |  |
| `scheduler.configured` | boolean | Required |  |
| `scheduler.binding_revision` | integer | Optional |  |
| `scheduler.protocol_version` | integer | Optional |  |
| `scheduler.approved_model_count` | integer | Optional |  |

Response default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Optional |  |
| `error` | JSON | Optional |  |

`text/plain`

`string`

### GET /api/v1/about

Identity: public operation / boundary described above

Response 200 — Native JSON response; extension catalog fields remain available.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `app_id` | string | Required |  |
| `app_version` | string | Required |  |
| `profile` | string | Required |  |
| `provider` | string | Required |  |
| `port` | integer | Required |  |
| `supported_asr_families` | integer | Required |  |
| `supported_tts_families` | integer | Required |  |
| `supported_speaker_families` | integer | Required |  |
| `streaming_asr` | boolean | Required |  |
| `max_loaded_models` | integer | Required |  |
| `max_concurrent_inference` | integer | Required |  |
| `max_concurrent_per_model` | integer | Required |  |

Response default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Optional |  |
| `error` | JSON | Optional |  |

`text/plain`

`string`

### GET /api/v1/discovery

Identity: public operation / boundary described above

Response 200 — Native JSON response; extension catalog fields remain available.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `service_id` | string | Required |  |
| `name` | string | Required |  |
| `protocol` | string | Required |  |
| `visibility` | string | Required |  |
| `multi_tenant` | boolean | Required |  |
| `authentication` | string | Required |  |
| `base_url` | string | Required |  |
| `health_path` | string | Required |  |
| `models` | array<VoicePublicModel> | Required |  |
| `scheduler` | VoiceSchedulerContract | Required |  |

Response default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Optional |  |
| `error` | JSON | Optional |  |

`text/plain`

`string`

### GET /api/v1/models

Identity: public operation / boundary described above

Response 200 — Native JSON response; extension catalog fields remain available.

`application/json`

`array<VoiceManagedModel>`

Response default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Optional |  |
| `error` | JSON | Optional |  |

`text/plain`

`string`

### GET /api/v1/models/{key}/input-limits

Identity: public operation / boundary described above

- `path: key` · string · Required · 

Response 200 — Native JSON response; extension catalog fields remain available.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `limits` | object  /  null | Required |  |
| `max_upload_bytes` | integer | Required |  |

Response 422 — Validation Error

`application/json`

`HTTPValidationError`

Response default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Optional |  |
| `error` | JSON | Optional |  |

`text/plain`

`string`

### GET /api/v1/creative-models

Identity: public operation / boundary described above

All creator precisions and soundfonts; management metadata, not speech discovery.

Response 200 — Native JSON response; extension catalog fields remain available.

`application/json`

`array<VoiceManagedModel>`

Response default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Optional |  |
| `error` | JSON | Optional |  |

`text/plain`

`string`

### POST /api/v1/models/{key}/pull

Identity: public operation / boundary described above

- `path: key` · string · Required · 

- `query: force` · boolean · Optional · 

Response 202 — 202 means download accepted, not installed. Existing task returns status=active/detail; otherwise the native V-Scheduler weight-service task response is forwarded. See its /openapi.json and poll /api/v1/models for ready/error.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `status` | string | Optional |  |
| `detail` | string | Optional |  |
| `task_id` | string | Optional |  |
| `model_id` | string | Optional |  |
| `phase` | string | Optional |  |

Response 422 — Validation Error

`application/json`

`HTTPValidationError`

Response default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Optional |  |
| `error` | JSON | Optional |  |

`text/plain`

`string`

### POST /api/v1/models/{key}/stop

Identity: public operation / boundary described above

- `path: key` · string · Required · 

Response 200 — Native JSON response; extension catalog fields remain available.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `status` | string | Required |  |
| `tasks` | array<string> | Required |  |

Response 422 — Validation Error

`application/json`

`HTTPValidationError`

Response default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Optional |  |
| `error` | JSON | Optional |  |

`text/plain`

`string`

### POST /api/v1/models/{key}/unload

Identity: public operation / boundary described above

- `path: key` · string · Required · 

Response 200 — Native JSON response; extension catalog fields remain available.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `status` | string | Required |  |
| `model` | string | Required |  |

Response 422 — Validation Error

`application/json`

`HTTPValidationError`

Response default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Optional |  |
| `error` | JSON | Optional |  |

`text/plain`

`string`

### GET /api/v1/hotwords

Identity: public operation / boundary described above

List saved hotword sets with their derived per-model format tables.

Response 200 — Native JSON response; extension catalog fields remain available.

`application/json`

`array<VoiceHotwordSet>`

Response default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Optional |  |
| `error` | JSON | Optional |  |

`text/plain`

`string`

### POST /api/v1/hotwords

Identity: public operation / boundary described above

Request body: application/json

`HotwordSetCreate`

Response 201 — Native JSON response; extension catalog fields remain available.

`application/json`

`VoiceHotwordSet`

Response 422 — Validation Error

`application/json`

`HTTPValidationError`

Response default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Optional |  |
| `error` | JSON | Optional |  |

`text/plain`

`string`

### POST /api/v1/hotwords/import

Identity: public operation / boundary described above

Request body: multipart/form-data

`Body_import_hotword_set_api_v1_hotwords_import_post`

Response 201 — Native JSON response; extension catalog fields remain available.

`application/json`

`VoiceHotwordSet`

Response 422 — Validation Error

`application/json`

`HTTPValidationError`

Response default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Optional |  |
| `error` | JSON | Optional |  |

`text/plain`

`string`

### GET /api/v1/hotwords/{set_id}

Identity: public operation / boundary described above

- `path: set_id` · string · Required · 

Response 200 — Native JSON response; extension catalog fields remain available.

`application/json`

`VoiceHotwordSet`

Response 422 — Validation Error

`application/json`

`HTTPValidationError`

Response default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Optional |  |
| `error` | JSON | Optional |  |

`text/plain`

`string`

### PATCH /api/v1/hotwords/{set_id}

Identity: public operation / boundary described above

- `path: set_id` · string · Required · 

Request body: application/json

`HotwordSetUpdate`

Response 200 — Native JSON response; extension catalog fields remain available.

`application/json`

`VoiceHotwordSet`

Response 422 — Validation Error

`application/json`

`HTTPValidationError`

Response default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Optional |  |
| `error` | JSON | Optional |  |

`text/plain`

`string`

### DELETE /api/v1/hotwords/{set_id}

Identity: public operation / boundary described above

- `path: set_id` · string · Required · 

Response 200 — Native JSON response; extension catalog fields remain available.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `status` | string | Required |  |
| `id` | string | Required |  |

Response 422 — Validation Error

`application/json`

`HTTPValidationError`

Response default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Optional |  |
| `error` | JSON | Optional |  |

`text/plain`

`string`

### GET /api/v1/hotwords/{set_id}/export

Identity: public operation / boundary described above

- `path: set_id` · string · Required · 

- `query: format` · string · Optional · text, qwen3, or zipformer

Response 200 — UTF-8 hotword file; Content-Disposition supplies its name.

`text/plain`

`string`

Response 422 — Validation Error

`application/json`

`HTTPValidationError`

Response default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Optional |  |
| `error` | JSON | Optional |  |

`text/plain`

`string`

### GET /v1/models

Identity: public operation / boundary described above

Response 200 — Native JSON response; extension catalog fields remain available.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `object` | string | Required |  |
| `data` | array<VoicePublicModel> | Required |  |

Response default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Optional |  |
| `error` | JSON | Optional |  |

`text/plain`

`string`

### POST /v1/audio/transcriptions

Identity: public operation / boundary described above

Request body: multipart/form-data

`Body_transcriptions_v1_audio_transcriptions_post`

Response 200 — json returns text only; verbose_json keeps native model metadata, available word/segment timestamps and optional hotword/speaker blocks. Times are seconds. text/srt/vtt return text; supported formats depend on this operation. HTTP chunked upload returns one final response, not SSE.

`application/json`

`VoiceTranscript`

`text/plain`

`string`

Response 404 — ASR model key does not exist or is not an ASR model

Response 409 — Model exists but its files are not ready

Response 413 — Audio upload is larger than the configured limit

Response 422 — Invalid field, hotword file, hotword limit, score, or model capability

Response 500 — Audio decoding or inference failed

Response default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Optional |  |
| `error` | JSON | Optional |  |

`text/plain`

`string`

### POST /v1/audio/translations

Identity: public operation / boundary described above

Request body: multipart/form-data

`Body_translations_v1_audio_translations_post`

Response 200 — json returns text only; verbose_json keeps native model metadata, available word/segment timestamps and optional hotword/speaker blocks. Times are seconds. text/srt/vtt return text; supported formats depend on this operation. HTTP chunked upload returns one final response, not SSE.

`application/json`

`VoiceTranscript`

`text/plain`

`string`

Response 404 — ASR model key does not exist or is not an ASR model

Response 409 — Model exists but its files are not ready

Response 413 — Audio upload is larger than the configured limit

Response 422 — Invalid field, hotword file, hotword limit, score, or model capability

Response 500 — Audio decoding or inference failed

Response default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Optional |  |
| `error` | JSON | Optional |  |

`text/plain`

`string`

### POST /v1/audio/streaming/transcriptions

Identity: public operation / boundary described above

Realtime streaming transcription over a chunked HTTP request body.

The body is audio transmitted incrementally; V-Voice feeds every chunk into
the OnlineRecognizer as it arrives and returns the final transcript when the
body ends. Use ``format=pcm`` or ``wav`` for true incremental decoding;
``auto`` buffers the whole body and decodes once.

- `query: model` · string · Required · Ready streaming ASR model key from /api/v1/discovery

- `query: language` · string · Optional · Kept for contract symmetry; streaming models auto-detect

- `query: format` · string · Optional · pcm (raw s16le mono), wav (uncompressed mono RIFF), or auto (buffered, decoded at end)

- `query: sample_rate` · integer · Optional · Sample rate for format=pcm; wav uses its header

- `query: response_format` · string · Optional · verbose_json, json, or text

- `query: hotwords` · string · Optional · One-shot comma/newline-separated phrases for hotword-capable streaming models

- `query: hotwords_set` · array<string> | null · Optional · Repeatable saved hotword set id from /api/v1/hotwords

- `query: hotwords_score` · number | null · Optional · Contextual-bias score from 0 to 10; streaming Zipformer only

- `query: speaker_model` · string · Optional · Optional ready speaker model key; adds a speaker attribution block to the final response

- `query: speaker_threshold` · number | null · Optional · Cosine similarity threshold for the speaker block; default 0.6

Request body: application/octet-stream

`string`

Response 200 — json returns text only; verbose_json keeps native model metadata, available word/segment timestamps and optional hotword/speaker blocks. Times are seconds. text/srt/vtt return text; supported formats depend on this operation. HTTP chunked upload returns one final response, not SSE.

`application/json`

`VoiceTranscript`

`text/plain`

`string`

Response 404 — ASR model key does not exist or is not an ASR model

Response 409 — Model exists but its files are not ready

Response 413 — Audio upload is larger than the configured limit

Response 422 — Invalid field, hotword file, hotword limit, score, or model capability

Response 500 — Audio decoding or inference failed

Response default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Optional |  |
| `error` | JSON | Optional |  |

`text/plain`

`string`

### GET /api/v1/speakers

Identity: public operation / boundary described above

List enrolled voiceprints (management plane).

Response 200 — Native JSON response; extension catalog fields remain available.

`application/json`

`array<VoiceSpeaker>`

Response default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Optional |  |
| `error` | JSON | Optional |  |

`text/plain`

`string`

### POST /api/v1/speakers

Identity: public operation / boundary described above

Enroll a speaker voiceprint from uploaded audio.

Request body: multipart/form-data

`Body_enroll_speaker_api_v1_speakers_post`

Response 201 — Native JSON response; extension catalog fields remain available.

`application/json`

`VoiceSpeaker`

Response 422 — Validation Error

`application/json`

`HTTPValidationError`

Response default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Optional |  |
| `error` | JSON | Optional |  |

`text/plain`

`string`

### DELETE /api/v1/speakers/{speaker_id}

Identity: public operation / boundary described above

- `path: speaker_id` · string · Required · 

Response 200 — Native JSON response; extension catalog fields remain available.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `status` | string | Required |  |
| `id` | string | Required |  |

Response 422 — Validation Error

`application/json`

`HTTPValidationError`

Response default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Optional |  |
| `error` | JSON | Optional |  |

`text/plain`

`string`

### GET /v1/audio/speakers

Identity: public operation / boundary described above

Public list of enrolled voiceprints for dependent clients.

- `query: model` · string · Optional · Ready speaker model key

Response 200 — Native JSON response; extension catalog fields remain available.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `object` | string | Required |  |
| `model` | string | Required |  |
| `default_threshold` | number | Required |  |
| `speakers` | array<VoiceSpeaker> | Required |  |
| `data` | array<VoiceSpeaker> | Required |  |

Response 422 — Validation Error

`application/json`

`HTTPValidationError`

Response default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Optional |  |
| `error` | JSON | Optional |  |

`text/plain`

`string`

### POST /v1/audio/speakers/identify

Identity: public operation / boundary described above

Identify which enrolled speaker (if any) spoke in the audio.

Request body: multipart/form-data

`Body_speakers_identify_v1_audio_speakers_identify_post`

Response 200 — Native JSON response; extension catalog fields remain available.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `object` | string | Required |  |
| `model` | string | Required |  |
| `threshold` | number | Required |  |
| `identified` | boolean | Required |  |
| `speaker` | object  /  null | Required |  |
| `score` | number | Required |  |
| `ranked` | array<object> | Required |  |

Response 422 — Validation Error

`application/json`

`HTTPValidationError`

Response default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Optional |  |
| `error` | JSON | Optional |  |

`text/plain`

`string`

### POST /v1/audio/speakers/verify

Identity: public operation / boundary described above

Verify the audio against one enrolled speaker voiceprint.

Request body: multipart/form-data

`Body_speakers_verify_v1_audio_speakers_verify_post`

Response 200 — Native JSON response; extension catalog fields remain available.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `object` | string | Required |  |
| `model` | string | Required |  |
| `speaker` | VoiceSpeaker | Required |  |
| `threshold` | number | Required |  |
| `score` | number | Required |  |
| `verified` | boolean | Required |  |

Response 422 — Validation Error

`application/json`

`HTTPValidationError`

Response default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Optional |  |
| `error` | JSON | Optional |  |

`text/plain`

`string`

### POST /transcribe

Identity: public operation / boundary described above

- `query: model` · string · Optional · 

- `query: lang` · string · Optional · 

Request body: application/octet-stream

`string`

Response 200 — json returns text only; verbose_json keeps native model metadata, available word/segment timestamps and optional hotword/speaker blocks. Times are seconds. text/srt/vtt return text; supported formats depend on this operation. HTTP chunked upload returns one final response, not SSE.

`application/json`

`VoiceTranscript`

`text/plain`

`string`

Response 422 — Validation Error

`application/json`

`HTTPValidationError`

Response default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Optional |  |
| `error` | JSON | Optional |  |

`text/plain`

`string`

### POST /v1/audio/speech

Identity: public operation / boundary described above

Request body: application/json

`SpeechRequest`

Response 200 — Binary audio in response_format; raw pcm is not a WAV container.

`audio/mpeg`

`string`

`audio/wav`

`string`

`audio/ogg`

`string`

`audio/aac`

`string`

`audio/flac`

`string`

`application/octet-stream`

`string`

Response 422 — Validation Error

`application/json`

`HTTPValidationError`

Response default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Optional |  |
| `error` | JSON | Optional |  |

`text/plain`

`string`

### GET /v1/audio/voices

Identity: public operation / boundary described above

- `query: model` · string · Optional · 

Response 200 — Native JSON response; extension catalog fields remain available.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `object` | string | Required |  |
| `model` | string | Required |  |
| `default_voice` | string | Required |  |
| `voices` | array<object> | Required |  |
| `data` | array<object> | Required |  |

Response 422 — Validation Error

`application/json`

`HTTPValidationError`

Response default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Optional |  |
| `error` | JSON | Optional |  |

`text/plain`

`string`

### GET /api/v1/scheduler/binding

Identity: public operation / boundary described above

Public redacted automatic-binding status; never returns service credentials.

Response 200 — Native JSON response; extension catalog fields remain available.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `protocol_version` | integer | Required |  |
| `binding_revision` | integer | Required |  |
| `configured` | boolean | Required |  |
| `approved_model_count` | integer | Required |  |

Response default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Optional |  |
| `error` | JSON | Optional |  |

`text/plain`

`string`

### POST /api/v1/scheduler/binding

Identity: VOSApplicationBearer

VOS Scheduler application only: validate and atomically apply a versioned binding.

The server-to-server JSON contract is documented in docs/scheduler-auto-binding.md.
User tokens, including administrator user tokens, cannot configure this endpoint.

Request body: application/json

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `protocol_version` | integer | Required |  · const=1 |
| `binding_revision` | integer | Required |  · minimum=1.0 |
| `app_id` | string | Required |  · const="com.ictrek.v-voice" |
| `url` | string | Required | Must match fixed VVOICE_SCHEDULER_URL. Default is http://v-scheduler:8080/scheduler/api/v1; v-router is a compatibility alias. The controller also listens at http://v-scheduler:38120/api/v1. |
| `token` | string | Required |  · minLength=32 · maxLength=4096 |
| `executor_token` | string | Required |  · minLength=32 · maxLength=4096 |
| `upstream_url` | string | Required | Must match V-Voice's advertised native upstream URL |
| `models` | object | Required |  |
| `gateway_executors` | object | Optional |  |
| `secondary_models` | object | Optional |  |
| `input_limits_version` | integer  /  null | Optional |  |
| `mixed_input_limits_version` | integer  /  null | Optional |  |
| `legacy_unbounded_models` | array<string>  /  null | Optional | Explicit old approvals only; disjoint from model_limits, together covering models. Does not grant an executor or alter task types. |
| `model_limits` | object  /  null | Optional |  |
| `execution_settings` | object  /  null | Optional | Optional calibrated runtime settings retained for binding-document compatibility. |

Response 200 — Native JSON response; extension catalog fields remain available.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `protocol_version` | integer | Required |  |
| `binding_revision` | integer | Required |  |
| `configured` | boolean | Required |  |
| `approved_model_count` | integer | Required |  |

Response default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Optional |  |
| `error` | JSON | Optional |  |

`text/plain`

`string`

### POST /studio-api/call

Identity: VOSUserBearer

Private user RPC: projects, music/score generation, job polling/cancellation and voices.

Returns result or error (check error even on HTTP 200). generation.start returns a job ID;
poll state.get activity/history and read results only after Scheduler-confirmed success.
Model download/cancel additionally require an administrator. The Go adapter enforces
identity, method allowlist, payload validation, user isolation and scheduling.
These are not OpenAI-standard music endpoints or gateway-forwarded public APIs.

Request body: application/json

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `method` | string | Required |  · enum=["state.get", "draft.save", "draft.delete", "generation.start", "generation.cue", "character.save", "character.preview", "character.delete", "character.discardPreview", "voice.fromGeneration", "voice.update", "voice.record", "timeline.import", "media.rename", "media.delete", "operation.cancel", "preferences.save", "model.download", "model.cancel", "model.forget", "runtime.unload", "diag.client"] |
| `data` | object | Required | Method-specific payload. generation.start accepts a Draft with bare creator modelId; kind music or score selects music generation or soundfont rendering. |
| `requestId` | string | Required | Stable generation idempotency key; retry with identical data |

Response 200 — Check error even on HTTP200. result is method-specific: state.get returns state/catalog metadata, generation returns job ID; poll until confirmed success before reading media. See the complete workbench workflow and native schema in the guide.

`application/json`

`object | object`

Response default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Optional |  |
| `error` | JSON | Optional |  |

`text/plain`

`string`

### GET /studio-api/media/{kind}/{file_name}

Identity: VOSUserBearer

Download a reference voice or completed output belonging to the authenticated user.

Obtain file_name from state.get history/voices; internal filesystem paths are not accepted.

- `path: kind` · string · Required · 

- `path: file_name` · string · Required · 

Response 200 — User-owned audio file

`application/json`

`JSON`

`audio/wav`

`string`

Response 401 — VOS user authentication required

Response 404 — Missing, foreign or not-yet-approved result

Response 422 — Validation Error

`application/json`

`HTTPValidationError`

Response default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Optional |  |
| `error` | JSON | Optional |  |

`text/plain`

`string`

## Shared data types

Field names retain their API spelling. Interpret extension metadata according to its owning service.

### Body_enroll_speaker_api_v1_speakers_post

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `name` | string | Required | Display name of the enrolled speaker |
| `file` | string | Required | Enrollment audio (speech from this speaker) |
| `model` | string | Optional | Ready speaker model key · default="speaker-campplus-zh-en" |

### Body_import_hotword_set_api_v1_hotwords_import_post

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `name` | string | Required | Display name of the hotword set |
| `file` | string | Required | UTF-8 hotword table, one phrase per line |

### Body_speakers_identify_v1_audio_speakers_identify_post

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `file` | string | Required | Audio to attribute to an enrolled speaker |
| `model` | string | Optional | Ready speaker model key · default="speaker-campplus-zh-en" |
| `threshold` | number | Optional | Cosine similarity threshold · default=0.6 · minimum=0.0 · maximum=1.0 |

### Body_speakers_verify_v1_audio_speakers_verify_post

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `file` | string | Required | Audio to verify against a speaker |
| `speaker` | string | Required | Enrolled speaker id or exact name |
| `model` | string | Optional | Ready speaker model key · default="speaker-campplus-zh-en" |
| `threshold` | number | Optional | Cosine similarity threshold · default=0.6 · minimum=0.0 · maximum=1.0 |

### Body_transcriptions_v1_audio_transcriptions_post

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `file` | string | Required | Audio file to recognize |
| `model` | string | Required | Ready ASR model key from /api/v1/discovery |
| `language` | string | Optional | Language code; empty lets the model decide · default="" |
| `response_format` | string | Optional | json, verbose_json, text, srt, or vtt · default="json" |
| `hotwords` | string | Optional | Comma/newline-separated phrases; SeACo, Qwen3-ASR or Zipformer · default="" |
| `hotwords_file` | string  /  null | Optional | UTF-8 text, one phrase per line |
| `hotwords_score` | number  /  null | Optional | Zipformer contextual-bias score from 0 to 10; ignored by other models |
| `hotwords_set` | array<string>  /  null | Optional | Repeatable saved hotword set id from /api/v1/hotwords; merged with hotwords and hotwords_file |
| `timestamp_granularities[]` | array<string>  /  null | Optional | Repeat with word and/or segment; verbose_json includes every available timestamp granularity |
| `speaker_model` | string | Optional | Optional ready speaker model key; adds a speaker attribution block to verbose_json · default="" |
| `speaker_threshold` | number  /  null | Optional | Cosine similarity threshold for the speaker block; default 0.6 |

### Body_translations_v1_audio_translations_post

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `file` | string | Required | Audio file to translate |
| `model` | string | Required | Ready ASR model key from /api/v1/discovery |
| `language` | string | Optional | Input language code; empty lets the model decide · default="" |
| `response_format` | string | Optional | json, verbose_json, text, srt, or vtt · default="json" |
| `hotwords` | string | Optional | Comma/newline-separated phrases; SeACo, Qwen3-ASR or Zipformer · default="" |
| `hotwords_file` | string  /  null | Optional | UTF-8 text, one phrase per line |
| `hotwords_score` | number  /  null | Optional | Zipformer contextual-bias score from 0 to 10; ignored by other models |
| `hotwords_set` | array<string>  /  null | Optional | Repeatable saved hotword set id from /api/v1/hotwords; merged with hotwords and hotwords_file |
| `timestamp_granularities[]` | array<string>  /  null | Optional | Repeat with word and/or segment; verbose_json includes every available timestamp granularity |
| `speaker_model` | string | Optional | Optional ready speaker model key; adds a speaker attribution block to verbose_json · default="" |
| `speaker_threshold` | number  /  null | Optional | Cosine similarity threshold for the speaker block; default 0.6 |

### HTTPValidationError

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | array<ValidationError> | Optional |  |

### HotwordSetCreate

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `name` | string | Required | Display name of the hotword set · minLength=1 · maxLength=64 |
| `phrases` | array<string> | Optional | Phrases; preferred over phrases_text when both are sent |
| `phrases_text` | string | Optional | Comma/newline-separated phrases; used when phrases is empty · default="" · maxLength=8192 |

### HotwordSetUpdate

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `name` | string  /  null | Optional |  |
| `phrases` | array<string>  /  null | Optional |  |

### SpeechRequest

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `model` | string | Required | Ready TTS model key from /api/v1/discovery |
| `input` | string | Required | Text to synthesize · minLength=1 · maxLength=20000 |
| `voice` | string | Optional | Voice ID returned by /v1/audio/voices for this model · default="default" |
| `response_format` | string | Optional | Binary output audio format · default="mp3" · enum=["mp3", "opus", "aac", "flac", "wav", "pcm"] |
| `speed` | number | Optional | Speech speed multiplier · default=1.0 · minimum=0.25 · maximum=4.0 |
| `language` | string | Optional | Language code; empty uses the model/voice default · default="" |
| `reference_audio` | string | Optional | audio.cpp only: base64 reference audio; not a server file path · default="" · maxLength=28000000 |
| `reference_text` | string | Optional | audio.cpp only: reference audio transcript · default="" · maxLength=2000 |
| `voice_description` | string | Optional | audio.cpp only: voice design instruction · default="" · maxLength=500 |
| `emotion_text` | string | Optional | IndexTTS only: emotion instruction; requires emotion_control capability · default="" · maxLength=500 |
| `emotion_strength` | number | Optional | IndexTTS only: emotion strength · default=0.6 · minimum=0.0 · maximum=1.0 |

### ValidationError

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `loc` | array<string  /  integer> | Required |  |
| `msg` | string | Required |  |
| `type` | string | Required |  |
| `input` | JSON | Optional |  |
| `ctx` | object | Optional |  |

### VoiceManagedModel

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `key` | string | Required |  |
| `name` | string | Required |  |
| `kind` | string | Required |  |
| `status` | string | Required |  |
| `family` | string | Optional |  |
| `backend` | string | Optional |  |
| `modelscope_repo` | string | Optional |  |
| `languages` | array<string> | Optional |  |
| `description` | string | Optional |  |
| `streaming` | boolean | Optional |  |
| `translation` | boolean | Optional |  |
| `loaded` | boolean | Optional |  |
| `inference_ready` | boolean | Optional |  |
| `inference_error` | string | Optional |  |
| `error` | string | Optional |  |
| `progress` | number  /  null | Optional |  |
| `downloaded_bytes` | integer  /  null | Optional |  |
| `total_bytes` | integer  /  null | Optional |  |
| `import_required` | boolean | Optional |  |
| `voices` | object | Optional |  |
| `voices.{key}.sid` | integer | Required |  |
| `voices.{key}.language` | string | Required |  |
| `hotwords` | object | Optional |  |
| `hotwords.supported` | boolean | Required |  |
| `hotwords.formats` | array<string> | Optional |  |
| `hotwords.score` | boolean | Optional |  |
| `hotwords.default_score` | number | Optional |  |
| `timestamps` | object | Optional |  |
| `timestamps.word` | boolean | Required |  |
| `timestamps.segment` | boolean | Required |  |
| `timestamps.source` | string | Required |  |

### VoicePublicModel

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `id` | string | Required |  |
| `object` | string | Required |  |
| `owned_by` | string | Required |  |
| `kind` | string | Required |  |
| `capabilities` | array<string> | Required |  |
| `endpoints` | array<string> | Required |  |
| `languages` | array<string> | Required |  |
| `hotwords` | object | Optional |  |
| `hotwords.supported` | boolean | Required |  |
| `hotwords.formats` | array<string> | Optional |  |
| `hotwords.score` | boolean | Optional |  |
| `hotwords.default_score` | number | Optional |  |
| `timestamps` | object | Optional |  |
| `timestamps.word` | boolean | Required |  |
| `timestamps.segment` | boolean | Required |  |
| `timestamps.source` | string | Required |  |
| `streaming` | object | Optional |  |
| `streaming.supported` | boolean | Required |  |
| `streaming.transports` | array<string> | Required |  |
| `streaming.hotwords` | boolean | Required |  |
| `voices` | object | Optional |  |
| `voices.endpoint` | string | Required |  |
| `voices.default` | string | Required |  |
| `voices.count` | integer | Required |  |

### VoiceHotwordSet

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `id` | string | Required |  |
| `name` | string | Required |  |
| `phrases` | array<string> | Required |  |
| `phrase_count` | integer | Required |  |
| `created_at` | string | Required |  |
| `updated_at` | string | Required |  |
| `formats` | array<object> | Required |  |

### VoiceSpeaker

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `id` | string | Required |  |
| `name` | string | Required |  |
| `model` | string | Required |  |
| `created_at` | string | Required |  |
| `dimension` | integer | Required |  |

### VoiceTranscript

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `text` | string | Required |  |
| `language` | string | Optional |  |
| `duration` | number | Optional |  |
| `words` | array<object> | Optional |  |
| `segments` | array<object> | Optional |  |
| `tokens` | array<string> | Optional |  |
| `timestamps` | array<number> | Optional |  |
| `emotion` | string | Optional |  |
| `event` | string | Optional |  |
| `streaming` | boolean | Optional |  |
| `hotwords` | object | Optional |  |
| `hotwords.requested` | boolean | Required |  |
| `hotwords.supported` | boolean | Required |  |
| `hotwords.applied` | boolean | Required |  |
| `hotwords.sets` | array<object> | Required |  |
| `hotwords.score_applied` | number  /  null | Required |  |
| `hotwords.ignored` | boolean | Required |  |
| `speaker` | object | Optional |  |
| `speaker.model` | string | Optional |  |
| `speaker.threshold` | number | Optional |  |
| `speaker.identified` | boolean | Optional |  |
| `speaker.speaker` | object  /  null | Optional |  |
| `speaker.score` | number | Optional |  |
| `speaker.ranked` | array<object> | Optional |  |

### VoiceSchedulerContract

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `protocol_version` | integer | Required |  |
| `input_limits_version` | integer | Required |  |
| `mixed_input_limits_version` | integer | Required |  |
| `app_id` | string | Required |  |
| `binding_endpoint` | string | Required |  |
| `lifecycle_protocol_version` | integer | Required |  |
| `executor_base_url` | string | Required |  |
| `upstream_url` | string | Required |  |
| `sync_models` | array<object> | Required |  |
| `async_models` | array<object> | Required |  |
| `num_threads` | integer | Required |  |
| `max_concurrent_inference` | integer | Required |  |
| `cpu_models` | array<string> | Required |  |
| `provider` | string | Required |  |
