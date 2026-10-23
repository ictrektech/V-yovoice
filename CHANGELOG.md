# Changelog

各版本的重要更新记录。日常改动记入 `Unreleased`；发布前合并重复项，整理为简短的功能、改进和修复说明。

## [Unreleased]

### 简体中文
- 开发模式通过 V-Scheduler 统一模型网关调用平台已有服务，不启动本地推理或重复登记调度身份；语音目录按实际能力显示，平台缺少 ASR/TTS 时明确提示。
- 修复开发页面无法通过局域网地址访问的问题；端口冲突或开发凭据无效时在启动阶段明确报错。
- 修复浏览器开发模式下打开语音模型等页面时重复显示工作台侧栏的问题，并纠正语音服务连接。

### English
- Call existing platform model services through the V-Scheduler gateway in browser development, without local inference or duplicate scheduling identities; filter speech capabilities and clearly report missing ASR/TTS services.
- Allow LAN access to the development page and report occupied ports or invalid development credentials at startup.
- Fix duplicate workbench sidebars when opening speech model and related pages in browser development mode, and correct speech service routing.

## [0.0.28] - 2026-10-22

### 简体中文
- 精简 AMD64 CUDA 镜像：保留 cuDNN 符号链接，避免重复打包相同库；安装包不再留在历史镜像层中。保持现有模型、接口及 GPU 运行库版本不变。

### English
- Slim the AMD64 CUDA image by preserving cuDNN symbolic links and keeping installation wheels out of image layers, without changing supported models, APIs or GPU runtime versions.

## [0.0.27] - 2026-10-22

### 简体中文
- 移除仅支持 PyTorch 的四个原生音乐模型和独立配乐接口，精简 GPU 运行镜像；保留 ONNX、GGUF 语音与音乐、编曲，已有模型文件和用户作品不删除。
- 各功能页新增「准备模型」，在当前页面下载、暂停或继续准备所需模型，关闭后保留原页面与编辑内容。
- 新增「关于」窗口；修复共享模型下载失败后的重试和状态归属，避免未下载的模型被误报为下载未完成。

### English
- Remove four PyTorch-only music models and the separate native music API, and slim GPU runtime images while retaining ONNX, GGUF speech/music and score workflows. Existing model files and projects are preserved.
- Add Prepare models to feature pages for in-place model download, pause and resume without leaving the current work.
- Add an About dialog and fix shared model download retries and per-model failure status, avoiding incomplete-download warnings for models that were never downloaded.

## [0.0.26] - 2026-10-22

### 简体中文
- 修复已校准的语音识别与说话人组合在使用不同执行器时无法自动接入的问题；继续核验调度器身份及所有模型的执行器审批。
- 语音生成、故事配音、音乐生成和编曲页的模型选择器直接显示所选模型是否就绪，并可在当前页面下载、暂停或继续下载，无需先打开模型管理页。

### English
- Accept calibrated speech and speaker combinations with distinct approved executors, while retaining Scheduler identity and executor approval checks.
- Show whether the selected model is ready directly in the model selector on speech, story dubbing, music generation and score pages, with download, pause and resume actions available without opening model management.

## [0.0.25] - 2026-10-21

### 简体中文
- 自动接入兼容旧版 VOS 应用身份核验，继续严格限制为 V-Scheduler 服务身份。
- 修复旧版 VOS 上选择“跟随 VOS”仍显示浏览器语言的问题；支持平台语言切换，无需刷新页面。
- 尚无就绪语音模型时明确提示先下载模型，避免误报为等待调度器接入。

### English
- Verify the Scheduler service identity on older VOS versions during automatic binding.
- Follow the platform language on older VOS versions and update open pages when the platform language changes.
- Explain when speech models need downloading instead of showing a generic scheduler setup message.

## [0.0.24] - 2026-10-21

### 简体中文
- 推理请求可携带任务优先级、协作让出、请求抢占和管理员强制尝试参数；保持原生退出及模型卸载后释放预算，管理员身份仅在当前请求转交。

### English
- Carry task priority, cooperative preemption consent and verified administrator force-admission intent on inference requests. Preserve native exit and unload barriers without persisting operator credentials.

## [0.0.23] - 2026-10-21

