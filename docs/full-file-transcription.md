# 全文件音频转写

`POST /v1/audio/transcriptions/full` 面向服务调用方。调用方上传一个原始音频文件，
V-Voice 在服务端完成解码、单声道转换、分段、逐段调度准入和文本合并，不要求调用方
安装 FFmpeg 或了解模型分段细节。

该接口只用于转写。热词、声纹归属和翻译仍使用
`POST /v1/audio/transcriptions` 或 `/v1/audio/translations`，原有单段行为不变。

## 前置发现

先读取 `GET /api/v1/models/{key}/input-limits`：

```json
{
  "limits": {
    "duration_seconds": 20,
    "sample_rate": 24000,
    "hotwords_characters": 0,
    "input_bytes": 1048576
  },
  "max_upload_bytes": 209715200,
  "full_transcription": {
    "endpoint": "/v1/audio/transcriptions/full",
    "processing_version": "full-file-v1",
    "max_upload_bytes": 209715200,
    "max_duration_seconds": 1800,
    "max_parts": 512,
    "max_source_sample_rate": 192000,
    "max_source_channels": 8,
    "response_formats": ["json", "srt", "text", "verbose_json", "vtt"]
  }
}
```

- `limits` 仍是单段模型校准，不会被全文件接口扩大。
- 全文件上传大小取 `full_transcription.max_upload_bytes`，不是
  `limits.input_bytes`。后者是每段经服务端转换后的 WAV 上限。
- `limits=null` 或缺少 `full_transcription` 时，调用方不应使用该接口。

## 请求

```bash
curl 'http://<VOS-IP>:22700/v1/audio/transcriptions/full' \
  -F 'file=@meeting.m4a' \
  -F 'model=sensevoice-int8' \
  -F 'language=' \
  -F 'response_format=json'
```

仓库内也提供真实服务检查脚本：

```bash
python3 scripts/check-full-transcription.py \
  --base-url 'http://<VOS-IP>:22700' \
  --model sensevoice-int8 \
  --input meeting.m4a \
  --expect-text 'meeting'
```

字段：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `file` | 是 | 原始文件。支持 FFmpeg 常见音频容器/编码：WAV、MP3、FLAC、OGG/Vorbis、M4A/AAC、CAF、AIFF、AMR、AC3、WMA/ASF；只取首个音轨并混为单声道。 |
| `model` | 是 | 已就绪且具备完整输入校准的 ASR 模型 key。 |
| `language` | 否 | 模型语言提示，空值自动检测。 |
| `response_format` | 否 | `json`（默认）、`verbose_json`、`text`、`srt`、`vtt`。 |

不支持向该接口同时提交 `hotwords*`、`speaker_model`、`timestamp_granularities`
或翻译任务。需要这些能力时继续使用原有单段接口。

## 成功响应

只有全部计划段落成功，才返回 HTTP 2xx 和 `complete: true`。

```json
{
  "text": "完整识别文本",
  "complete": true,
  "model": "sensevoice-int8",
  "task": "transcribe",
  "duration": 15.2,
  "parts_total": 1,
  "speech_detected": true,
  "audio": {
    "source_sample_rate": 48000,
    "source_channels": 2,
    "decoded_sample_rate": 16000
  },
  "cache": {
    "processing_version": "full-file-v1",
    "model_revision": "1f0c...",
    "source_sha256": "4a2e...",
    "key": "b64d..."
  }
}
```

`verbose_json` 还包含合并后的 `tokens`、`timestamps`、`words`、`segments` 和
`parts[]`。`parts[]` 中每项包含 `index`、原始音频中的 `start`/`end`、
`duration` 和该段文本。

空语音是成功结果：HTTP 2xx、`complete: true`、`text: ""`、
`speech_detected: false`。VAD 确认无语音时 `parts_total` 为 0；
若运行时 VAD 不可用而退回整段识别，模型返回空文本时 `parts_total` 可为 1。

