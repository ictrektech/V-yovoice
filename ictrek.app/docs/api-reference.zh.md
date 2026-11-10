# V-Voice API 详细参考

## 选择正确入口

VOS 服务的容器地址为 `http://v-voice-backend:7070`，默认宿主机映射为 `http://<vos-host>:22700`，浏览器同源为 `/app/com.ictrek.v-voice`。完整文档 `/api-guide#zh`、交互字段参考 `/docs`、实际启用接口契约 `/openapi.json` 均追加在该根地址后。工作台的 API 页保留原有分章示例，并链接本参考。安装时保留原 profile 和共享权重目录，不需要用户手工部署 agent。

这里是 VOS 服务契约，不是桌面 CLI 的独立 `/v1/generations`/MCP 服务。后者使用单独的本机/CLI Bearer token、数据目录和启动方式，见项目 docs/api_zh.md；不能把 CLI Token 填到 VOS 工作台接口。VOS 中新桌面功能是否开放，以本服务实际目录和路由为准。

## 身份、Key 与权限边界

兼容语音 `/v1/*`、旧 `/transcribe`、热词和声纹库是应用共享服务，不按 VOS 用户隔离；原生 HTTP 路由不签发个人 API Key，也不把客户端任意 Key 当作 VOS 用户。公共目录声明 authentication=none。对外应用优先通过 V-Scheduler 的统一 `/v1/*` 调用，使用其个人/模型 Key 或 VOS 身份，public/private 由 V-Scheduler 控制；厂商 Key、调度内部 token 和客户端 Key 不是同一种凭据。

用户工作台 `/studio-api/*` 使用经服务端 VOS userinfo 验证的 Bearer token，项目、生成记录和参考音色按用户隔离。model.download/model.cancel 等工作台管理命令还要求 system_admin/platform_admin。原生 Python 模型 pull/stop/unload、共享热词和声纹管理接口不提供相同的逐用户管理鉴权，应仅在已有受信服务入口使用，不能把工作台的管理员校验推定为所有原生路由都具备。

自动绑定 POST `/api/v1/scheduler/binding` 只接受 V-Scheduler 的 VOS **应用身份**；管理员用户 token 也不能配置。GET 仅返回 protocol_version、binding_revision、configured、approved_model_count，不返回服务凭据。configured=true 仅表示配置存在，模型还需批准、权重校验与输入校准；不能据此声称推理已验证。内部执行端由调度器携带 executor token、执行 ID、attempt/fence 调用，外部 Agent 不应自行构造。

## 模型、下载、预算和停止

`GET /api/v1/models` 是全量语音管理目录；`/api/v1/creative-models` 包含音乐、音色库等创作精度。共享文件存在后还会后台校验，verifying 不等于 ready；ready 表示文件就绪，ASR inference_ready 才说明该节点的模型审批/校准通过，仍不保证当前资源空闲。`/v1/models` 和 discovery 只发布文件就绪且属于 ASR/TTS/speaker 的接口模型，创作目录不等于全部可经公开 speech 端点执行。

pull 的202只表示下载已受理，需轮询目录 status/progress/error。force=true 请求更新但保留共享仓库其他已安装精度。仅导入模型返回409，需管理员提供原始权重，不能自动下载一个不存在的源。stop 取消**下载**，响应 status=cancelled/not_running 和 tasks；unload 卸载驻留运行时、不删除权重；用户推理取消使用工作台 operation.cancel。DELETE 热词/声纹/作品会删除对应记录，不能当成取消执行。

调度启用时，输入限制从 `/api/v1/models/{key}/input-limits` 查询，limits 为 null 表示兼容的既有批准路径，不代表无限资源。受管的新模型须有当前节点校准，不要抄其他机器预算。ASR limits 包含 duration_seconds、sample_rate、input_bytes、hotwords_characters；Kokoro 使用 text_characters、speed_min/max。受限 ASR 组合热词/声纹/翻译若未校准会返回422，不能仅以模型本身支持推定组合已批准。503 缺少模型执行审批、绑定或校准，429 资源繁忙，413 上传/时长等限制，422 参数/能力不支持，409 权重未就绪。请求失败不会自动获得直通许可。

## ASR / TTS 输入与返回

ASR transcriptions/translations 使用 multipart 的 file、model 等字段；hotwords_set 可以重复，热词文本、文件和热词集合并去重，具体模型能力以 discovery 为准。`timestamp_granularities[]` 是含方括号的字段名，可重复 word/segment；json 只返回 text，verbose_json 才保留原生 words/segments、hotwords 和可选 speaker。时间单位是秒，不支持的时间戳不能伪造。text/srt/vtt 返回文本而不是 JSON。输入文件大小上限取服务配置与已批准模型限额较小值。

TTS speech 使用 JSON。model 从目录选择，voice 从 `/v1/audio/voices?model=...` 获取；response_format 决定二进制音频，pcm 是裸 PCM，不含 WAV 头。克隆 reference_audio 是纯 Base64 音频，不接受服务器路径；reference_text、voice_description、emotion_text/strength 仅在相应模型能力成立时生效。不要将桌面支持的每个创作模型都推定为该公开同步端点已批准。

## HTTP 流与 WebSocket