### 简体中文
- 自动登记 V-Scheduler 应用心跳与批准预算；支持从统一接入页面停止语音执行，确认原生退出及权重卸载后释放资源，停止回执可在重启后重试。保留原共享模型目录、输入限制和配乐任务取消机制。

### English
- Automatically register approved executors and heartbeat with V-Scheduler. Stop speech execution from the unified integration page, releasing resources only after native exit and model unloading. Persist confirmed stop receipts for retry after restart, preserving shared models, input limits and music task cancellation.

## [0.0.22] - 2026-10-20

### 简体中文
- VOS 默认接入地址统一为 `v-scheduler`，保留共享模型目录和显式配置；复用 0.0.21 原生镜像，不改变推理运行时及资源设置。

### English
- Prefer the canonical `v-scheduler` VOS endpoints while preserving shared model paths and explicit settings. Reuse the 0.0.21 native images with unchanged inference runtime and resource settings.

## [0.0.21] - 2026-10-19

### 简体中文
- 新增「配乐生成」，整合 V-Music 的 ACE-Step 1.5 Turbo、Stable Audio 3 Small-Music / Medium、MusicGen Small，支持按模型适配的生成参数、WAV/FLAC 试听下载和多语言 API 文档。
- 配乐模型统一纳入创作模型管理，复用公开 ModelScope 权重与 V-Scheduler 共享存储、输入限制和资源调度；界面显示实际审批输入上限并阻止超限请求，与旧 ASR、TTS、声纹及创作审批共存，保留旧接口与上传配置。
- 降低低内存设备 CPU 语音模型卸载后的常驻占用，统一遵循强制 CPU 配置；优化 Stable Audio GPU 权重加载，修复配乐子进程生命周期及各平台运行时依赖。

### English
- Add background music generation with V-Music's ACE-Step 1.5 Turbo, Stable Audio 3 Small-Music / Medium and MusicGen Small, model-aware generation controls, WAV/FLAC playback and download, and multilingual API documentation.
- Unify music model management with public ModelScope weights and V-Scheduler storage, bounded inputs and admission. Display approved input limits and block oversized requests. Preserve existing ASR, TTS, speaker and creation approvals, APIs and upload settings.
- Reduce retained CPU speech memory after unloading, honor CPU model configuration consistently, optimize Stable Audio GPU loading, and fix music worker lifecycle and platform runtime dependencies.

## [0.0.20] - 2026-10-19

### 简体中文
- 修复 L4T 安装配置覆盖强制 CPU 模型列表的问题，保留 Paraformer 默认兼容行为，并允许为低内存设备选择 CPU 推理。

### English
- Honor the configured CPU model list on L4T while retaining the default Paraformer compatibility setting, enabling measured low-memory inference configurations.

## [Earlier integration and upstream notes]

### 简体中文
- VOS 窗口右上角新增“关于”按钮，显示应用版本、App ID、运行配置、推理后端及 V-Scheduler 模型网关连接状态。
- 修复未下载过的模型错误显示“下载未完成”：整仓下载失败不再影响其他精度，只有本模型自己的文件失败才提示。
- 修复共享仓库下载失败后“继续下载”永远被拒绝的问题：改为按当前模型文件重新下载，失败原因直接显示在创建页。
- 模型下载与生成互不阻塞：下载进度单独显示并可单独暂停，正在下载的模型不能移除或用于生成；更换模型目录后自动识别已有完整模型。
- 作品、音色、模型和设置改用 SQLite 数据库保存在数据目录，逐项写入并自动备份；升级时自动导入原 `state.json`，迁移数据目录期间可继续编辑，接口设置与 AI 密钥一并保留。
- 删除作品、历史、音频和清理残留统一按引用登记判断，共享素材不会被误删；启动自检只在确认文件不存在时才移除内容，修复前自动留存快照；存储配置损坏或磁盘已满时明确提示。
- 音频读不到时播放器与时间线直接标出不可用，不再主动弹窗；打开作品只预读音频时长，弹窗背景去掉模糊并修复 macOS 弹窗背后出现边线。
- 本地服务意外停止时可一键重启并补存修改；应用异常退出后不再残留推理进程；修复 Windows 退出、托盘与菜单行为，原生菜单和错误提示支持英文。
- 界面修复：AI 写作栏未配置时统一从“设置 AI”进入；窄屏检查器保持宽屏宽度、不再全屏覆盖正文；创作区变窄时右侧面板自动收起；单页渲染出错只提示该页。

