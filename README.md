## V-Voice for VOS

VOS uses sherpa-onnx / ONNX Runtime for speech and audio.cpp for GGUF speech,
voice cloning and music, plus native soundfont score rendering. Runtime images do
not install PyTorch, Transformers or Diffusers. CUDA libraries are copied into a
clean runtime stage rather than inheriting the full GPU development image.

The PyTorch-only ACE-Step 1.5 Turbo (original weights), Stable Audio 3 Small-Music,
Stable Audio 3 Medium and MusicGen Small have been removed, along with their
separate Background music page and `/v1/audio/music/generations` /
`/api/v1/music-models` endpoints (now 404). The audio.cpp GGUF versions of ACE-Step
and YuE2 remain in **Music generation**; score arranging and every existing speech
API remain available. No installed weights, shared directories, projects or audio
are deleted. Rollback can reuse those files with the preceding release.

Each feature page has a **Prepare models** button. It opens only the relevant
speech, creator or soundfont models in a dialog on the current page, with download,
pause, resume and verification states using V-Scheduler / ModelScope. Closing it
returns to the same page and leaves downloads running. Model administrators are
still required for shared downloads. The full model manager remains available.
The optional `export-seaco` development extra uses Torch only for offline model
export and is never installed in service images; SeACo inference remains ONNX-only.

`VVOICE_CPU_MODELS` applies consistently to ASR, TTS and speaker models. Explicit
unload and LRU eviction collect unreachable objects and attempt to return free
CPU heap pages; this is best effort, not proof that GPU/native execution stopped.
The isolated `scripts/calibrate-cpu-voice-worker.py` requires an outer Scheduler
permit and records three rounds of unchanged 512-character TTS / 20-second ASR,
RSS and host available memory; never run it by disabling production admission.

Model management expands in the VOS sidebar into speech models and creator models/soundfonts;
there is no second, easily missed category tab bar. VOS settings scroll independently.
The settings model-management action stays inside the workbench; the standalone
compatibility console also provides an explicit return-to-workbench link.
Embedded service forms inherit the workbench theme. API documentation includes the private
music/score RPC contract, job polling/cancellation and authenticated result download;
these are explicitly distinguished from the public OpenAI-compatible speech endpoints.
Import-only variants do not offer a remote download in either manager; stopping a
download only cancels active tasks whose file selection overlaps the chosen model.
The VOS sidebar provides dedicated Model management, ASR, original TTS, Speaker recognition,
and Hotword management pages inside the workbench. They retain the original
model cards, download/unload controls, transcription, speaker enrollment,
identification and verification forms and existing API paths; the creative
editor stays mounted when opening them. VOS userinfo uses integer `enable: 1`;
disabled or malformed identities are rejected rather than treated as signed in.
LAN HTTP uses secure random UUIDs and S256 PKCE without requiring WebCrypto.
Automatic scheduling uses a VOS-authenticated, versioned server-to-server binding;
credentials stay in this app's private storage and reload without restarting.
New node approvals declare input-limit protocol v1 and enforce their measured text,
speed, encoded-audio size, source sample rate and duration before native model loading.
Audio decoding is bounded; oversized direct and gateway requests do not acquire a compute permit.
See [the Scheduler-side handoff and actual-node acceptance gates](docs/scheduler-auto-binding.md).

This fork is the successor to `com.ictrek.v-voice`. It preserves the existing
V-Voice model catalog and APIs and adds the yovoice creation workbench/audio.cpp
models. Model support is additive, not a replacement by a curated subset.
All upstream downloadable model variants remain in the creation catalog;
upstream import-only entries retain their source requirements. Models are shared
through V-Scheduler's built-in model repository from ModelScope, not downloaded separately per user.
The VOS workbench and its dedicated API documentation page support English,
Simplified Chinese and Traditional Chinese, following VOS or an app-local override.

See [integration, public APIs, scheduling and rollback](docs/vos-integration.md)
and [retained speech-service documentation](docs/v-voice-legacy.md).
The VOS package requires the unified V-Scheduler app, which includes the gateway
and model repository; separate V-Router and Model Hub installations are unnecessary.
The sections below describe the original upstream desktop app; they do not imply
that VOS images or releases have passed their release gates. Fork source and
merge baseline are recorded in [UPSTREM](UPSTREM).