HTTP `/v1/audio/streaming/transcriptions` 的 body 是原始音频分块，参数都放 query，不是 multipart，也不是 SSE：上传结束才返回一次最终 JSON/text。format=pcm 为 s16le 单声道，sample_rate 默认16000；wav 使用头部采样率；auto 收完再解码，不保证增量识别。

WebSocket `/v1/audio/streaming/ws?model=...` 接收二进制 PCM/WAV 帧，返回 `{type:"partial",text,is_endpoint}`；发送文本 `{"type":"finish"}` 请求最终 `{type:"final",...原生结果}`。关闭连接主要用于取消，不能保证断开后仍能读到 final；请明确发送 finish 并等 final。错误为 `{type:"error",detail}` 后关闭，常见4404/4409/4422/4500，调度错误可能映射其他44xx。WebSocket 未包含在 OpenAPI HTTP 路由表中，本节是其协议说明。

## 私有工作台 RPC 与任务

POST `/studio-api/call` JSON 包含 method、data、requestId。requestId 为32位小写十六进制稳定 ID；生成重试复用相同 ID 和相同参数，冲突不可当成新任务重放。响应始终检查 error，即使 HTTP200；result 是该方法原生返回值。generation.start/cue、character.preview、generation.alignLyrics、melody.plan/cover/listen 经 Scheduler 排队，返回任务并不表示生成完成。通过 state.get 轮询 result.state.activity/history；只有 Scheduler 确认完成后才能通过 `/studio-api/media/outputs/{fileName}` 下载，未批准或跨用户结果404。音色使用 voices 路径。

工作台可调用清单包括：state.get、preferences.save（仅个人 uiLocale）；draft.save/delete；generation.start/cue/alignLyrics/lyricTimes/lyricWords；character.save/preview/delete/discardPreview；voice.fromGeneration/suggest/update/record；timeline.import/fromGeneration；media.rename/delete；melody.inspect/transform/dismiss/plan/cover/listen/result；operation.cancel；diag.client；model.download/cancel/forget；runtime.unload。并非全部桌面 RPC 都允许浏览器调用，禁止传入任意服务器文件路径或运行外部命令。方法 data 按实际作品/模型类型解释；未列出的桌面方法403。具体字段结构以同版本 internal/schema 的 Draft/Character/State、internal/desktop/rpc.go 以及 internal/vos/server.go 的方法分支为准，不能把原生 result 统一当成任务 ID。

```bash
# 公共语音经 V-Scheduler；model 使用它发现的完整 ID。
curl --fail-with-body 'http://<vos-host>:22888/v1/audio/transcriptions' -H "Authorization: Bearer $SCHEDULER_KEY" -F 'model=<qualified-asr-model>' -F file=@sample.wav -F response_format=verbose_json
# 私有工作台使用 VOS 身份；不要提交 Scheduler 模型 Key。
curl --fail-with-body 'http://<vos-host>:22700/studio-api/call' -H "Authorization: Bearer $VOS_TOKEN" -H 'Content-Type: application/json' -d '{"method":"state.get","data":{},"requestId":"0123456789abcdef0123456789abcdef"}'
```


## 完整接口与返回

### GET /health

身份：公开接口 / 按文中调用边界

响应 200 — Native JSON response; extension catalog fields remain available.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `status` | string | 必填 |  |
| `version` | string | 必填 |  |
| `provider` | string | 必填 |  |

响应 default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 可选 |  |
| `error` | JSON | 可选 |  |

`text/plain`

`string`

### GET /ready

身份：公开接口 / 按文中调用边界

响应 200 — Native JSON response; extension catalog fields remain available.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `ready` | boolean | 必填 |  |
| `model_hub_root` | boolean | 必填 |  |
| `scheduler` | object | 必填 |  |
| `scheduler.configured` | boolean | 必填 |  |
| `scheduler.binding_revision` | integer | 可选 |  |
| `scheduler.protocol_version` | integer | 可选 |  |
| `scheduler.approved_model_count` | integer | 可选 |  |

响应 default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 可选 |  |
| `error` | JSON | 可选 |  |

`text/plain`

`string`

### GET /api/v1/about

身份：公开接口 / 按文中调用边界

响应 200 — Native JSON response; extension catalog fields remain available.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `app_id` | string | 必填 |  |
| `app_version` | string | 必填 |  |
| `profile` | string | 必填 |  |
| `provider` | string | 必填 |  |
| `port` | integer | 必填 |  |
| `supported_asr_families` | integer | 必填 |  |
| `supported_tts_families` | integer | 必填 |  |
| `supported_speaker_families` | integer | 必填 |  |
| `streaming_asr` | boolean | 必填 |  |
| `max_loaded_models` | integer | 必填 |  |
| `max_concurrent_inference` | integer | 必填 |  |
| `max_concurrent_per_model` | integer | 必填 |  |

响应 default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 可选 |  |
| `error` | JSON | 可选 |  |

`text/plain`

`string`

### GET /api/v1/discovery

身份：公开接口 / 按文中调用边界

响应 200 — Native JSON response; extension catalog fields remain available.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `service_id` | string | 必填 |  |
| `name` | string | 必填 |  |
| `protocol` | string | 必填 |  |
| `visibility` | string | 必填 |  |
| `multi_tenant` | boolean | 必填 |  |
| `authentication` | string | 必填 |  |
| `base_url` | string | 必填 |  |
| `health_path` | string | 必填 |  |
| `models` | array<VoicePublicModel> | 必填 |  |
| `scheduler` | VoiceSchedulerContract | 必填 |  |