### English
- Add an About button in the top-right VOS titlebar showing the app version, App ID, profile, inference backend and V-Scheduler model gateway connection state.
- Stop reporting never-downloaded models as an incomplete download: a failed whole-repository task no longer affects every precision, only that model's own failed files are reported.
- Fix resume being rejected forever after a shared repository download failed by downloading the selected model files again, and show the failure reason on the creation page.
- Let model downloads and generation run independently, with separate progress and pause, and prevent removing or using a model that is still downloading; recognize complete models after changing the model directory.
- Store works, voices, models and settings in a SQLite database in the data directory with incremental writes and automatic backups; import the previous `state.json` on upgrade, keep editing during a data directory migration, and retain local API settings and AI keys.
- Decide file usage from one reference registry when deleting works, history, audio and leftovers so shared assets are never removed; remove timeline content only when startup checks confirm a file is missing, taking a snapshot before repair; report corrupt storage configuration or a full disk explicitly.
- Mark unavailable audio directly in the player and story timeline instead of popping up a notice, pre-read only the duration when opening a work, and remove the blurred dialog backdrop and the macOS edge line behind dialogs.
- Restart a stopped local service in place and save pending edits, remove leftover inference processes after an abnormal exit, fix Windows exit, tray and menu behavior, and localize native menus and error messages to English.
- Interface fixes: route AI writing setup through AI settings, keep narrow-screen inspectors at desktop width instead of covering the text, collapse the side panel when the creation area is narrow, and show render errors only for the affected page.

