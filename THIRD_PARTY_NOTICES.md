# 第三方组件

## VOS 镜像补充

VOS 版从固定的 audio.cpp v0.9.1 源码构建 CPU/CUDA 独立进程，原始 LICENSE
位于 `/opt/vvoice/audiocpp/LICENSE`。FFmpeg、eSpeak-ng、MeCab 及其动态依赖来自
各 profile 的系统发行版软件包，不是下文桌面安装包中的预编译版本；具体版本、
版权与许可保留在镜像的软件包数据库和 `/usr/share/doc/` 中。

ARM GPU 运行镜像只从原固定 SDK 提取 CUDA、cuDNN 及 ONNX Runtime 所需的独立
Protobuf / Abseil C++ 共享库，不继承 SDK 的 PyTorch 或 Python 包；SDK 中对应
系统软件包的版权及 NVIDIA 容器许可保留在 `/opt/vvoice/notices/cuda/`。

模型不随镜像打包。ModelScope 镜像保留原始文件校验值、来源索引和独立许可；
OmniVoice、YuE2 权重采用 CC-BY-NC-4.0，Breeze TTS 2 采用其研究与非商业协议，
不能从本应用的 Apache-2.0 许可推导模型商用授权。音色库分别保留自己的许可
与作者署名，不统一改标为应用许可。

- Astryx 0.6.1：https://astryx.atmeta.com/ ，保留 npm 包中的许可。
- audio.cpp v0.9.3：https://github.com/0xShug0/audio.cpp ，Apache-2.0，Copyright 2026 ShugoAI LLC。macOS 包内置 Metal 服务，Windows 包内置 CPU 服务及 DLL；原始 LICENSE 随 engine 目录分发；其他运行包从官方发行页下载并保留许可。
- IndexTTS：https://github.com/index-tts/index-tts ，模型不随应用分发。中文模型协议原文保存在 web/public/model-license.txt，下载和使用模型须遵守该协议。
- React、Vite、TypeScript、Lucide、StyleX、WebView2 的许可与版权声明以对应依赖包为准。

- FFmpeg 8.1.2：https://ffmpeg.org/ ，LGPL-2.1-or-later。构建时从校验摘要的官方源码裁剪，只保留音频解码与 WAV 输出，作为独立可执行程序随 App/CLI 分发。许可证与构建参数位于安装包 `tools/FFmpeg-LICENSE.txt`、`tools/build.json`（macOS App 为 `Contents/Resources/tools/`）；对应源码与构建脚本随 Release 的 `yovoice-<版本>-ffmpeg-source.tar.gz` 提供。

- ocho（https://github.com/leemysw/ocho-release ）：Apache-2.0，源码不公开，以二进制形式的独立可执行程序随 yovoice 分发、作为子进程运行；许可随包位于 `tools/ocho/LICENSE.txt`（macOS App 为 `Contents/Resources/tools/ocho/`）。

- VoxCPM2：https://github.com/OpenBMB/VoxCPM ，模型不随应用分发，使用 Apache-2.0 许可：https://github.com/OpenBMB/VoxCPM/blob/main/LICENSE 。

## OmniVoice and Qwen3-TTS