响应 default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 可选 |  |
| `error` | JSON | 可选 |  |

`text/plain`

`string`

### GET /api/v1/models

身份：公开接口 / 按文中调用边界

响应 200 — Native JSON response; extension catalog fields remain available.

`application/json`

`array<VoiceManagedModel>`

响应 default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 可选 |  |
| `error` | JSON | 可选 |  |

`text/plain`

`string`

### GET /api/v1/models/{key}/input-limits

身份：公开接口 / 按文中调用边界

- `path: key` · string · 必填 · 

响应 200 — Native JSON response; extension catalog fields remain available.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `limits` | object  /  null | 必填 |  |
| `max_upload_bytes` | integer | 必填 |  |

响应 422 — Validation Error

`application/json`

`HTTPValidationError`

响应 default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 可选 |  |
| `error` | JSON | 可选 |  |

`text/plain`

`string`

### GET /api/v1/creative-models

身份：公开接口 / 按文中调用边界

All creator precisions and soundfonts; management metadata, not speech discovery.

响应 200 — Native JSON response; extension catalog fields remain available.

`application/json`

`array<VoiceManagedModel>`

响应 default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 可选 |  |
| `error` | JSON | 可选 |  |

`text/plain`

`string`

### POST /api/v1/models/{key}/pull

身份：公开接口 / 按文中调用边界

- `path: key` · string · 必填 · 

- `query: force` · boolean · 可选 · 

响应 202 — 202 means download accepted, not installed. Existing task returns status=active/detail; otherwise the native V-Scheduler weight-service task response is forwarded. See its /openapi.json and poll /api/v1/models for ready/error.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `status` | string | 可选 |  |
| `detail` | string | 可选 |  |
| `task_id` | string | 可选 |  |
| `model_id` | string | 可选 |  |
| `phase` | string | 可选 |  |

响应 422 — Validation Error

`application/json`

`HTTPValidationError`

响应 default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 可选 |  |
| `error` | JSON | 可选 |  |

`text/plain`

`string`

### POST /api/v1/models/{key}/stop

身份：公开接口 / 按文中调用边界

- `path: key` · string · 必填 · 

响应 200 — Native JSON response; extension catalog fields remain available.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `status` | string | 必填 |  |
| `tasks` | array<string> | 必填 |  |

响应 422 — Validation Error

`application/json`

`HTTPValidationError`

响应 default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 可选 |  |
| `error` | JSON | 可选 |  |

`text/plain`

`string`

### POST /api/v1/models/{key}/unload

身份：公开接口 / 按文中调用边界

- `path: key` · string · 必填 · 

响应 200 — Native JSON response; extension catalog fields remain available.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `status` | string | 必填 |  |
| `model` | string | 必填 |  |

响应 422 — Validation Error

`application/json`

`HTTPValidationError`

响应 default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 可选 |  |
| `error` | JSON | 可选 |  |

`text/plain`

`string`

### GET /api/v1/hotwords

身份：公开接口 / 按文中调用边界

List saved hotword sets with their derived per-model format tables.

响应 200 — Native JSON response; extension catalog fields remain available.

`application/json`

`array<VoiceHotwordSet>`

响应 default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 可选 |  |
| `error` | JSON | 可选 |  |

`text/plain`

`string`

### POST /api/v1/hotwords

身份：公开接口 / 按文中调用边界

请求体：application/json

`HotwordSetCreate`

响应 201 — Native JSON response; extension catalog fields remain available.

`application/json`

`VoiceHotwordSet`

响应 422 — Validation Error

`application/json`

`HTTPValidationError`

响应 default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 可选 |  |
| `error` | JSON | 可选 |  |

`text/plain`

`string`

### POST /api/v1/hotwords/import

身份：公开接口 / 按文中调用边界

请求体：multipart/form-data

`Body_import_hotword_set_api_v1_hotwords_import_post`

响应 201 — Native JSON response; extension catalog fields remain available.

`application/json`

`VoiceHotwordSet`

响应 422 — Validation Error

`application/json`

`HTTPValidationError`

响应 default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 可选 |  |
| `error` | JSON | 可选 |  |

`text/plain`

`string`

### GET /api/v1/hotwords/{set_id}

身份：公开接口 / 按文中调用边界

- `path: set_id` · string · 必填 · 

响应 200 — Native JSON response; extension catalog fields remain available.

`application/json`

`VoiceHotwordSet`

响应 422 — Validation Error

`application/json`

`HTTPValidationError`

响应 default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 可选 |  |
| `error` | JSON | 可选 |  |

`text/plain`

`string`

### PATCH /api/v1/hotwords/{set_id}

身份：公开接口 / 按文中调用边界

- `path: set_id` · string · 必填 · 

请求体：application/json

`HotwordSetUpdate`

响应 200 — Native JSON response; extension catalog fields remain available.

`application/json`

`VoiceHotwordSet`

响应 422 — Validation Error

`application/json`

`HTTPValidationError`

响应 default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 可选 |  |
| `error` | JSON | 可选 |  |

`text/plain`

`string`