- Windows 自动更新在应用已签名时校验更新包的发行者签名，签名不一致时拒绝安装；正式发布配置证书后自动签名应用、服务与安装包。
- 自定义数据目录被删除、改名或所在磁盘未连接时，启动不再静默新建空目录，而是提示重试、退出或新建空目录；运行中数据目录丢失时保存会明确提示目录不存在；迁移后的新目录若是空的不再自动删除旧目录，避免误删唯一一份数据；Windows 退出时作品保存失败也可选择不备份直接退出。
- 新增 Breeze TTS 2（中英，Q4 / Q8 / BF16）：可用文字描述设计音色，或用参考音频和原文克隆并以描述调整语速、情绪和语气；默认缩短分段、限制单段生成长度并在显卡上使用 bf16 推理，减少拖音和长段静音。模型需要 v0.9.1 内核，权重仅限非商业用途。
- 新建作品菜单新增“导入文件配音”：导入 TXT 或 Markdown 文本直接生成语音作品，导入 SRT、VTT、ASS 字幕生成故事作品；自动识别 UTF-8、UTF-16 与 GBK 编码，Markdown 的标记符号会被去掉。
- CLI 新增 `yovoice mcp`，以 stdio 方式提供 MCP，Claude Desktop、Cursor 等本机客户端可直接作为子进程启动，无需令牌；结果直接返回生成音频的本机路径，`upload_voice` 也可按本机路径导入参考音频。
- 设置 › 常规新增“本机接口”：开启后在 127.0.0.1 上提供与 `yovoice serve` 相同的 HTTP / MCP 接口（默认端口 8080，可修改），本机其他软件凭访问令牌即可调用桌面应用里的模型生成语音；令牌可复制、重置，端口被占用时直接提示。
- AI 服务新增 OrcaRouter（兼容 OpenAI 接口）：点“免费连接 OrcaRouter”在浏览器登录并同意授权后自动添加，默认使用免费模型，不用复制密钥；免费模型被拒绝时分别提示还需等待几秒、内容超过免费长度上限或需要绑定 GitHub。
- Windows 与 macOS 应用内更新提示：发现新版本时弹出提示并在侧栏显示下载进度，可查看对应语言的更新内容，下载完成后一键重启更新；设置页新增“版本与更新”，可随时检查更新，更新后首次启动会提示新版本内容。
- 修复语音生成面板中“更多情绪”与“微调情绪”折叠按钮残留边框与背景的问题，统一为轻量幽灵折叠外观。
- 修复缺少乐谱数据的旧编曲作品在启动或打开时导致整个窗口白屏的问题，这类作品会自动补上空乐谱。
- 侧栏导航与新建作品菜单将“语音生成”置于首位（排在“故事配音”上方）；桌面端重新打开时默认展示作品列表（不自动打开内容页），并记住离开前所在的分类页面。
- 参考音频的“使用中”检查不再受生成历史阻断，删除音色时自动清空历史版本中的引用；删除作品时级联清理该作品的所有历史版本、导入的时间线素材及磁盘文件，异常条目和磁盘文件丢失也可正常删除。
- 设置 › 常规新增“存储”分组：直观展示数据目录与各类空间占用（模型、生成音频、参考声音与缓存），支持“更改位置”（带进度条弹窗把数据完整复制到新目录并改写路径，迁移中途失败不影响原目录；完全退出并重新打开后生效，旧目录随后自动删除以释放空间；重启前暂停保存修改，禁止设在应用安装目录或当前数据目录内）与“清理残留”（保护存活作品与时间线素材，回收超过 24 小时的孤儿历史版本与无引用文件）；Windows 全新安装在非系统盘时默认使用安装目录旁的 `yovoice-data` 目录并记住该选择，macOS 同样读取迁移后的数据目录。
- 优化 API 生成音频的生命周期管理：接口高频生成时只保留最新 50 条无所属作品的历史并释放物理音频，时间线仍在使用的版本不受影响。
- 数据生命周期治理：启动时自动修复时间线中指向已缺失版本或素材的悬空片段（此前会导致作品永久无法保存），并在后台自动清理残留，无需手动点击；“清理残留”额外回收故事作品中已被替换且 24 小时未编辑的逐句旧版本，以及 downloads 中超过 24 小时的内核安装包缓存；内核安装完成后立即删除安装包；移除应用下载的模型时同时删除模型文件释放空间，导入的模型仍只解除登记。
- 引用与重复数据治理：重复导入同一工程时复用内容完全相同的参考音频和角色，不再每次堆积副本；删除角色后作品与说话人自动解除关联并保留已复制的设置；字幕作品中被说话人设置覆盖、界面不可见的作品级音色不再阻止删除参考音频，删除时一并清理；启动自检额外清理指向已删除角色或音频的悬空引用；`state.corrupt-*.json` 最多保留 3 份；Windows `host-service.log` 超过 5MB 时滚动切分。
- 更改数据存储位置后自动重启：迁移完成时弹出提示并自动退出、重新打开应用，新目录立即生效，不再需要手动从托盘退出；迁移前先保存界面中尚未落盘的正文，迁移后退出不再因旧目录冻结而报“作品保存失败”。
- 修复迁移数据目录后退出时报 `@yovoice.error.storageRestartRequired`“退出前未能保存作品”且无法退出：旧目录冻结期间的退出保存直接跳过；工作台测试整体隔离用户目录，运行测试不再改写本机 `storage.json`（此前会把真实应用的数据目录指向测试临时目录）。
- macOS 退出时作品保存失败（如运行中删除了数据目录、磁盘已满或外置盘断开）不再只能强制结束：与 Windows 一致提供“备份后退出 / 直接退出 / 返回编辑”，错误提示附带具体原因而非仅显示错误码。
- “当前作品”只存在于作品编辑页（含版本记录）：切到设置、声音库或作品列表时立即保存未落盘的修改并关闭作品，这些页面退出不再保存作品；内容未变化的保存不再改写状态文件，数据目录不可写时也不会因此挡住退出；删除当前作品后切换到的空白新作品不会在退出时被意外创建。

## [0.0.19] - 2026-10-16

### English

- Validate VOS speech input against V-Scheduler's measured limits before loading models. Direct and gateway calls share text, speed and bounded audio protections, while existing Thor scheduling remains compatible.

### 简体中文

- VOS 语音接口按 V-Scheduler 下发的实测范围校验文字、语速和音频；超限请求在加载模型前拒绝，音频解码有界，直连和网关采用相同保护，并兼容现有 Thor 调度。

## [0.0.18] - 2026-10-16

### English