- [OmniVoice](https://huggingface.co/k2-fsa/OmniVoice): code Apache-2.0, pretrained weights CC-BY-NC (non-commercial), as stated by the model author.
- [Qwen3-TTS 12Hz 1.7B Base](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-Base): Apache-2.0.
- Weights are downloaded separately from audio.cpp GGUF repositories and are not included in yovoice installers.

## ACE-Step

- [ACE-Step 1.5](https://huggingface.co/ACE-Step/Ace-Step1.5)：MIT，音乐生成模型。权重从 audio.cpp GGUF 仓库单独下载，不随应用安装包分发。

## Stable Audio 3

- [Stable Audio 3 Small Music](https://huggingface.co/stabilityai/stable-audio-3-small-music)、[Small SFX](https://huggingface.co/stabilityai/stable-audio-3-small-sfx)、[Medium](https://huggingface.co/stabilityai/stable-audio-3-medium)：[Stability AI Community License](https://huggingface.co/stabilityai/stable-audio-3-small-sfx/blob/main/LICENSE.md)，使用者及其关联方年收入低于 100 万美元时可免费使用（含商用），超过需向 Stability AI 申请企业许可；商用须向 Stability AI 登记并标注“Powered by Stability AI”。文本编码器 T5Gemma 另受 Gemma 使用条款约束。权重从 audio.cpp GGUF 仓库单独下载，不随应用安装包分发。Powered by Stability AI.

## 编曲

- [go-meltysynth](https://github.com/sinshu/go-meltysynth)（提交 05d311382fc4）：MIT，Copyright (C) 2021–2022 Nobuaki Tanaka，纯 Go SoundFont 合成器，编译进 yovoice 服务与 CLI，见[原始许可](https://github.com/sinshu/go-meltysynth/blob/main/LICENSE.txt)。
- [MuseScore General](https://ftp.osuosl.org/pub/musescore/soundfont/MuseScore_General/) 0.2：MIT，Copyright (c) S. Christian Collins，General MIDI 音色库。用户在设置或 CLI 中单独下载，不随应用安装包分发。

## Kokoro 与发音资源

- [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) 和 [Kokoro-82M-v1.1-zh](https://huggingface.co/hexgrad/Kokoro-82M-v1.1-zh)：Apache-2.0，模型单独下载或导入，不随应用安装包分发。
- [eSpeak-ng 1.52.0](https://github.com/espeak-ng/espeak-ng/tree/4870adfa25b1a32b4361592f1be8a40337c58d6c)：GPL-3.0-or-later。原生库与数据来自 espeakng-loader 0.2.4 的 PyPI wheel，下载 Kokoro 模型时由应用从 PyPI（或阿里云 PyPI 镜像）获取到用户数据目录，不随应用安装包分发。完整对应源码见[固定版本源码](https://github.com/espeak-ng/espeak-ng/archive/4870adfa25b1a32b4361592f1be8a40337c58d6c.tar.gz)，构建方法见[上游构建脚本](https://github.com/thewh1teagle/espeakng-loader/blob/e5e9200dc3fd894b7415942c2602fc31526d60fc/build.sh)。由独立 audio.cpp 进程加载，Go 服务不链接该库。
- [MeCab](https://taku910.github.io/mecab/)：BSD / LGPL / GPL 多许可；原生库来自 fugashi 1.5.2 的 PyPI wheel，与 eSpeak-ng 一样在下载 Kokoro 模型时获取，不随应用安装包分发。
- VOS 镜像沿用系统 eSpeak-ng / MeCab 及其许可证，不在每个用户目录下载发音库；以上 wheel 下载流程适用于桌面端。
- [Misaki](https://github.com/hexgrad/misaki)：Apache-2.0；[jieba](https://github.com/fxsjy/jieba) 和 [pypinyin](https://github.com/mozillazg/python-pinyin)：MIT。模型中的字词发音映射由这些组件生成，对应许可内嵌在模型资源中。
- [UniDic 3.1.0](https://github.com/polm/unidic-py)：日文词典与许可内嵌在 v1.0 多语言模型包中。模型版本与语言支持见 [Kokoro 说明](docs/models_zh.md#kokoro)。

## MCP

- [MCP Go SDK v1.8.0](https://github.com/modelcontextprotocol/go-sdk/tree/v1.8.0)：官方 Model Context Protocol 实现，Apache-2.0 / MIT，见[原始许可](https://github.com/modelcontextprotocol/go-sdk/blob/v1.8.0/LICENSE)。
- SDK 的 Go 依赖版本锁定在 `go.mod` / `go.sum`，包括 google/jsonschema-go、yosida95/uritemplate、segmentio/encoding 与 asm，以及 golang.org/x 下的 oauth2、sync、sys、time；各组件保留上游许可。