### DELETE /api/v1/hotwords/{set_id}

身份：公开接口 / 按文中调用边界

- `path: set_id` · string · 必填 · 

响应 200 — Native JSON response; extension catalog fields remain available.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `status` | string | 必填 |  |
| `id` | string | 必填 |  |

响应 422 — Validation Error

`application/json`

`HTTPValidationError`

响应 default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 可选 |  |
| `error` | JSON | 可选 |  |

`text/plain`

`string`

### GET /api/v1/hotwords/{set_id}/export

身份：公开接口 / 按文中调用边界

- `path: set_id` · string · 必填 · 

- `query: format` · string · 可选 · text, qwen3, or zipformer

响应 200 — UTF-8 hotword file; Content-Disposition supplies its name.

`text/plain`

`string`

响应 422 — Validation Error

`application/json`

`HTTPValidationError`

响应 default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 可选 |  |
| `error` | JSON | 可选 |  |

`text/plain`

`string`

### GET /v1/models

身份：公开接口 / 按文中调用边界

响应 200 — Native JSON response; extension catalog fields remain available.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `object` | string | 必填 |  |
| `data` | array<VoicePublicModel> | 必填 |  |

响应 default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 可选 |  |
| `error` | JSON | 可选 |  |

`text/plain`

`string`

### POST /v1/audio/transcriptions

身份：公开接口 / 按文中调用边界

请求体：multipart/form-data

`Body_transcriptions_v1_audio_transcriptions_post`

响应 200 — json returns text only; verbose_json keeps native model metadata, available word/segment timestamps and optional hotword/speaker blocks. Times are seconds. text/srt/vtt return text; supported formats depend on this operation. HTTP chunked upload returns one final response, not SSE.

`application/json`

`VoiceTranscript`

`text/plain`

`string`

响应 404 — ASR model key does not exist or is not an ASR model

响应 409 — Model exists but its files are not ready

响应 413 — Audio upload is larger than the configured limit

响应 422 — Invalid field, hotword file, hotword limit, score, or model capability

响应 500 — Audio decoding or inference failed

响应 default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 可选 |  |
| `error` | JSON | 可选 |  |

`text/plain`

`string`

### POST /v1/audio/translations

身份：公开接口 / 按文中调用边界

请求体：multipart/form-data

`Body_translations_v1_audio_translations_post`

响应 200 — json returns text only; verbose_json keeps native model metadata, available word/segment timestamps and optional hotword/speaker blocks. Times are seconds. text/srt/vtt return text; supported formats depend on this operation. HTTP chunked upload returns one final response, not SSE.

`application/json`

`VoiceTranscript`

`text/plain`

`string`

响应 404 — ASR model key does not exist or is not an ASR model

响应 409 — Model exists but its files are not ready

响应 413 — Audio upload is larger than the configured limit

响应 422 — Invalid field, hotword file, hotword limit, score, or model capability

响应 500 — Audio decoding or inference failed

响应 default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 可选 |  |
| `error` | JSON | 可选 |  |

`text/plain`

`string`

### POST /v1/audio/streaming/transcriptions

身份：公开接口 / 按文中调用边界

Realtime streaming transcription over a chunked HTTP request body.

The body is audio transmitted incrementally; V-Voice feeds every chunk into
the OnlineRecognizer as it arrives and returns the final transcript when the
body ends. Use ``format=pcm`` or ``wav`` for true incremental decoding;
``auto`` buffers the whole body and decodes once.

- `query: model` · string · 必填 · Ready streaming ASR model key from /api/v1/discovery

- `query: language` · string · 可选 · Kept for contract symmetry; streaming models auto-detect

- `query: format` · string · 可选 · pcm (raw s16le mono), wav (uncompressed mono RIFF), or auto (buffered, decoded at end)

- `query: sample_rate` · integer · 可选 · Sample rate for format=pcm; wav uses its header

- `query: response_format` · string · 可选 · verbose_json, json, or text

- `query: hotwords` · string · 可选 · One-shot comma/newline-separated phrases for hotword-capable streaming models

- `query: hotwords_set` · array<string> | null · 可选 · Repeatable saved hotword set id from /api/v1/hotwords

- `query: hotwords_score` · number | null · 可选 · Contextual-bias score from 0 to 10; streaming Zipformer only

- `query: speaker_model` · string · 可选 · Optional ready speaker model key; adds a speaker attribution block to the final response

- `query: speaker_threshold` · number | null · 可选 · Cosine similarity threshold for the speaker block; default 0.6

请求体：application/octet-stream

`string`

响应 200 — json returns text only; verbose_json keeps native model metadata, available word/segment timestamps and optional hotword/speaker blocks. Times are seconds. text/srt/vtt return text; supported formats depend on this operation. HTTP chunked upload returns one final response, not SSE.

`application/json`

`VoiceTranscript`

`text/plain`

`string`

响应 404 — ASR model key does not exist or is not an ASR model

响应 409 — Model exists but its files are not ready

响应 413 — Audio upload is larger than the configured limit

响应 422 — Invalid field, hotword file, hotword limit, score, or model capability

响应 500 — Audio decoding or inference failed

响应 default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 可选 |  |
| `error` | JSON | 可选 |  |

`text/plain`

`string`

### GET /api/v1/speakers

身份：公开接口 / 按文中调用边界

