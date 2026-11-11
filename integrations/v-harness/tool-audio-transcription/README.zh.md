---
description: "可直接安装的 V-yovoice 音频转写工具、配置页与原文卡片。"
kind: "package-bundle"
---

# V-yovoice 音频转写

[English](README.md) | 中文

## 概述

在 Web 或 Desktop 普通会话中粘贴 MP3，询问“这段音频内容是什么？”。智能体按需调用 V-yovoice。助手最终回答之后的持久化音频卡片提供播放、拖动进度和完整原文，原文与智能体总结分开展示。支持多个文件、后续提问、重新识别及恢复会话，无需本地识别模型或插件市场。

## 安装与配置

预构建安装包为 `ictrek-dsh-tool-audio-transcription-0.1.2.tgz`，适配 v-harness **0.2.2-rc.1.vos.03** 和 DSH **0.2.2-rc.1**；旧版 DSH 0.2.1-rc.2 / 0.2.1-rc.5 请继续使用插件 0.1.1。打开**插件 → 添加插件**，填写宿主可访问的安装包 URL 或绝对路径。这里不是文件上传器：Mac 本地路径不能表示远程 VOS 上的文件。VOS 使用前将包复制到目标租户工作区，并使用租户内部路径，例如 `/home/admin/workspace/audio-plugin-acceptance/plugin.tgz`；容器共享的 `/tmp` 在租户内不可见。也可填写固定 Release 地址 `https://github.com/ictrektech/V-yovoice/releases/download/harness-plugin-latest/audio-transcription.tgz`。安装进目标租户的 profile，不修改共享运行时。

npm 包发布后，插件市场可从可访问的 npm 源安装 `@ictrek/dsh-tool-audio-transcription`。

在宿主上以 profile 所有者执行 CLI 示例：

```sh
dsh plugin --profile web add /absolute/host/path/ictrek-dsh-tool-audio-transcription-0.1.2.tgz
```

启用组合包后打开配置页，保存 V-yovoice **服务根地址**（不含 `/v1`），点击**检查连接 / 获取模型**，选择已就绪的 ASR 模型并再次保存。地址必须能从宿主所在容器访问。Desktop 应通过其插件页安装进受管 Desktop profile，不能用无关的 `web` profile 代替。按宿主提示刷新或重启。尚未配置的插件可以正常加载，调用转写时会明确提示配置要求。

设置保存在当前 profile。目标服务必须提供 `/api/v1/models`、`/api/v1/models/{key}/input-limits` 和 `/v1/audio/transcriptions`。这里接入 VOS 的 V-yovoice ASR 服务，不是桌面/CLI 的语音合成 API。模型查询经过 DSH 已认证的 Remote 连接，由宿主访问语音服务。VOS 租户的网络策略必须允许访问该地址；租户外可达的服务在租户内仍可能被阻止。插件不修改网关设置或网络隔离；安装包不包含凭据。

输入限制声明 `/v1/audio/transcriptions/full` 时，宿主向该接口发送原始文件，只接受完整且与请求匹配的结果；转换和分段由 V-yovoice 负责。旧版服务继续使用单段接口及其模型限制；插件不会静默转码。

## 使用

附加一个或多个音频后要求转写、总结或针对内容提问。多个文件逐个选择转写。轮次卡片位于助手最终回答之后，每个上传文件都有播放器；由用户主动开始播放。中央播放键、当前位置、剩余时间和波形进度条跟随宿主亮色或暗色主题；波形支持点击、拖动、悬停时间和键盘定位。不超过 20 MiB 且 10 分钟的音频在浏览器本地解码为真实峰值；更大文件、解码失败或受限宿主改为高对比度进度条。峰值只缓存在当前浏览器会话内存中，不写入会话日志。短原文直接展示，长原文从预览展开，复制操作保留完整文本；无语音时明确提示。浏览器或附件后端无法流式读取时，已保存原文仍保留并显示具体原因。没有最终回答时，卡片继续显示在停止的轮次之后。桌面文件路径必须由用户在当前会话中明确提供，并通过当前执行文件系统读取。

