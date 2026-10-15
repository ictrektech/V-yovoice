---
license: other
tags:
  - audio.cpp
  - gguf
  - text-to-speech
  - music-generation
---

# V-Voice creative models

Verified upstream GGUF models and SoundFonts for the VOS edition of
[V-Voice](https://github.com/ictrektech/V-yovoice), based on yovoice and audio.cpp.
Weights are mirrored without changing their bytes. Original authors, conversion
sources, fixed revisions, file sizes and SHA256 values are recorded in
`source-index.json`; original license texts and provenance are under `licenses/`.

The application retains the full 38-variant creation catalog. Two upstream Kokoro
variants are import-only and are not represented as public downloads here.
The complete downloadable catalog consists of 41 unique files. Staged uploads
are not complete until the anonymous catalog audit passes; use the source index
and application catalog rather than assuming every repository file is one model.
Existing V-Voice ONNX models remain in their original ModelScope repositories.

Install selected model files through Model Hub and share its read-only export
with V-Voice. Do not copy weights into each user's project directory. The app's
model manager checks the catalog's original SHA256 values before using GGUF files.

## Model licenses

The application license does not replace model licenses. Refer to the retained
original terms, model cards and `licenses/source-index.json`:

- IndexTTS: original IndexTTS model agreement.
- VoxCPM2, Qwen3-TTS and Kokoro: original Apache-2.0 terms and notices.
- OmniVoice and YuE2: CC-BY-NC-4.0 weights.
- Breeze TTS 2: BreezeBlue research and non-commercial agreement, with its notices.
- ACE-Step: original MIT terms and attribution, including XL conversion provenance.
- SoundFonts: individual licenses and author credits; they are not relabeled with
  the application's license. SGM-V2.01 is by Shan, mirrored without modification.

## 简体中文

本仓库为 VOS 版 V-Voice 保存上游 GGUF 模型和音色库，文件内容不作修改。
来源、固定版本、大小及 SHA256 见 `source-index.json`，原始许可与署名见
`licenses/`。应用保留全部 38 个创作模型变体，其中两项 Kokoro 依照上游要求
仅支持合法文件导入，不虚构公开下载地址。其余可下载目录共 41 个独立文件，
分批上传后须通过匿名完整性审计才算完成；原有 ONNX 模型仍使用原来的
ModelScope 仓库。

请通过 Model Hub 按模型安装所需文件，并将共享导出目录以只读方式提供给
V-Voice，不要为每个用户重复复制权重。模型与应用的许可分别适用；尤其注意
OmniVoice、YuE2 的非商业许可、Breeze 的研究与非商业协议及 IndexTTS 的原始
模型协议。音色库亦分别保留原始许可与作者署名，完整条款以原文为准。