`text`、`srt`、`vtt` 响应同样携带：

- `X-VVoice-Transcription-Complete: true`
- `X-VVoice-Cache-Key`
- `X-VVoice-Processing-Version`

所有响应使用 `Cache-Control: no-store`。

## 失败语义

失败时绝不把部分文本放在顶层 `text`，也不返回 `complete: true`。已完成部分只出现在
明确标记的 `partial` 中：

```json
{
  "detail": "part 2: Local compute resources are busy",
  "complete": false,
  "error": {
    "code": "service_busy",
    "message": "part 2: Local compute resources are busy",
    "status": 429,
    "part_number": 2,
    "parts_total": 3,
    "retryable": true
  },
  "partial": {
    "complete": false,
    "text": "第一段文本",
    "duration": 75.0,
    "parts_completed": 1,
    "parts_total": 3,
    "parts": [
      {
        "index": 0,
        "start": 0.0,
        "end": 20.0,
        "duration": 20.0,
        "text": "第一段文本"
      }
    ]
  }
}
```

调用方必须把非 2xx 视为没有完整结果。若需要重试，应重试整个文件；服务端没有断点
续传或持久化部分任务。

| HTTP | `error.code` | 含义 |
| --- | --- | --- |
| 403 | `admission_denied` | 请求了强制准入但缺少有效管理员授权，或调度器拒绝身份。 |
| 404 | `model_not_found` | 模型 key 不存在或不是 ASR 模型。 |
| 409 | `model_not_ready` | 模型文件尚未就绪。 |
| 409 | `direct_admission_required` | 请求带了 V-Router 单次许可头；该接口需要逐段直连准入。 |
| 413 | `audio_file_too_large` | 编码文件超过上传上限。 |
| 413 | `audio_duration_too_large` | 解码时长超过总时长上限。 |
| 413 | `too_many_audio_parts` | 分段数超过上限。 |
| 415 | `unsupported_audio` | 无音轨、损坏、不支持的容器/编码，或容器尝试使用未批准 demuxer。 |
| 422 | `source_sample_rate_too_large` | 源采样率超过安全上限（普通 48 kHz 可接受）。 |
| 422 | `source_channels_too_large` | 源声道数超过安全上限。 |
| 422 | `empty_audio` | 文件为空或没有可解码采样。 |
| 422 | `invalid_request` | multipart 或字段校验失败；`error.details` 给出字段原因。 |
| 422 | `invalid_response_format` | `response_format` 不在支持列表中。 |
| 422 | `invalid_input` | 字段或单段输入指标不符合模型校准。 |
| 429 | `service_busy` | 某段调度忙碌；响应可能带 `Retry-After`。 |
| 500 | `transcription_failed` | 推理或结果组装失败。 |
| 503 | `model_not_calibrated` | 模型没有完整输入校准。 |
| 503 | `invalid_model_calibration` | 校准值无法产生合法的 16 kHz 分段。 |
| 503 | `scheduler_unavailable` | 调度配置、许可或服务身份不可用。 |
| 503 | `audio_decoder_unavailable` | 镜像缺少服务端 FFmpeg/ffprobe。 |
| 503 | `scheduler_stopped` | 调度停止请求到达，后续段落不再提交。 |
| 504 | `audio_decode_timeout` | 单次 FFmpeg/ffprobe 解码超时，子进程已终止。 |
| 504 | `transcription_timeout` | 解码或总处理时限到期。 |

## 分段与调度

1. 检查编码大小、容器时长、源采样率和源声道数。
2. 使用 `ffprobe` 探测，使用镜像内 `ffmpeg` 有界解码为单声道 16 kHz PCM；
   只允许本地 file 协议和音频 demuxer，阻止播放列表等容器读取其他文件。
3. 短音频只转换并用 VAD 判定是否静音，不切分。长音频优先使用 VAD，
   在接近模型上限时再选低能量切点；VAD 不可用时退回有界固定分段。
