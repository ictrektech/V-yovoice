# V-Voice

V-Voice 是部署在 VOS 宿主机上的公共 ASR / TTS 共享语音服务，模型通过
[`sherpa-onnx`](https://github.com/k2-fsa/sherpa-onnx) 或 SeACo 专用 ONNX Runtime 适配器推理。它对平台内所有应用和
V-Router 提供统一入口：OpenAI 兼容音频 API、经 Model Hub 安装的公共模型目录，以及
机器可读的发现元数据。服务不区分 VOS 用户，所有已就绪模型均作为 public 模型提供。

## 功能

### 界面语言

Web 控制台支持简体中文、繁體中文和 English。右上角语言菜单默认选择
**跟随 VOS**：优先读取 VOS 注入的 `window.vos_platform.getState()` 语言快照，
并监听 `broadcast.on('locale-change', …)` 实时切换；兼容旧版 VOS 使用的
`VIVIBIT-…-preferences-locale` 与 `vben-web-antd-…-preferences-locale` 存储项。
独立打开或无法读取 VOS 语言时，按浏览器语言回退，仍无法匹配则使用简体中文。

手动选择语言会写入 V-Voice 专用的 `v-voice-language` 浏览器存储项，不会修改
VOS 或其他应用的设置；重新选择 **跟随 VOS** 即恢复自动同步。模型名称、用户输入、
API 技术标识和服务返回的原始诊断内容保持原样。
模型卡片的语言列表、热词/流式接口能力，以及音色选项中的语言标签均跟随界面语言。

### OpenAI 兼容推理 API

| 接口 | 说明 |
|---|---|
| `POST /v1/audio/transcriptions` | 语音转写；支持已保存热词集、请求级热词文本、UTF-8 热词文件、模型相关增强分数，以及可选的 `speaker_model` 声纹同次归属 |
| `POST /v1/audio/streaming/transcriptions` | 流式转写（仅 streaming 模型）：chunked 请求体边到边解码，结束返回最终文本 |
| `POST /v1/audio/streaming/ws` | WebSocket 实时识别（仅 streaming 模型）：二进制音频帧增量返回 partial/final |
| `POST /v1/audio/translations` | 语音翻译（输出英文），字段与转写相同；模型能力决定翻译和热词支持 |
| `POST /v1/audio/speech` | 语音合成；`response_format` 支持 `mp3`、`opus`、`aac`、`flac`、`wav`、`pcm`，`speed` 0.25–4.0 |
| `GET /v1/audio/voices` | 列出指定 TTS 模型的可用 voice；TTS 请求的 `voice` 必须来自该接口 |
| `GET /v1/audio/speakers` | 列出已注册声纹（public） |
| `POST /v1/audio/speakers/identify` | 声纹 1:N 说话人归属识别（public） |
| `POST /v1/audio/speakers/verify` | 声纹 1:1 说话人验证（public） |
| `GET /v1/models` | OpenAI 风格的已就绪模型列表 |
| `GET /api/v1/discovery` | 面向 V-Router 的完整模型契约（kind、capabilities、endpoints） |
| `GET/POST/PATCH/DELETE /api/v1/hotwords` | 热词集增删改查（固化热词，保存后自动转化模型格式） |
| `POST/DELETE /api/v1/speakers` | 声纹注册 / 删除（管理面） |

公共推理接口不需要 API Key。请求与响应字段详见 `/openapi.json` 和
[docs/v-router-discovery.md](docs/v-router-discovery.md)。

### 长音频自动分段

offline 模型（SenseVoice、Whisper、Qwen3-ASR、Paraformer、离线 Zipformer）均按
短语音训练，超过约 30 秒的整段音频一次性解码会严重劣化（输出残缺或幻觉）甚至
耗尽内存。V-Voice 在服务端自动处理：时长超过 `VVOICE_VAD_SPLIT_SECONDS`
（默认 30 秒，0 禁用）的音频先用 silero VAD 切出语音段（段间微隙合并、单段上限
20 秒），逐段解码后按时间戳平移合并。`verbose_json` 的 `words[]`/`segments[]`
为全音频真实时间轴，另附 `segments_decoded` 字段。流式模型原生分块解码，不走
该路径。实测 205 秒多人对话：SenseVoice 整段 35 字幻觉 → 分段 968 字完整转写。

### 流式（实时）识别

catalog 中的 streaming 模型（`zipformer-en-streaming`、`zipformer-zh-streaming`）
由 sherpa-onnx `OnlineRecognizer` 驱动，支持音频流式输入与实时识别：

- `POST /v1/audio/streaming/transcriptions?model=...&format=pcm|wav|auto`：
  HTTP chunked 请求体边到边解码，body 结束返回最终转写（verbose_json 同整句接口，
  另附 `streaming: true`）。`pcm` 为 s16le 单声道原始字节，`wav` 为无压缩单声道
  RIFF，`auto` 缓冲后整体解码（非增量，兼容任意容器）。流式 Zipformer 同样支持
  热词（`hotwords` / `hotwords_set` / `hotwords_score`）。
- `POST /v1/audio/streaming/ws?model=...`（WebSocket）：客户端发二进制 PCM 帧，
  服务端增量返回 `{"type":"partial",...}`，`{"type":"finish"}` 后返回
  `{"type":"final",...}`。
- 其余模型为整句识别（OfflineRecognizer），调用流式接口返回 422；对整句模型可
  按客户端 VAD 分段循环调用整句接口近似实时。

### 声纹（说话人）识别

`speaker-campplus-zh-en`（3D-Speaker CAM++，中英双语，28MB）提供声纹能力，
`kind=speaker`：

- 注册（管理面）：`POST /api/v1/speakers`（multipart：`name` + `file` +
  可选 `model`），服务端提取声纹向量存入 `data/speakers.json`，不保留音频。
- 识别 / 验证（public 推理面）：`POST /v1/audio/speakers/identify`（1:N 归属，
  返回 Top-5 余弦相似度排名与阈值判定）、`POST /v1/audio/speakers/verify`
  （1:1，`speaker` 传已注册 id 或名称）；`GET /v1/audio/speakers` 列出声纹库。
  默认阈值 0.6（0–1，越高越严格），建议注册与识别使用同一模型。
- **边转写边声纹（组合模式）**：`POST /v1/audio/transcriptions`、
  `/v1/audio/translations`、`/v1/audio/streaming/transcriptions` 与
  `/v1/audio/streaming/ws` 均接受可选的 `speaker_model`（与可选
  `speaker_threshold`）。提供时，同一段音频在转写的同时提取声纹并与声纹库
  比对，`verbose_json` / 流式最终响应附带 `speaker` 块（`identified`、
  `speaker`、`score`、`threshold`、Top-5 `ranked[]`；音频过短无法提取时块内
  以 `error` 说明，不影响转写结果）。OpenAI 标准无此能力，该参数为可选扩展，
  缺省时请求与 OpenAI 完全兼容。声纹库持久化在应用存储
  `data/speakers.json`，注册一次、永久可比对，无需外部数据库。

```bash
curl 'http://<VOS-IP>:22700/v1/audio/transcriptions' \
  -F file=@sample.wav -F model=sensevoice-int8 \
  -F speaker_model=speaker-campplus-zh-en \
  -F response_format=verbose_json
# verbose_json 同时返回 text/words[] 与 speaker 归属块
```

热词在 SeACo-Paraformer、Qwen3-ASR 模型、`zipformer-en` 和两个流式 Zipformer 上启用。识别请求可用 `hotwords`
传递一次性逗号/换行分隔词组，用 `hotwords_file` 上传 UTF-8 热词文件，也可用
`hotwords_set` 引用已保存热词集（可重复），三者在服务端合并去重，最多 64 个
热词、合计 4096 UTF-8 bytes。Zipformer 系（含流式）还接受范围 `0..10` 的
`hotwords_score`，默认 `1.5`。其他模型忽略热词字段并继续转写。

`seaco-paraformer-zh` 是额外的 SeACo-Paraformer INT8 模型，保留原 `paraformer-zh`。
模型源为 `vivibit/v-voice-seaco-paraformer-zh-int8`，由 Model Hub 安装；官方 checkpoint
在构建机导出为识别主模型与热词编码器两个 ONNX，部署后无需 PyTorch 或 FunASR。
SeACo 使用 CPU ONNX Runtime（包括 GPU profile），复用现有缓存、并发限制和长音频 VAD。
支持请求级热词、热词文件和已保存热词集；每条热词去除空格后最多 10 字符，超限返回 422。
无需 `hotwords_score`。当前只提供整句中文转写，不提供翻译、流式或词时间戳；
`words[]`/`segments[]` 返回空数组，discovery 按实际能力声明。

SeACo 模型包可在构建机用 `pip install '.[export-seaco]'` 安装导出依赖后，通过
`python scripts/publish_models.py seaco-paraformer-zh --prepare-only --work-dir ~/dev/build/v-voice/models`
复现；上游 revision 与 checkpoint SHA-256 固定在 `catalog/sources.json`。
使用已有的 `--publish-prepared` 流程上传，凭据仅从环境读取。

热词集保存在 `VOS_APP_STORAGE_PATH/data/hotwords.json`，通过
`/api/v1/hotwords` 增删改查：`POST /api/v1/hotwords/import` 上传热词表后，
服务端自动解析并在后台生成三种模型格式（`text` 一行一个、`qwen3` 逗号分隔
提示词、`zipformer` contextual biasing 表），可通过
`GET /api/v1/hotwords/{id}/export?format=...` 下载。

`response_format=verbose_json` 时，SenseVoice、Paraformer 和 Zipformer 会把
sherpa token 时间戳标准化为 OpenAI 风格 `words[]`、`segments[]`（秒）；
Qwen3-ASR 与 Whisper Tiny 当前没有底层时间戳，明确返回空数组而不伪造。
SenseVoice 额外返回整句 `lang` / `emotion` / `event` 副语言标签；ASR 转写结果
本身不含说话人字段，说话人归属通过独立的声纹模型接口完成（见上文"声纹识别"），
详见 [docs/model-support.md](docs/model-support.md)。带 `streaming` capability
的模型支持音频流式输入与实时识别；整句模型可按 VAD 分段循环调用近似实时。
客户端可重复提交 `timestamp_granularities[]=word|segment`，并应先读取
discovery 的 `word_timestamps` capability。TTS 客户端必须按模型调用
`GET /v1/audio/voices?model=...`，用返回的 `voices[].id` 构造联动下拉框。

### 模型管理

- 模型以 curated catalog 形式发布到 ModelScope，通过 Model Hub 安装到共享模型目录；
  管理面为 `/api/v1/models` 及其 `pull` / `stop` / `unload` 子接口，需要
  `com.ictrek.v-voice:model:manage` 权限。
- 只有下载完成、可用于推理的模型才会出现在 `/v1/models` 和 discovery 中。
- 模型在首次推理请求时懒加载，保留在进程内 LRU 缓存中；可在模型页显式卸载（不删除文件）。
- 自定义模型包需包含通过校验的 `vvoice-model.json` 描述文件，并使用 pinned 版本
  sherpa-onnx 可加载的文件布局，见 [docs/model-support.md](docs/model-support.md)。

### Web 控制台

前端控制台挂在 VOS 应用前缀 `/app/com.ictrek.v-voice/` 下，提供模型列表
（ASR / TTS / 声纹分类，流式模型带「流式」标记）、ASR / TTS playground
（仅允许调用已就绪模型，TTS voice 从所选模型的声库中选择，合成结果可直接
下载）、热词管理页（热词集增删改查、热词表上传、模型格式导出）、声纹页
（声纹注册、1:N 归属识别、1:1 验证、声纹库管理）。页头「关于」按钮展示应用
版本、运行 profile、推理 provider 等信息；版本号由 VOS 安装包通过
`APP_VERSION` 环境变量注入（`runtime-config.js`），与 `GET /api/v1/about` 一致。

### 并发与资源控制

以下参数均可在 VOS 安装配置中调整：

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `VVOICE_NUM_THREADS` | 4 | sherpa-onnx 每个模型使用的 CPU 线程数 |
| `VVOICE_MAX_LOADED_MODELS` | 2 | 常驻推理模型实例（LRU 缓存）上限 |
| `VVOICE_MAX_CONCURRENT_INFERENCE` | 2 | 所有模型合计同时执行的推理请求数 |
| `VVOICE_MAX_CONCURRENT_PER_MODEL` | 2 | 同一模型实例同时执行的请求数 |
| `VVOICE_VAD_SPLIT_SECONDS` | 30 | 超过该时长的整句音频自动做 VAD 分段解码；0 禁用 |

超出的请求排队等待。GPU profile 强制 `VVOICE_PROVIDER=cuda`，CPU profile 强制 `cpu`。

## 支持的模型

公共 catalog 共 16 个模型，均以 `vivibit/v-voice-*` 仓库公开发布在 ModelScope：

### ASR（8 个）

| 模型 key | 名称 | 语言 | 热词 | 词时间戳 | 说明 |
|---|---|---|---|---|---|
| `sensevoice-int8` | SenseVoice Small INT8 | zh / yue / en / ja / ko 自动检测 | 不支持 | 支持 | 首选模型；带标点恢复和 ITN，附加 `emotion` / `event` 字段 |
| `whisper-tiny` | Whisper Tiny INT8 | 多语言 | 不支持 | 不支持 | 支持 transcribe 与翻译任务 |
| `qwen3-asr-0.6b` | Qwen3-ASR 0.6B INT8 | 12 种语言 | 文本、文件、热词集 | 不支持 | 请求级提示词热词，无增强分数 |
| `qwen3-asr-1.7b` | Qwen3-ASR 1.7B INT8 | 12 种语言 | 文本、文件、热词集 | 不支持 | 更高精度的 1.7B int8 导出，同样原生 sherpa-onnx 加载 |
| `paraformer-zh` | Paraformer Chinese INT8 | zh | 不支持 | 支持 | 中文快速识别 |
| `seaco-paraformer-zh` | SeACo-Paraformer Chinese INT8 | zh | 文本、文件、热词集 | 不支持 | CPU 双 ONNX 神经热词识别 |
| `zipformer-en` | Zipformer English INT8 | en | 文本、文件、热词集、分数 | 支持 | BPE contextual biasing + modified beam search |
| `zipformer-en-streaming` | Zipformer English Streaming INT8 | en | 文本、热词集、分数 | 支持 | 流式实时识别（OnlineRecognizer + 端点检测） |
| `zipformer-zh-streaming` | Zipformer Chinese Streaming INT8 | zh | 文本、热词集、分数 | 支持 | 中文流式实时识别（multi-zh-hans int8） |

### 声纹（1 个）

| 模型 key | 名称 | 语言 | 说明 |
|---|---|---|---|
| `speaker-campplus-zh-en` | 3D-Speaker CAM++ zh-en | zh / en | 声纹注册 / 1:N 归属识别 / 1:1 验证，余弦相似度默认阈值 0.6 |

### TTS（7 个）

| 模型 key | 名称 | 语言 | 说明 |
|---|---|---|---|
| `kokoro-multilang` | Kokoro 82M Multilingual | en / zh | 首选模型；54 个命名 voice |
| `vits-zh` | VITS Chinese | zh | 轻量中文合成 |
| `matcha-zh` | Matcha Chinese Baker | zh | Matcha 声学模型 + Vocos vocoder |
| `zipvoice-zh-en` | ZipVoice Chinese-English INT8 | zh / en | 零样本克隆，内置参考音频 |
| `kitten-nano-en` | KittenTTS Nano English | en | 小型多说话人模型 |
| `pocket-en` | PocketTTS English INT8 | en | 内置参考音频 |
| `supertonic-3` | Supertonic 3 INT8 | 31 种语言 | 10 个说话人 |

Kokoro 使用 sherpa-onnx 的 ONNX 导出与音素化运行时；Kokoro-FastAPI 仅作为 API 设计
参考，`hexgrad/kokoro` 仅用于校验模型参数，两者都不是推理后端。

## 端口与访问入口

- 容器内监听 **7070**（`VVOICE_PORT`），VOS 包将其映射到宿主机 **22700**。
- Web 控制台与全部管理/推理请求统一走 VOS 前缀 `/app/com.ictrek.v-voice/`（Traefik strip）。

| 调用位置 | 服务根地址 | API base URL |
|---|---|---|
| 同一 `vos_default` Docker 网络 | `http://v-voice-backend:7070` | `…/v1` |
| VOS 宿主机进程 | `http://127.0.0.1:22700` | `…/v1` |
| 同宿主机的其他容器 | `http://host.docker.internal:22700` | `…/v1` |

其他固定路径：`GET /health`（进程健康、版本、ONNX Runtime provider）、
`GET /ready`（服务与 Model Hub 共享目录可用性）、`GET /openapi.json`、`GET /docs`。

## 运行 profile

VOS 包提供六个互斥 profile，见 `ictrek.app/src/manifest.yml`：

| Profile | 运行时 |
|---|---|
| `amd` | AMD64 CPU |
| `amd-cuda` | AMD64 NVIDIA CUDA |
| `arm` | ARM64 CPU |
| `arm-cuda` | 通用 ARM64 NVIDIA CUDA |
| `l4t` | Jetson / L4T CUDA |
| `thor` | Thor / Spark CUDA |

镜像构建与飞书 sheet 映射见 [ictrek.app/README.md](ictrek.app/README.md)。

## 部署依赖

- 必需：Model Hub（`com.ictrek.model-hub` >= 0.0.54）。共享模型目录通过
  `MODEL_HUB_SHARED_MODELS_PATH`（path hint `com.ictrek.model.storage`）挂载到容器
  `/modelhub`，所有 V-Voice 用户共享已安装模型。
- 可选：V-Router（`com.ictrek.v-router` >= 0.0.22）通过 discovery 聚合本服务的
  ASR / TTS 模型，接入要求见 [docs/v-router-discovery.md](docs/v-router-discovery.md)。
- 持久化数据写入 `VOS_APP_STORAGE_PATH/data`。

## 开发

```bash
python -m pip install -e '.[test]'
python -m pytest -q
cd frontend && npm install && npm run build
```

更多文档：[V-Router 接入契约](docs/v-router-discovery.md)、
[模型支持](docs/model-support.md)、[模型发布](docs/model-publication.md)、
[ASR 评测报告](docs/asr-benchmark.md)、
[V-Router 性能报告](docs/voice-router-benchmark.md)。