VOS packaging verifies current published dependency versions. Private GitHub
repositories are checked through the existing approved App Store SSH tunnel,
including the published archive, without copying a broad GitHub token into CI.
The manual Actions trigger checks dependency access only; it does not package,
publish or install an application. See [the VOS release guide](ictrek.app/README.md).

<p align="center">
  <img src="web/public/v-voice.png" width="96" alt="V-Voice" />
</p>

<h1 align="center">V-Voice</h1>
<p align="center">Give your words a voice. Compose your ideas into songs.</p>
<p align="center">
  <a href="https://yovoice.leemysw.com"><img src="https://img.shields.io/badge/website-yovoice.leemysw.com-10b981?style=flat-square" alt="Website" /></a>
  <a href="web/package.json"><img src="https://img.shields.io/badge/version-0.2.0-blue?style=flat-square" alt="Version 0.2.0" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-orange?style=flat-square" alt="License: Apache-2.0" /></a>
  <img src="https://img.shields.io/badge/macOS-14%2B-black?style=flat-square" alt="macOS 14+ (Apple Silicon)" />
  <img src="https://img.shields.io/badge/Windows-10%2F11-0078D4?style=flat-square" alt="Windows 10/11 (x64)" />
</p>
<p align="center">English · <a href="README_zh.md">简体中文</a></p>

<p align="center"><a href="https://yovoice.leemysw.com">Website</a> · <a href="docs/cli.md">CLI & Agent Skill</a> · <a href="docs/api.md">API / MCP Deployment</a> · <a href="docs/development.md">Development</a></p>

---

yovoice is an open-source, local-first audio and music creation studio for macOS and Windows. 

Turn text into expressive speech, natural cloned voices, complete vocal songs, and multi-track scores right on your machine. Featuring zero-shot voice cloning, emotional performance controls, AI music generation with lyrics, and General MIDI score arranging—**all running 100% locally with zero cloud API calls, zero per-character fees, and zero Python environment headaches.**

![yovoice creation workspace — browser preview](docs/images/yovoice-workspace.png)

---

## Why yovoice?