- Use the unified V-Scheduler application for model management, model routing and scheduling. Preserve shared model files and existing gateway APIs; resolve the dependency from its current published release during packaging.

### 简体中文

- VOS 安装统一依赖 V-Scheduler，模型管理改用其内置服务；保留共享模型文件及原有网关接口，打包时实时核验已发布依赖版本。

## [0.0.16] - 2026-10-15

### English

- Fix VOS sign-in and blank workbench failures, including secure UUID and S256 PKCE support on LAN HTTP.
- Restore dedicated ASR, original TTS, speaker recognition and hotword pages, with model categories under the expandable Model management sidebar.
- Keep settings navigation inside the workbench, add a return link to the compatibility console, restore settings scrolling and share the workbench theme across service pages.
- Manage all creator variants, music models and soundfonts through ModelScope/Model Hub, with per-model download, cancellation and file-verification status; import-only weights never offer a nonexistent download, and cancellation does not stop unrelated models sharing a repository.
- Add multilingual music/score job, cancellation and private-result API documentation, alongside the existing speech APIs and OpenAPI contract.
- Support VOS-authenticated, versioned Scheduler binding and hot reload without bypassing resource admission; keep uncertain execution states and unconfirmed results private.

### 简体中文

- 修复 VOS 登录与工作台白屏问题，支持局域网 HTTP 下的安全 UUID 与 S256 PKCE 登录。
- 补齐 ASR、原有 TTS、声纹与热词专用页面，模型分类移入左侧可展开的“模型管理”子菜单。
- 设置内部切换不再跳出工作台，旧控制台增加返回入口；修复设置页滚动，统一语音服务页面与工作台主题。
- 通过 ModelScope / Model Hub 管理全部创作精度、音乐模型与音色库，显示逐模型下载、停止与文件校验状态；仅导入权重不再提供不存在的下载，取消不再影响同仓库的其他模型。
- 补齐音乐、编曲、任务查询/取消与用户私有结果的多语言 API 文档，并保留原有语音接口和 OpenAPI 契约。
- 增加经 VOS 身份核验的版本化调度绑定与热更新，不绕过资源准入；执行停止未知或调度尚未确认成功时不交付结果。

## [0.0.15] - 2026-10-15

### English

- VOS V-Voice adds a voice-creation workbench while retaining its app identity, icon, complete legacy model catalog, ASR, translation, streaming, hotwords, speaker recognition, TTS and compatible APIs. The retained service console is available alongside the workbench.
- All 38 upstream creative model/precision variants remain supported. Shared weights use ModelScope and Model Hub; native capabilities appear in V-Router discovery. Model-specific licenses apply, and import-only variants still require verified original files.
- Projects and reference voices are isolated by VOS identity. Creation tasks and direct/gateway inference integrate with V-Scheduler, with single-use permit handoff and no duplicate resource reservation. The workbench can follow VOS language without losing an edited draft.
- Migrates the existing six platform profiles, image builds, Feishu records and VOS release pipeline. `UPSTREM` records the original fork source for future merges.
- English, Simplified Chinese and Traditional Chinese UI, with a dedicated multilingual API documentation page covering both standard endpoints and model-specific extensions.
- Model browsing stays responsive during large-weight verification. Only verified models are advertised; generation checks the selected package and honors cancellation before loading it.

### 简体中文

- VOS V-Voice 新增声音创作工作台，保留应用身份、原图标、完整原模型目录、识别、翻译、流式识别、热词、声纹、TTS 与兼容 API；原语音服务控制台继续可用。
- 保留上游全部 38 种创作模型/精度，权重统一经 ModelScope 与 Model Hub 共享管理，并向 V-Router 公开模型原生能力。各模型仍受原始许可约束，仅导入版本仍需提供校验通过的原文件。
- 作品和参考音色按 VOS 身份隔离；创作任务、直接调用和网关推理接入 V-Scheduler，使用单次可核验许可交接，避免重复预约资源。创作界面可跟随 VOS 语言切换且不丢失正在编辑的草稿。
- 迁移原有六个平台 profile、镜像构建、飞书记录和 VOS 发布流程；通过 `UPSTREM` 记录原始 fork 来源，方便后续合并更新。
- 创作界面支持英文、简体中文与繁体中文，新增独立的多语言 API 文档页面，涵盖标准接口和模型专用扩展。
- 大型权重校验期间保持目录浏览可响应；仅公开已验证模型，生成前校验所选模型，并支持在装载前取消。

