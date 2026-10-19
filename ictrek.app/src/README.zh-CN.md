# V-Voice

统一工作台提供语音、歌曲生成、编曲和「配乐生成」。原生配乐支持 ACE-Step 1.5
Turbo、Stable Audio 3 Small-Music / Medium、MusicGen Small，在「模型管理 →
创作模型与音色库」经 V-Scheduler / ModelScope 安装，保留 WAV/FLAC 试听下载。
公共配乐扩展 API 为 `POST /v1/audio/music/generations`；MusicGen 最长 30 秒。
模型就绪不等于计算已批准：新音乐模型须取得 V-Voice 自己的资源校准与调度绑定。
原有歌曲、编曲和以下语音服务功能继续保留。

V-Voice 保留基于 ONNX 的公共 ASR / 流式 ASR / TTS / 声纹服务。模型由 V-Scheduler 内置模型仓库安装并由所有用户共享；其统一网关通过发现接口接入公共能力，无需独立安装 Model Hub 或 V-Router。

新增 `seaco-paraformer-zh`，模型源为 `vivibit/v-voice-seaco-paraformer-zh-int8`。
SeACo 在所有 profile 上使用 CPU ONNX Runtime，支持中文整句转写与神经热词，
复用请求热词、UTF-8 文件和已保存热词集；每条热词去除空格后最多 10 字符。
不需增强分数；不支持翻译、流式和词时间戳。原 `paraformer-zh` 保留。

宿主机 OpenAI 兼容接口：`http://<VOS-IP>:22700/v1`。

模型在首次推理请求时热加载，默认最多常驻 2 个推理实例。默认全局并发推理为 2、
单模型 key 并发为 2，超出的请求会排队；可在安装配置中调整常驻数和两个并发上限。
页头「关于」按钮展示应用版本（由安装包 `APP_VERSION` 环境变量注入）、运行
profile 与推理 provider；热词页可对固化热词集增删改查并导出模型格式，声纹页
支持声纹注册、1:N 归属识别与 1:1 验证，TTS 合成结果可直接下载。

## 流式识别

`zipformer-zh-streaming`、`zipformer-en-streaming` 支持音频流式输入与实时识别：

```bash
# HTTP 分块：边传边解码，结束返回最终转写
curl 'http://<VOS-IP>:22700/v1/audio/streaming/transcriptions?model=zipformer-zh-streaming&format=pcm' \
  --header 'Transfer-Encoding: chunked' --data-binary @audio.pcm

# WebSocket：二进制 PCM 帧增量返回 partial，发送 {"type":"finish"} 后返回 final
# ws://<VOS-IP>:22700/v1/audio/streaming/ws?model=zipformer-en-streaming
```

## 声纹识别

`speaker-campplus-zh-en`（中英）提供声纹能力：管理面 `POST /api/v1/speakers`
注册声纹（名称 + 音频，建议 ≥10 秒），public 面 `POST
/v1/audio/speakers/identify` 做 1:N 归属、`POST /v1/audio/speakers/verify` 做
1:1 验证、`GET /v1/audio/speakers` 列出声纹库；余弦相似度阈值默认 0.6。声纹注册一次即持久化（应用存储 `data/speakers.json`），永久可比对。

组合模式（边转写边声纹）：转写接口与流式接口均可带可选 `speaker_model`
（及 `speaker_threshold`），同一段音频在转写的同时完成归属比对，`verbose_json`
/ 流式最终响应附带 `speaker` 块；缺省该参数时与 OpenAI 完全兼容：

```bash
curl 'http://<VOS-IP>:22700/v1/audio/transcriptions' \
  -F file=@sample.wav -F model=sensevoice-int8 \
  -F speaker_model=speaker-campplus-zh-en -F response_format=verbose_json
```

## 热词 ASR API

Qwen3-ASR（0.6B / 1.7B）、`zipformer-en` 与两个流式 Zipformer 支持热词：
`hotwords` 一次性文本、`hotwords_file` UTF-8 文件、`hotwords_set` 已保存热词集
（可重复），三者在服务端合并去重；最多 64 个、合计 4096 UTF-8 bytes。Zipformer
系还支持 `0..10` 的 `hotwords_score`（默认 `1.5`）。固化热词集经
`/api/v1/hotwords` 增删改查，上传热词表后服务端自动后台转化为
`text` / `qwen3` / `zipformer` 三种模型格式。

```bash
curl 'http://<VOS-IP>:22700/v1/audio/transcriptions' \
  -F file=@sample.wav -F model=qwen3-asr-0.6b \
  -F 'hotwords=华为,昇腾,V-Voice' -F hotwords_set=hw_1a2b3c4d \
  -F language=zh -F response_format=verbose_json
```

SenseVoice、Paraformer、Zipformer 的 `verbose_json` 包含 OpenAI 风格
`words[]`/`segments[]`；Qwen3-ASR、Whisper Tiny 当前返回空数组，不伪造时间戳。
SenseVoice 额外返回 `lang` / `emotion` / `event` 副语言标签；ASR 转写结果不含
说话人字段，归属判定请用声纹接口。TTS voice 请先调用
`/v1/audio/voices?model=<模型 key>` 并使用返回 ID。

超过 30 秒的音频会自动做 VAD 分段解码（`VVOICE_VAD_SPLIT_SECONDS` 可调，0 禁用），避免长音频识别劣化；`verbose_json` 附带 `segments_decoded`。

完整实时 schema：`http://<VOS-IP>:22700/docs` 或 `/openapi.json`；V-Router
接入契约见仓库 docs/v-router-discovery.md。