List enrolled voiceprints (management plane).

响应 200 — Native JSON response; extension catalog fields remain available.

`application/json`

`array<VoiceSpeaker>`

响应 default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 可选 |  |
| `error` | JSON | 可选 |  |

`text/plain`

`string`

### POST /api/v1/speakers

身份：公开接口 / 按文中调用边界

Enroll a speaker voiceprint from uploaded audio.

请求体：multipart/form-data

`Body_enroll_speaker_api_v1_speakers_post`

响应 201 — Native JSON response; extension catalog fields remain available.

`application/json`

`VoiceSpeaker`

响应 422 — Validation Error

`application/json`

`HTTPValidationError`

响应 default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 可选 |  |
| `error` | JSON | 可选 |  |

`text/plain`

`string`

### DELETE /api/v1/speakers/{speaker_id}

身份：公开接口 / 按文中调用边界

- `path: speaker_id` · string · 必填 · 

响应 200 — Native JSON response; extension catalog fields remain available.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `status` | string | 必填 |  |
| `id` | string | 必填 |  |

响应 422 — Validation Error

`application/json`

`HTTPValidationError`

响应 default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 可选 |  |
| `error` | JSON | 可选 |  |

`text/plain`

`string`

### GET /v1/audio/speakers

身份：公开接口 / 按文中调用边界

Public list of enrolled voiceprints for dependent clients.

- `query: model` · string · 可选 · Ready speaker model key

响应 200 — Native JSON response; extension catalog fields remain available.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `object` | string | 必填 |  |
| `model` | string | 必填 |  |
| `default_threshold` | number | 必填 |  |
| `speakers` | array<VoiceSpeaker> | 必填 |  |
| `data` | array<VoiceSpeaker> | 必填 |  |

响应 422 — Validation Error

`application/json`

`HTTPValidationError`

响应 default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 可选 |  |
| `error` | JSON | 可选 |  |

`text/plain`

`string`

### POST /v1/audio/speakers/identify

身份：公开接口 / 按文中调用边界

Identify which enrolled speaker (if any) spoke in the audio.

请求体：multipart/form-data

`Body_speakers_identify_v1_audio_speakers_identify_post`

响应 200 — Native JSON response; extension catalog fields remain available.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `object` | string | 必填 |  |
| `model` | string | 必填 |  |
| `threshold` | number | 必填 |  |
| `identified` | boolean | 必填 |  |
| `speaker` | object  /  null | 必填 |  |
| `score` | number | 必填 |  |
| `ranked` | array<object> | 必填 |  |

响应 422 — Validation Error

`application/json`

`HTTPValidationError`

响应 default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 可选 |  |
| `error` | JSON | 可选 |  |

`text/plain`

`string`

### POST /v1/audio/speakers/verify

身份：公开接口 / 按文中调用边界

Verify the audio against one enrolled speaker voiceprint.

请求体：multipart/form-data

`Body_speakers_verify_v1_audio_speakers_verify_post`

响应 200 — Native JSON response; extension catalog fields remain available.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `object` | string | 必填 |  |
| `model` | string | 必填 |  |
| `speaker` | VoiceSpeaker | 必填 |  |
| `threshold` | number | 必填 |  |
| `score` | number | 必填 |  |
| `verified` | boolean | 必填 |  |

响应 422 — Validation Error

`application/json`

`HTTPValidationError`

响应 default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 可选 |  |
| `error` | JSON | 可选 |  |

`text/plain`

`string`

### POST /transcribe

身份：公开接口 / 按文中调用边界

- `query: model` · string · 可选 · 

- `query: lang` · string · 可选 · 

请求体：application/octet-stream

`string`

响应 200 — json returns text only; verbose_json keeps native model metadata, available word/segment timestamps and optional hotword/speaker blocks. Times are seconds. text/srt/vtt return text; supported formats depend on this operation. HTTP chunked upload returns one final response, not SSE.

`application/json`

`VoiceTranscript`

`text/plain`

`string`

响应 422 — Validation Error

`application/json`

`HTTPValidationError`

响应 default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 可选 |  |
| `error` | JSON | 可选 |  |

`text/plain`

`string`

### POST /v1/audio/speech

身份：公开接口 / 按文中调用边界

请求体：application/json

`SpeechRequest`

响应 200 — Binary audio in response_format; raw pcm is not a WAV container.

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

响应 422 — Validation Error

`application/json`

`HTTPValidationError`

响应 default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 可选 |  |
| `error` | JSON | 可选 |  |

`text/plain`

`string`

### GET /v1/audio/voices

身份：公开接口 / 按文中调用边界

- `query: model` · string · 可选 · 

响应 200 — Native JSON response; extension catalog fields remain available.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `object` | string | 必填 |  |
| `model` | string | 必填 |  |
| `default_voice` | string | 必填 |  |
| `voices` | array<object> | 必填 |  |
| `data` | array<object> | 必填 |  |

响应 422 — Validation Error

`application/json`

`HTTPValidationError`

响应 default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 可选 |  |
| `error` | JSON | 可选 |  |

`text/plain`

`string`

### GET /api/v1/scheduler/binding

身份：公开接口 / 按文中调用边界

Public redacted automatic-binding status; never returns service credentials.

