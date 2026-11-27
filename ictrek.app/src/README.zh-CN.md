# V-Voice

打开「模型管理 → 语音与声纹模型 → 节点部署管理」，在目标节点部署后端，选择已安装模型和「自动」「NFS 只读挂载」或「传输到节点」，然后准备并登记。在语音识别、语音合成或声纹表单的「执行节点」选择主节点或分节点。支持的模型和接口字段见「API 文档」。 「工作台执行节点」用于配音、音乐和音效生成、字幕逐句重做、角色试听、歌词对齐、扒谱、出谱及编曲渲染和试听。先在同一个分节点登记任务所需的全部模型，完成后核对实际执行节点。

在 V-Voice 打开「模型管理 → 语音与声纹模型 → 远端节点」，选择目标节点并部署对应 Profile 的后端。后端运行后点击「准备并登记 SenseVoice」，主实例需已下载该模型。然后从「语音识别 ASR → 远端节点」选择模型和节点并上传音频，结果显示实际执行节点。

工作台采用 ONNX 与 audio.cpp GGUF 后端，不再安装 PyTorch 运行时。
移除四个仅支持 PyTorch 的音乐模型及独立配乐页面/API；GGUF 音乐生成、语音、
声音克隆和编曲继续保留。已安装模型文件、作品和音频不删除。
各功能页面的「准备模型」按钮可原地下载、暂停或继续准备对应模型，
仍统一通过 V-Scheduler / ModelScope 管理，无需离开当前页面寻找模型。

V-Voice 保留基于 ONNX 的公共 ASR / 流式 ASR / TTS / 声纹服务。模型由 V-Scheduler 内置模型仓库安装并由所有用户共享；其统一网关通过发现接口接入公共能力，无需独立安装 Model Hub 或 V-Router。

## 实时对话

AMD CUDA、Jetson / L4T 与 Thor profile 提供 Haru 中英文全双工实时对话。可选择“轻松聊天”“语言练习”“面试练习”三种固定角色；模型首次使用时由 V-Scheduler 下载并按需加载，同一设备同时只能进行一场对话。默认通话上限 180 秒，挂断后模型按设置热保留，空闲到期自动卸载并释放许可。

首次会话需要麦克风授权。请使用耳机，避免模型听到自己的扬声器输出而形成自问自答。实时对话会按 profile 的 CUDA 架构构建 speech.cpp worker；AMD CPU、ARM CPU 和通用 ARM CUDA 等纯 CPU 或未适配 profile 不显示该入口。

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