4. 每段 WAV 不超过模型批准的 `duration_seconds` 和 `input_bytes`；不增加未校准裕量。
5. 每段在模型加载前重新校验，并通过独立 V-Scheduler permit 准入；成功后依次合并。
6. 临时文件在成功、失败、超时或取消后清理。

取消或断开会停止解码和后续段落；已经进入原生推理的当前段不能安全抢占。该次许可会
等原生线程退出后按原有停止核验流程释放，因此“请求已断开”不等于“远端计算已停止”。

## 配置

| 环境变量 | 默认值 | 作用 |
| --- | --- | --- |
| `VVOICE_MAX_UPLOAD_MB` | 200 | 编码文件总大小。 |
| `VVOICE_FULL_TRANSCRIPTION_MAX_SECONDS` | 1800 | 解码后的总时长。 |
| `VVOICE_FULL_TRANSCRIPTION_TIMEOUT_SECONDS` | 1800 | 单次请求总处理时限。 |
| `VVOICE_FULL_TRANSCRIPTION_DECODE_TIMEOUT_SECONDS` | 300 | 单次 ffprobe/ffmpeg 时限。 |
| `VVOICE_FULL_TRANSCRIPTION_MAX_PARTS` | 512 | 最大调度分段数。 |
| `VVOICE_FULL_TRANSCRIPTION_MAX_SOURCE_SAMPLE_RATE` | 192000 | 源采样率安全上限。 |
| `VVOICE_FULL_TRANSCRIPTION_MAX_SOURCE_CHANNELS` | 8 | 源声道数安全上限。 |

所有 VOS 服务镜像已安装系统 `ffmpeg`/`ffprobe`。调用方和 v-harness 租户不需要安装
解码器。

## 缓存语义

服务端不持久化转写结果。调用方可在本地按
`cache.key = SHA256(source_sha256 + model_revision + language + processing_version)`
复用文本。模型权重/安装文件变化会改变 `model_revision`，分段或解码规则变化会改变
`processing_version`；任一项变化都必须重新转写。不要只按模型 key 和文件名缓存。

## v-harness 插件接入

插件源码由本仓库的
[`integrations/v-harness/tool-v-yovoice`](../integrations/v-harness/tool-v-yovoice)
维护，以预构建 `.tgz` 安装到 v-harness，不编入 VOS 服务镜像。本地发布构建使用明确锁定的
v-harness 源码版本，脚本会临时载入插件并执行插件测试、lint、Host/Client 编译与完整打包：

```bash
V_HARNESS_REPO=/absolute/path/to/v-harness \
  pnpm --dir integrations/v-harness/tool-v-yovoice build:release
```

插件遵循以下接口约束：

1. 从 `input-limits.full_transcription` 判断服务支持，并读取
   `max_upload_bytes`、`max_duration_seconds`、`processing_version`。
2. 原文件大小上限改为
   `min(插件 maxUploadBytes, full_transcription.max_upload_bytes)`；
   不再用 `limits.input_bytes` 拒绝原始文件。
3. 保留原始字节，直接提交到 `POST /v1/audio/transcriptions/full`，
   默认使用 `response_format=json`。不要自行转码或分段。
4. 仅把 HTTP 2xx 且 `complete === true` 视为新转写。非 2xx 时不得把
   `partial.text` 写成成功原文；可显示 `error.code` 并提示重试。
5. 在会话缓存记录中加入 `cache.key`（或至少
   `processing_version + model_revision`），模型或服务规则变化后自动失效。
6. `requestTimeoutMs` 应覆盖服务端总时限；默认 600000 ms 只适合较短文件。
7. 插件配置的 V-yovoice 地址必须能被租户直接访问，且不应经过带单次 permit 的
   V-Router 转发；不要修改网关隔离策略来绕过这一点。
8. 可选地把 `duration`、`parts_total`、`cache` 和 `complete` 保存到结果元数据，
   便于审计“完整”来源；不要向模型声称未读取的 partial 文本是完整原文。