响应 200 — Native JSON response; extension catalog fields remain available.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `protocol_version` | integer | 必填 |  |
| `binding_revision` | integer | 必填 |  |
| `configured` | boolean | 必填 |  |
| `approved_model_count` | integer | 必填 |  |

响应 default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 可选 |  |
| `error` | JSON | 可选 |  |

`text/plain`

`string`

### POST /api/v1/scheduler/binding

身份：VOSApplicationBearer

VOS Scheduler application only: validate and atomically apply a versioned binding.

The server-to-server JSON contract is documented in docs/scheduler-auto-binding.md.
User tokens, including administrator user tokens, cannot configure this endpoint.

请求体：application/json

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `protocol_version` | integer | 必填 |  · const=1 |
| `binding_revision` | integer | 必填 |  · minimum=1.0 |
| `app_id` | string | 必填 |  · const="com.ictrek.v-voice" |
| `url` | string | 必填 | Must match fixed VVOICE_SCHEDULER_URL. Default is http://v-scheduler:8080/scheduler/api/v1; v-router is a compatibility alias. The controller also listens at http://v-scheduler:38120/api/v1. |
| `token` | string | 必填 |  · minLength=32 · maxLength=4096 |
| `executor_token` | string | 必填 |  · minLength=32 · maxLength=4096 |
| `upstream_url` | string | 必填 | Must match V-Voice's advertised native upstream URL |
| `models` | object | 必填 |  |
| `gateway_executors` | object | 可选 |  |
| `secondary_models` | object | 可选 |  |
| `input_limits_version` | integer  /  null | 可选 |  |
| `mixed_input_limits_version` | integer  /  null | 可选 |  |
| `legacy_unbounded_models` | array<string>  /  null | 可选 | Explicit old approvals only; disjoint from model_limits, together covering models. Does not grant an executor or alter task types. |
| `model_limits` | object  /  null | 可选 |  |
| `execution_settings` | object  /  null | 可选 | Optional calibrated runtime settings retained for binding-document compatibility. |

响应 200 — Native JSON response; extension catalog fields remain available.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `protocol_version` | integer | 必填 |  |
| `binding_revision` | integer | 必填 |  |
| `configured` | boolean | 必填 |  |
| `approved_model_count` | integer | 必填 |  |

响应 default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 可选 |  |
| `error` | JSON | 可选 |  |

`text/plain`

`string`

### POST /studio-api/call

身份：VOSUserBearer

Private user RPC: projects, music/score generation, job polling/cancellation and voices.

Returns result or error (check error even on HTTP 200). generation.start returns a job ID;
poll state.get activity/history and read results only after Scheduler-confirmed success.
Model download/cancel additionally require an administrator. The Go adapter enforces
identity, method allowlist, payload validation, user isolation and scheduling.
These are not OpenAI-standard music endpoints or gateway-forwarded public APIs.

请求体：application/json

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `method` | string | 必填 |  · enum=["state.get", "draft.save", "draft.delete", "generation.start", "generation.cue", "character.save", "character.preview", "character.delete", "character.discardPreview", "voice.fromGeneration", "voice.update", "voice.record", "timeline.import", "media.rename", "media.delete", "operation.cancel", "preferences.save", "model.download", "model.cancel", "model.forget", "runtime.unload", "diag.client"] |
| `data` | object | 必填 | Method-specific payload. generation.start accepts a Draft with bare creator modelId; kind music or score selects music generation or soundfont rendering. |
| `requestId` | string | 必填 | Stable generation idempotency key; retry with identical data |

响应 200 — Check error even on HTTP200. result is method-specific: state.get returns state/catalog metadata, generation returns job ID; poll until confirmed success before reading media. See the complete workbench workflow and native schema in the guide.

`application/json`

`object | object`

响应 default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 可选 |  |
| `error` | JSON | 可选 |  |

`text/plain`

`string`

### GET /studio-api/media/{kind}/{file_name}

身份：VOSUserBearer

Download a reference voice or completed output belonging to the authenticated user.

Obtain file_name from state.get history/voices; internal filesystem paths are not accepted.

- `path: kind` · string · 必填 · 

- `path: file_name` · string · 必填 · 

响应 200 — User-owned audio file

`application/json`

`JSON`

`audio/wav`

`string`

响应 401 — VOS user authentication required

响应 404 — Missing, foreign or not-yet-approved result

响应 422 — Validation Error

`application/json`

`HTTPValidationError`

响应 default — Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 可选 |  |
| `error` | JSON | 可选 |  |

`text/plain`

`string`

## 共享数据结构

字段保持 API 的原始拼写；JSON 任意扩展字段按其所属服务说明解释。

### Body_enroll_speaker_api_v1_speakers_post

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `name` | string | 必填 | Display name of the enrolled speaker |
| `file` | string | 必填 | Enrollment audio (speech from this speaker) |
| `model` | string | 可选 | Ready speaker model key · default="speaker-campplus-zh-en" |

### Body_import_hotword_set_api_v1_hotwords_import_post

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `name` | string | 必填 | Display name of the hotword set |
| `file` | string | 必填 | UTF-8 hotword table, one phrase per line |