## [0.2.0] - 2026-10-11

### English

- New Music projects: set the style with tags, write lyrics with section markers or go instrumental, and generate full songs with ACE-Step 1.5 Turbo / XL Turbo or YuE2 3B (vocal songs whose length follows the lyrics; CC BY-NC 4.0, non-commercial). Each take is kept as a version you can preview, compare, reuse and export. Models made of several files can now be downloaded.
- New Score projects: write notes per track by bar and beat, import MIDI, or let an agent compose, then render every track with a General MIDI sound font and mix by role. The track area spans the bottom of the window with sections on the timeline, zoom, scrolling and a playhead; export MIDI or score JSON. Choose MuseScore General, GeneralUser GS or SGM-V2.01. The CLI adds `yovoice score render|midi|from-midi` with stems, MCP adds `render_score`, and the Agent Skill adds a score guide.
- Optional AI providers (DeepSeek, Qwen, Zhipu, Kimi, Doubao, MiniMax, OpenAI, Anthropic, OpenRouter, coding plans, local and custom endpoints) write a whole score or song style, lyrics and title from one sentence, run in the background, and can switch models on the spot.
- A refreshed interface: ticket-style project lists with record and cassette covers, grouped settings, a separate sound font page, side panel toggles in the title bar (the right panel toggle only appears in a workspace), and hover hints only for truncated text or icon buttons.
- The audio.cpp engine is upgraded to v0.9.1 and updates separately from the app; new Windows CUDA 12.4 and 13.3 installers.
- Fixes for long AI requests timing out, saving on exit, Windows time-zone saves, timeline menus, deleting the last project, and clearer error messages and diagnostic logs.

### 简体中文

- 新增“音乐生成”：用标签定风格，写带段落标记的歌词或改为纯音乐，由 ACE-Step 1.5 Turbo / XL Turbo 或 YuE2 3B（带人声、长度随歌词，CC BY-NC 4.0 仅限非商业）生成整首歌曲；每次生成保留为版本，可试听、对比、复用和导出。支持下载由多个文件组成的模型。
- 新增“编曲”：按小节和拍写各声部音符，或导入 MIDI、让 Agent 写谱，用 General MIDI 音色库逐声部渲染并按角色混音。轨道区横跨窗口底部，段落标在时间轴上，可缩放、滚动并显示播放指针；可导出 MIDI 或乐谱 JSON。音色库可选 MuseScore General、GeneralUser GS 或 SGM-V2.01。CLI 新增 `yovoice score render|midi|from-midi`（含分轨），MCP 新增 `render_score`，Agent Skill 新增编曲参考。
- 可选接入 AI 服务（DeepSeek、通义千问、智谱、Kimi、豆包、MiniMax、OpenAI、Anthropic、OpenRouter、编程套餐、本地与自定义接口），一句话写出整份编曲或歌曲的风格、歌词和标题，在后台进行，可随时切换模型。
- 界面焕新：票根式作品列表配唱片与磁带封面，设置页分组，音色库单独成页，左右面板开关集成到标题栏（右侧面板开关只在工作区显示），悬浮提示只在文字被截断或图标按钮需要说明时出现。
- 推理内核升级到 audio.cpp v0.9.1，与应用分开更新；新增 Windows CUDA 12.4 与 13.3 安装包。
- 修复长 AI 请求超时、退出保存、Windows 时区作品保存、时间线菜单、删除最后一个作品等问题，错误提示和诊断日志更具体。

## [0.1.7] - 2026-10-05

### English

- Run a remote speech service with HTTP API and MCP support. Submit, query, cancel, and download generation tasks with authentication, retry deduplication, and configurable timeouts.
- Use the Agent Skill with either a local CLI or a remote service. User guides and CLI packages now include separate English and Chinese documentation.
- Fix Windows save-error reporting and allow a recovery backup when saving on exit fails. Improve diagnostic logs for saving and generation failures.

### 简体中文