- 🔒 **100% Local Privacy**: Runs entirely on your local GPU/CPU. Your manuscripts, reference voices, and creations never leave your computer.
- 💸 **Zero Recurring Fees**: Say goodbye to per-character/per-minute meters and expensive cloud voice/music subscriptions.
- ⚡ **Native C++ Performance (No Python Hell)**: Powered by [audio.cpp](https://github.com/0xShug0/audio.cpp) v0.9.1. Ships with bundled Windows CUDA 12.4/13.3 runtimes and native macOS Metal support. Double-click and create—no Conda or PyTorch conflicts.
- 🎛️ **Creator Workstation**: Multi-take versioning for side-by-side comparison, waveform trimming, timeline scrolling, and clean stems/MIDI export.
- 🤖 **MCP & AI Agent Ecosystem**: Connect DeepSeek, Qwen, Claude, OpenAI, or local Ollama to write scores and lyrics in seconds. Includes a native Model Context Protocol (MCP) server for Cursor and Claude Code.

---

## Features

- **Voice and expression** — use a reference voice, match a reference performance, adjust emotions, or describe the delivery in words.
- **A complete audio workflow** — import or record reference audio, trim clips, preview speech, and export your work.
- **Voice design and cloning** — VoxCPM2 offers text-guided voice design, controllable cloning, and transcript-assisted cloning with automatic multilingual handling, and 48 kHz output.
- **Music generation** — describe a style, write lyrics with section markers, and generate full songs or instrumentals with ACE-Step 1.5; every take is kept as a version to compare.
- **Score** — write each part by bar and beat, import MIDI or let an Agent write the score, then render it with a General MIDI sound font and a role-based mix; results are exactly repeatable and export to MIDI and stems. See [Score](docs/score.md).
- **Optional AI service** — connect DeepSeek, Qwen, Kimi, OpenAI, Anthropic, Ollama or any compatible API to let AI write arrangements and lyrics; keys stay on this computer. See [AI service](docs/ai.md).
- **Local models** — run IndexTTS 2.0 / 2.5, VoxCPM2, OmniVoice, Qwen3-TTS, Breeze TTS 2 and Kokoro through audio.cpp, with resumable model downloads and GGUF import.
- **Hardware acceleration** — Metal on Apple Silicon; CPU, NVIDIA CUDA, and experimental Vulkan on Windows.
- **Agent Skill & MCP** — ask your AI agent to set up local speech generation and create voiceovers from text and reference audio.

---

## Hardware & VRAM Quick Guide

| Use Case | Recommended Hardware | Recommended Models |
| --- | --- | --- |
| 🟢 **Lightweight & Blazing Fast** | Any CPU / 4 GB+ RAM | **Kokoro-82M** (only 189 MB Q8, millisecond latency, runs great on CPU) |
| 🟡 **High-Fidelity Voice Cloning** | 4 GB – 6 GB VRAM / 8 GB+ Apple Silicon | **VoxCPM2** (2B, 48 kHz), **IndexTTS 2.0/2.5**, **Qwen3-TTS** |
| 🔴 **Full Song & Music Generation** | 12 GB+ VRAM / 16 GB+ Apple Silicon | **ACE-Step 1.5 Turbo** (BF16, 10 GB), **YuE2 3B** |

---

## Supported Models

| Model | Parameters | Model file size by precision | Core capabilities |
| --- | --- | --- | --- |
| IndexTTS 2.0 | — | Q8 · 3.63 GB<br>F16 · 4.65 GB<br>ORIG · 8.08 GB | Chinese/English voice cloning, emotion control, reference performance |
| IndexTTS 2.5 | — | Q8 · 3.50 GB<br>F16 · 4.55 GB<br>ORIG · 7.89 GB | Multilingual voice cloning, emotion control, pronunciation editing |
| VoxCPM2 | 2B | Q8 · 2.96 GB<br>BF16 · 4.77 GB<br>ORIG · 4.96 GB | Text-guided voice design, voice cloning, transcript-assisted cloning |
| OmniVoice | 0.6B | Q8 · 1.35 GB<br>BF16 · 1.64 GB<br>F16 · 1.64 GB | Attribute-based voice design, voice cloning, non-verbal sound tags |
| Qwen3-TTS Base | 0.6B | Q8 · 1.99 GB<br>BF16 · 2.52 GB | Reference voice cloning, optional transcript guidance, multilingual speech |
| Qwen3-TTS Base | 1.7B | Q8 · 2.70 GB<br>BF16 · 4.20 GB<br>ORIG · 4.54 GB | Reference voice cloning, optional transcript guidance, multilingual speech |
| Qwen3-TTS CustomVoice | 1.7B | Q8 · 2.82 GB<br>BF16 · 4.18 GB | 9 built-in voices, text-guided style and emotion |
| Qwen3-TTS VoiceDesign | 1.7B | Q8 · 2.82 GB<br>BF16 · 4.18 GB | Voice design from natural-language descriptions, no reference audio required |
| Breeze TTS 2 | ~3B | Q4 · 3.79 GB<br>Q8 · 5.08 GB<br>BF16 · 7.34 GB | Chinese and English voice design, cloning and voice direction; GPU recommended, requires the v0.9.1 engine |
| Kokoro-82M 1.0 Official | 82M | Q8 · 189.55 MB<br>BF16 · 211.95 MB | 49 built-in voices, multilingual speech excluding Japanese |
| Kokoro-82M 1.0 | 82M | Q8 · 932.66 MB | 54 built-in voices, full multilingual resources including Japanese; import only |
| Kokoro-82M 1.1-zh | 82M | Q8 · 255.32 MB | 100 Chinese and 3 English voices; experimental, import only |
| ACE-Step 1.5 Turbo | — | BF16 · 10.09 GB | Songs and instrumentals from a style prompt and lyrics, 50+ vocal languages; requires engine v0.9.1 |

All models are available in the App and CLI. See [model selection](docs/models.md) for input requirements and examples. OmniVoice (CC-BY-NC) and Breeze TTS 2 (BreezeBlue Research and Non-Commercial License) weights are restricted to non-commercial use.

---

## Installation

Choose the package for your platform from the repository’s [Releases](../../releases) tab or visit the [official website](https://yovoice.leemysw.com).

| Platform | Package | Install |
| --- | --- | --- |
| macOS 14+ · Apple Silicon | `.dmg` | Open the disk image and drag yovoice to Applications |
| Windows 10/11 · x64 | `-setup.exe` | Run the installer, then open yovoice from the Start menu |
| Windows 10/11 · x64 · NVIDIA GPU | `-cuda12.4-setup.exe` | Bundles the CUDA 12.4 runtime; works with older GPUs and drivers and uses the GPU from first launch |
| Windows 10/11 · x64 · NVIDIA GPU | `-cuda13.3-setup.exe` | Bundles the CUDA 13.3 runtime; needs a newer driver, smaller download |

The Windows installer downloads and installs [WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/) if needed. Models are downloaded inside the app; uninstalling preserves user data in `~/.yovoice`.

Check for updates from the app menu on macOS or Windows. Updates are also checked and downloaded in the background; restart to install when ready. Windows updates download only the app (`-update.exe`) and keep the installed runtime; when a release recommends a newer runtime you can upgrade it in Settings → Inference engine.

![Install yovoice on macOS](docs/images/yovoice-macos-install.png)

---

## Quick Start

1. **Set up a model.** Download a model in Settings (e.g. Kokoro-82M for fast narration, or VoxCPM2 for cloning).
2. **Create a project.** Choose Story dubbing, Speech generation, Music, or Score.
3. **Add content.** Enter text, lyrics, or notes, then pick a character and adjust style.
4. **Generate audio.** Select Generate, then preview, compare takes, edit, and export.

---

## CLI & Agent Skill

Give your agent the [yovoice Skill](https://github.com/leemysw/yovoice/tree/main/skills/yovoice) link and ask it to install the Skill and set up the local CLI, engine, and model:

> Install this Skill and set up yovoice for local speech generation: https://github.com/leemysw/yovoice/tree/main/skills/yovoice

Then describe what you want:

> Read narration.txt using voice.wav as the reference voice, with a calm delivery, and save it as narration.wav.

The agent runs the standalone CLI without opening the desktop app. See the [CLI guide](docs/cli.md) for details.

---

Run `yovoice serve` to provide an authenticated HTTP API and MCP inference service for other machines. See the [API / MCP deployment guide](docs/api.md) for deployment and client examples.

## Development

```sh
make install
make app-run
```

See the [development guide](docs/development.md) for prerequisites. It also covers browser preview, tests, and project structure.

---

## Contributing

Bug reports, feature suggestions, and pull requests are welcome. Include your platform, model, and steps to reproduce when reporting a problem. Run `make check` before submitting code changes.

---

## Acknowledgements

- [audio.cpp](https://github.com/0xShug0/audio.cpp) by ShugoAI — the local audio inference engine.
- [VoxCPM](https://github.com/OpenBMB/VoxCPM) — voice design and cloning models, licensed under Apache-2.0.
- [IndexTTS](https://github.com/index-tts/index-tts) — the speech synthesis models behind yovoice.
- [OmniVoice](https://github.com/k2-fsa/OmniVoice) — voice design and cloning models.
- [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS) — voice cloning, built-in voices, and text-guided voice design.
- [ACE-Step](https://github.com/ace-step/ACE-Step-1.5) — music generation from style prompts and lyrics.
- [go-meltysynth](https://github.com/sinshu/go-meltysynth), [MuseScore General](https://musescore.org/en/handbook/3/soundfonts-and-sfz-files#gm_soundfonts), [GeneralUser GS](https://www.schristiancollins.com/generaluser) and SGM-V2.01 by David Shan — the SoundFont synthesizer and sound fonts behind score rendering.
- Kokoro — lightweight speech synthesis with built-in voices: [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) and [Kokoro-82M-v1.1-zh](https://huggingface.co/hexgrad/Kokoro-82M-v1.1-zh).

---

## Star History

<a href="https://www.star-history.com/?repos=leemysw%2Fyovoice&type=date&legend=bottom-right">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=leemysw/yovoice&type=date&theme=dark&legend=bottom-right" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=leemysw/yovoice&type=date&legend=bottom-right" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=leemysw/yovoice&type=date&legend=bottom-right" />
 </picture>
</a>

---

## License

[Apache-2.0](LICENSE). Dependencies retain their [original licenses](THIRD_PARTY_NOTICES.md); IndexTTS models are covered separately by their [model license](web/public/model-license.txt).
# V-Scheduler 接入

新旧审批共存时，服务发现声明 `mixed_input_limits_version: 1`；调度绑定必须同时携带同版本及明确的 `legacy_unbounded_models`。旧模型名单与 `model_limits` 不得重叠，两者必须恰好覆盖已批准的 `models`。四个原生配乐模型始终要求独立的有界输入校准，不能进入旧模型名单。无效绑定被拒绝并保留上一份审批；输入校验和许可获取期间绑定变化时要求重试，避免跨版本使用预算。旧创作模型的目录别名仅用于输入校验，不授予额外同步执行器或改变原有异步任务类型。

VOS 安装依赖统一应用 `com.ictrek.v-scheduler`，打包时从已发布的 GitHub Release 或应用商店解析依赖版本，查询失败则停止打包。模型管理默认地址为 `http://v-scheduler-model-hub:6005`；保留 `MODEL_HUB_API_URL` 配置键供现有安装升级使用，已有安装需将该参数切换到新地址。

V-Scheduler 已内置模型仓库，无需独立安装 Model Hub。共享模型目录继续使用兼容配置键 `MODEL_HUB_SHARED_MODELS_PATH`（默认 `/data/vos_workspace/model_hub`），保留现有模型、导出路径和下载记录；这些历史命名不代表仍依赖旧应用。统一模型网关为 `http://v-scheduler-gateway:8080/v1`；资源调度接口为 `http://v-scheduler:38120/api/v1`。接入及资源授权契约见 [V-Scheduler 接入指南](https://github.com/ictrektech/V-Scheduler/blob/main/docs/application-integration.md)。模型目录可见不代表本地推理已获调度授权。

## 应用生命周期与资源停止

VOS 安装后，应用通过 Scheduler 的可信绑定获得 `lifecycle_protocol_version=1`，自动登记已批准的执行器并定时上报应用心跳；节点遥测仍由 V-Scheduler 的内置组件采集，不需要用户安装 Agent。正式入口为 `http://v-scheduler:38120/api/v1`，兼容别名继续可用。模型目录、原有安装参数和模型下载方式不变。

在 V-Scheduler「节点管理 → 应用统一接入」可查看实际节点、批准预算和运行中的执行。同步计算使用「停止并卸载」，异步任务使用「取消」；停止请求本身不释放预算。应用确认原生调用/子进程退出并卸载权重后才提交原执行的停止证明。未知执行或确认失败继续保留预约，避免把仍在运行的计算当成空闲；确认回执保存在应用私有目录，可在重启后重试。阻塞式原生调用须等待其实际返回，不能承诺立即中断。

完整流程、身份和接口见 [V-Scheduler 统一接入指南](https://github.com/ictrektech/V-Scheduler/blob/main/docs/application-integration.md#unified-lifecycle)。

发布纯应用层改动时，可在对应架构构建机上使用 `VVOICE_STUDIO_BASE_IMAGE=<已核验的同 profile 发布镜像> bash docker/build_studio_image.sh --sheet <sheet> --application-only`，复用已校准的原生环境，仅更新当前 `vvoice/`、预先编译的 Go 程序和网页资产。随后用原脚本 `--publish-only` 推送并记录飞书。改变原生依赖、内核或目录契约时仍须完整构建。


### Task priority and cooperative preemption

Inference requests optionally accept `X-VScheduler-Priority: background|interactive|high`,
`X-VScheduler-Preemptible: true|false`, `X-VScheduler-Allow-Preemption: true|false`, and
`X-VScheduler-Force-Admission: true|false`. The default is background priority with all
three flags off. Preemption requires consent from both requests. Resources remain
reserved until native exit and model unload are confirmed. Synchronous requests are
never automatically replayed. Force admission requires a current administrator Bearer
identity verified by V-Scheduler; hard budgets, stop barriers and at least 1 GiB RAM
headroom remain enforced. Operator credentials are never persisted in tasks.
See the [unified integration guide](https://github.com/ictrektech/V-Scheduler/blob/main/docs/application-integration.md).

VOS 界面默认跟随平台语言，兼容旧版平台语言存储和新版语言广播；显式选择的语言仍优先。尚无就绪语音模型时，页面提示先下载模型，模型就绪后自动重试 V-Scheduler 接入，不要求用户部署 Agent。

自动接入同时兼容新版 VOS 身份接口和旧版 VOS 的 `user/check` 应用身份核验；只接受 V-Scheduler 的精确已启用服务身份，普通用户及其他应用不能交接授权。用户无需手工配置服务令牌，既有共享目录和兼容地址继续保留。

组合语音调用由 V-Scheduler 校准主任务的总预算；次模型可以使用不同执行器，但全部模型映射均须通过同一应用的执行器审批。