### Body_speakers_identify_v1_audio_speakers_identify_post

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `file` | string | 必填 | Audio to attribute to an enrolled speaker |
| `model` | string | 可选 | Ready speaker model key · default="speaker-campplus-zh-en" |
| `threshold` | number | 可选 | Cosine similarity threshold · default=0.6 · minimum=0.0 · maximum=1.0 |

### Body_speakers_verify_v1_audio_speakers_verify_post

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `file` | string | 必填 | Audio to verify against a speaker |
| `speaker` | string | 必填 | Enrolled speaker id or exact name |
| `model` | string | 可选 | Ready speaker model key · default="speaker-campplus-zh-en" |
| `threshold` | number | 可选 | Cosine similarity threshold · default=0.6 · minimum=0.0 · maximum=1.0 |

### Body_transcriptions_v1_audio_transcriptions_post

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `file` | string | 必填 | Audio file to recognize |
| `model` | string | 必填 | Ready ASR model key from /api/v1/discovery |
| `language` | string | 可选 | Language code; empty lets the model decide · default="" |
| `response_format` | string | 可选 | json, verbose_json, text, srt, or vtt · default="json" |
| `hotwords` | string | 可选 | Comma/newline-separated phrases; SeACo, Qwen3-ASR or Zipformer · default="" |
| `hotwords_file` | string  /  null | 可选 | UTF-8 text, one phrase per line |
| `hotwords_score` | number  /  null | 可选 | Zipformer contextual-bias score from 0 to 10; ignored by other models |
| `hotwords_set` | array<string>  /  null | 可选 | Repeatable saved hotword set id from /api/v1/hotwords; merged with hotwords and hotwords_file |
| `timestamp_granularities[]` | array<string>  /  null | 可选 | Repeat with word and/or segment; verbose_json includes every available timestamp granularity |
| `speaker_model` | string | 可选 | Optional ready speaker model key; adds a speaker attribution block to verbose_json · default="" |
| `speaker_threshold` | number  /  null | 可选 | Cosine similarity threshold for the speaker block; default 0.6 |

### Body_translations_v1_audio_translations_post

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `file` | string | 必填 | Audio file to translate |
| `model` | string | 必填 | Ready ASR model key from /api/v1/discovery |
| `language` | string | 可选 | Input language code; empty lets the model decide · default="" |
| `response_format` | string | 可选 | json, verbose_json, text, srt, or vtt · default="json" |
| `hotwords` | string | 可选 | Comma/newline-separated phrases; SeACo, Qwen3-ASR or Zipformer · default="" |
| `hotwords_file` | string  /  null | 可选 | UTF-8 text, one phrase per line |
| `hotwords_score` | number  /  null | 可选 | Zipformer contextual-bias score from 0 to 10; ignored by other models |
| `hotwords_set` | array<string>  /  null | 可选 | Repeatable saved hotword set id from /api/v1/hotwords; merged with hotwords and hotwords_file |
| `timestamp_granularities[]` | array<string>  /  null | 可选 | Repeat with word and/or segment; verbose_json includes every available timestamp granularity |
| `speaker_model` | string | 可选 | Optional ready speaker model key; adds a speaker attribution block to verbose_json · default="" |
| `speaker_threshold` | number  /  null | 可选 | Cosine similarity threshold for the speaker block; default 0.6 |

### HTTPValidationError

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | array<ValidationError> | 可选 |  |

### HotwordSetCreate

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `name` | string | 必填 | Display name of the hotword set · minLength=1 · maxLength=64 |
| `phrases` | array<string> | 可选 | Phrases; preferred over phrases_text when both are sent |
| `phrases_text` | string | 可选 | Comma/newline-separated phrases; used when phrases is empty · default="" · maxLength=8192 |

### HotwordSetUpdate

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `name` | string  /  null | 可选 |  |
| `phrases` | array<string>  /  null | 可选 |  |

### SpeechRequest

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `model` | string | 必填 | Ready TTS model key from /api/v1/discovery |
| `input` | string | 必填 | Text to synthesize · minLength=1 · maxLength=20000 |
| `voice` | string | 可选 | Voice ID returned by /v1/audio/voices for this model · default="default" |
| `response_format` | string | 可选 | Binary output audio format · default="mp3" · enum=["mp3", "opus", "aac", "flac", "wav", "pcm"] |
| `speed` | number | 可选 | Speech speed multiplier · default=1.0 · minimum=0.25 · maximum=4.0 |
| `language` | string | 可选 | Language code; empty uses the model/voice default · default="" |
| `reference_audio` | string | 可选 | audio.cpp only: base64 reference audio; not a server file path · default="" · maxLength=28000000 |
| `reference_text` | string | 可选 | audio.cpp only: reference audio transcript · default="" · maxLength=2000 |
| `voice_description` | string | 可选 | audio.cpp only: voice design instruction · default="" · maxLength=500 |
| `emotion_text` | string | 可选 | IndexTTS only: emotion instruction; requires emotion_control capability · default="" · maxLength=500 |
| `emotion_strength` | number | 可选 | IndexTTS only: emotion strength · default=0.6 · minimum=0.0 · maximum=1.0 |

### ValidationError

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `loc` | array<string  /  integer> | 必填 |  |
| `msg` | string | 必填 |  |
| `type` | string | 必填 |  |
| `input` | JSON | 可选 |  |
| `ctx` | object | 可选 |  |