工具包括 `list_audio_files`、`list_audio_models`、`transcribe_audio`、`read_audio_transcript`。上传音频时，智能体先列出准确附件身份，再开始识别，以便轮次卡片在转写进行中就能显示播放器。转写可指定 `attachment_id` 或 `file_path`，不能同时指定。用户明确要求重新识别时传 `reprocess: true`。旧版单段服务在同会话中复用匹配结果；全文件服务在识别前无法提供当前模型版本，因此会重新识别，先前原文仍可通过 `read_audio_transcript` 读取。重新识别失败不会覆盖原有成功结果；卡片保留并标记上一次成功原文。音频和原文随会话保存，沿用现有附件保留策略。

播放使用插件自有的受认证接口。接口校验附件确实属于指定且已加载的会话，以有界字节范围流式返回，并拒绝任意宿主路径。附件按宿主保留策略清理后，播放源随附件不可用。

## 配置

| 字段 | 初始值 | 含义 |
|---|---|---|
| `baseUrl` | 空 | 宿主可访问的服务根地址，不能带凭据、查询或片段。 |
| `model` | 空 | 明确选择的 ASR 模型，不自动切换。 |
| `requestTimeoutMs` | 1860000 | 获取与识别时限，以及包含完整响应读取的单次请求时限。已有 profile 覆盖值继续生效。 |
| `maxUploadBytes` | 209715200 | 本地读取上限，同时遵守适用的服务上传上限。 |
| `maxResponseBytes` | 16777216 | 完整服务 JSON 响应的字节上限。 |
| `pageCharacters` | 12000 | 模型每次收到的转写窗口上限，单位为 UTF-16 字符。 |

`audioTranscription.catalog()` 返回当前配置的 `selected` 模型及 `models`；每个模型包含 `key`、`name` 和 `ready`。

所有字段可在插件页配置；CLI 用户也可在 profile patch 的 `tool-audio-transcription` 行 `config` 下设置。音频解码、时长限制、调度准入由 V-yovoice 负责；超限或不支持时明确失败，不在客户端分片或静默截断。取消或卸载会中止本地请求，但断连不能证明远端推理已经停止。

## 构建与验证

npm 包名为 `@ictrek/dsh-tool-audio-transcription`；发布前须确认公司控制该 npm 账号或组织并拥有发布权限。已安装旧版 `@deepseek-ai/dsh-tool-audio-transcription` 的用户应先记录服务地址和模型，再停用并移除旧包，然后安装新包并核对配置；不要同时启用两个包。会话数据不属于插件安装包，不应删除会话或工作区。

插件源码位于 V-yovoice，使用明确且干净的 v-harness 源码副本构建：

```sh
V_HARNESS_REPO=/absolute/path/to/v-harness \
  pnpm --dir integrations/v-harness/tool-audio-transcription build:release
```

脚本校验固定宿主 revision，将本包临时放入该 v-harness workspace，依次执行插件测试、lint、Host/Client 编译、`build:artifacts` 和 `build:check`，然后在被忽略的 `dist/dsh-plugin/` 下生成 `.tgz`、SHA256 和 `compatibility.json`。脚本同时检查归档不含 workspace 声明、源码入口、安装脚本或本机构建路径。将三个文件上传到专用 `harness-plugin-vX.Y.Z` Release；安装验收必须使用最终发布包。

锁定的 0.2.2-rc.1 宿主源码自身有 7 条测试文件 TypeScript 错误；脚本仅接受与已复核基线完全一致的错误，并在 `compatibility.json` 标记，任何新增错误或其他构建失败均会阻止发布。


## 模型体验

### 音频工具与原文

#### 模型看到什么

插件增加四个工具声明及音频使用提示。音频字节不进入大模型请求。成功转写的完整原文作为工具结果元数据留存在会话，模型每次收到有界文本窗口、总长度和下一页位置；后续通过读取工具分页，不重复识别。转写属于不可信来源内容，不作为指令执行；总结只依据实际读入的部分。

#### Token 影响

工具声明及返回的窗口消耗上下文。卡片可读取完整原文，不会将全文重复注入每次模型请求。

#### KV Cache 影响

启停改变工具与提示声明；转写文字通过正常工具结果进入后续请求。


## 已知限制与后续工作

- MP3 是必测格式；其他格式的浏览器播放和 V-yovoice 解码能力取决于实际宿主与服务。全文件录音须满足服务的总限制；旧版单段服务直接执行模型限制。不包含流式识别、客户端切片、语音合成或环境音分析。超时后远端工作可能继续，重试前应检查服务。公开发布与市场上架留待后续。