- 新增 HTTP API 与 MCP 远程语音服务，支持任务提交、查询、取消和音频下载，提供认证、重试去重与可配置超时。
- Agent Skill 支持本地 CLI 和远程服务；用户指南与 CLI 安装包提供独立中英文文档。
- 修复 Windows 保存错误提示，退出保存失败时可备份作品；完善保存和生成失败的诊断日志。

## [0.1.6] - 2026-10-01

### Added

- 角色支持保存多种演绎方式，每种演绎可独立选择模型和参数，故事台词和语音项目可分别选用。

### Fixed

- 统一演绎选择框与新增、更多按钮的尺寸和对齐。
- 修复音轨面板调高区域遮挡播放按钮的问题，拖拽仅在顶部横线附近触发，横线贴近面板上边线外侧，并缩小播放控制图标。
- 移除应用图标底板边缘的光带，清理透明轮廓杂点，并校准 macOS 图标的主体边界和小尺寸留白。

## [0.1.5] - 2026-09-29

### Added

- 新增故事配音与语音生成两类作品，支持字幕导入、分段生成和可编辑音轨。
- 新增音轨裁剪、撤销与重做、混音及 WAV 导出，支持作品归档导入导出与状态恢复。
- 新增 Kokoro 官方 BF16 模型下载。
- 新增版本变更日志，发布时自动将对应版本的说明展示到 GitHub Release 页面。

### Changed

- 移除待处理台词批量生成，播放时正文始终自动跟随。

### Fixed

- 优化音轨缩放、滚动、片段拖动与磁吸裁剪交互，统一单人和多人播放指针样式。
- 修复旧版 WebKit 下拉浮层样式，通知展示不再挤动工作台布局。
- 改进 Windows 窗口尺寸适配与位置保存，以及 macOS 应用启动和图标边距。

## [0.1.4] - 2026-09-26

### Added

- 新增角色库，保存并复用音色与声音设置；声音库与创作流程共用编辑能力。
- 新增 Kokoro 官方 Q8 模型下载及 49 个内置音色，支持实验性多语言和中文版本导入。

### Changed

- 优化声音库、生成历史、参考音频片段与原文管理，统一搜索、头像、音频试听和弹窗交互。

### Fixed

- 修复 macOS 麦克风权限回调崩溃，兼容旧版 macOS 的下拉选择器。
- 修复 VoxCPM2 长参考音频的编码器容量问题。
- 修复服务退出时未等待清理完成的问题，并保留 Windows 界面兼容修复。

## [0.1.3] - 2026-09-19

### Changed

- 优化 Windows 窗口边框、滚动、原生菜单与应用对话框。
- 新增代理开关和设置自动保存，调整下拉菜单定位。

### Fixed

- 修复 Windows 下载归档目录路径处理，完善 .NET 8 构建兼容性。

## [0.1.2] - 2026-09-18

### Added

- 新增 OmniVoice 与 Qwen3-TTS 模型及对应的声音设计、克隆和生成参数。
- 新增英文界面，支持语言偏好及 macOS 菜单、提示本地化。

### Changed

- 整理偏好设置、模型目录操作与生成控制面板。

### Fixed

- 修复 macOS 自动更新时 `lipo` 架构校验参数顺序错误。

## [0.1.1] - 2026-09-16

### Added

- 新增 VoxCPM2 Q8 / BF16，支持声音设计、音色克隆和参考原文辅助克隆，App 与 CLI 均可使用。
- 新增声音描述、引导强度、推理步数和随机种子设置。

### Changed

- 优化模型管理布局与按钮，下载期间可移除其他模型的登记。
- 简化 `make app-run`，分离日常启动与安装包制作；采用完整生成后播放。

### Fixed

- 修复 macOS 麦克风权限归属，改用原生权限请求。

## [0.1.0] - 2026-09-16

### Added

- 首个公开版本，提供 macOS Apple Silicon 与 Windows 桌面安装包。
- 支持 IndexTTS 2.0 / 2.5 本地生成、模型下载及 GGUF 导入。
- 支持参考音色、参考演绎、情绪调节、文字引导和参考音频录制。
- 提供声音库、作品历史、版本管理与音频试听。
- 提供 macOS、Windows、Linux 独立 CLI 与 Agent Skill，内置精简 FFmpeg 处理常见音频格式。