### VoiceManagedModel

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `key` | string | 必填 |  |
| `name` | string | 必填 |  |
| `kind` | string | 必填 |  |
| `status` | string | 必填 |  |
| `family` | string | 可选 |  |
| `backend` | string | 可选 |  |
| `modelscope_repo` | string | 可选 |  |
| `languages` | array<string> | 可选 |  |
| `description` | string | 可选 |  |
| `streaming` | boolean | 可选 |  |
| `translation` | boolean | 可选 |  |
| `loaded` | boolean | 可选 |  |
| `inference_ready` | boolean | 可选 |  |
| `inference_error` | string | 可选 |  |
| `error` | string | 可选 |  |
| `progress` | number  /  null | 可选 |  |
| `downloaded_bytes` | integer  /  null | 可选 |  |
| `total_bytes` | integer  /  null | 可选 |  |
| `import_required` | boolean | 可选 |  |
| `voices` | object | 可选 |  |
| `voices.{key}.sid` | integer | 必填 |  |
| `voices.{key}.language` | string | 必填 |  |
| `hotwords` | object | 可选 |  |
| `hotwords.supported` | boolean | 必填 |  |
| `hotwords.formats` | array<string> | 可选 |  |
| `hotwords.score` | boolean | 可选 |  |
| `hotwords.default_score` | number | 可选 |  |
| `timestamps` | object | 可选 |  |
| `timestamps.word` | boolean | 必填 |  |
| `timestamps.segment` | boolean | 必填 |  |
| `timestamps.source` | string | 必填 |  |

### VoicePublicModel

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `id` | string | 必填 |  |
| `object` | string | 必填 |  |
| `owned_by` | string | 必填 |  |
| `kind` | string | 必填 |  |
| `capabilities` | array<string> | 必填 |  |
| `endpoints` | array<string> | 必填 |  |
| `languages` | array<string> | 必填 |  |
| `hotwords` | object | 可选 |  |
| `hotwords.supported` | boolean | 必填 |  |
| `hotwords.formats` | array<string> | 可选 |  |
| `hotwords.score` | boolean | 可选 |  |
| `hotwords.default_score` | number | 可选 |  |
| `timestamps` | object | 可选 |  |
| `timestamps.word` | boolean | 必填 |  |
| `timestamps.segment` | boolean | 必填 |  |
| `timestamps.source` | string | 必填 |  |
| `streaming` | object | 可选 |  |
| `streaming.supported` | boolean | 必填 |  |
| `streaming.transports` | array<string> | 必填 |  |
| `streaming.hotwords` | boolean | 必填 |  |
| `voices` | object | 可选 |  |
| `voices.endpoint` | string | 必填 |  |
| `voices.default` | string | 必填 |  |
| `voices.count` | integer | 必填 |  |

### VoiceHotwordSet

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `id` | string | 必填 |  |
| `name` | string | 必填 |  |
| `phrases` | array<string> | 必填 |  |
| `phrase_count` | integer | 必填 |  |
| `created_at` | string | 必填 |  |
| `updated_at` | string | 必填 |  |
| `formats` | array<object> | 必填 |  |

### VoiceSpeaker

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `id` | string | 必填 |  |
| `name` | string | 必填 |  |
| `model` | string | 必填 |  |
| `created_at` | string | 必填 |  |
| `dimension` | integer | 必填 |  |

### VoiceTranscript

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `text` | string | 必填 |  |
| `language` | string | 可选 |  |
| `duration` | number | 可选 |  |
| `words` | array<object> | 可选 |  |
| `segments` | array<object> | 可选 |  |
| `tokens` | array<string> | 可选 |  |
| `timestamps` | array<number> | 可选 |  |
| `emotion` | string | 可选 |  |
| `event` | string | 可选 |  |
| `streaming` | boolean | 可选 |  |
| `hotwords` | object | 可选 |  |
| `hotwords.requested` | boolean | 必填 |  |
| `hotwords.supported` | boolean | 必填 |  |
| `hotwords.applied` | boolean | 必填 |  |
| `hotwords.sets` | array<object> | 必填 |  |
| `hotwords.score_applied` | number  /  null | 必填 |  |
| `hotwords.ignored` | boolean | 必填 |  |
| `speaker` | object | 可选 |  |
| `speaker.model` | string | 可选 |  |
| `speaker.threshold` | number | 可选 |  |
| `speaker.identified` | boolean | 可选 |  |
| `speaker.speaker` | object  /  null | 可选 |  |
| `speaker.score` | number | 可选 |  |
| `speaker.ranked` | array<object> | 可选 |  |

### VoiceSchedulerContract

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `protocol_version` | integer | 必填 |  |
| `input_limits_version` | integer | 必填 |  |
| `mixed_input_limits_version` | integer | 必填 |  |
| `app_id` | string | 必填 |  |
| `binding_endpoint` | string | 必填 |  |
| `lifecycle_protocol_version` | integer | 必填 |  |
| `executor_base_url` | string | 必填 |  |
| `upstream_url` | string | 必填 |  |
| `sync_models` | array<object> | 必填 |  |
| `async_models` | array<object> | 必填 |  |
| `num_threads` | integer | 必填 |  |
| `max_concurrent_inference` | integer | 必填 |  |
| `cpu_models` | array<string> | 必填 |  |
| `provider` | string | 必填 |  |
