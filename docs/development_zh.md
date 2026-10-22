# 开发指南

[English](development.md) · 简体中文

本指南用于从源码构建 yovoice。直接安装请查看 [CLI 安装](cli_zh.md#安装)或 [Releases](https://github.com/leemysw/yovoice/releases)。

## 环境要求

- Node.js 22+、pnpm 9.15.2、Go 1.26+、Python 3.12+。
- 音频转换器构建需要 Make、Bash、curl 和 C 编译器。
- macOS：Apple Silicon、macOS 14+、Xcode Command Line Tools。
- Windows：Windows 10/11 x64、.NET SDK 8、WebView2 Runtime、MSYS2 MinGW64。制作安装包还需 Inno Setup 6，使用 Make 命令需 GNU Make。

Windows 在 MSYS2 MinGW64 终端中安装音频构建工具：

```sh
pacman -Syu
pacman -S --needed make curl diffutils mingw-w64-x86_64-gcc mingw-w64-x86_64-python
```

更新要求重新打开终端时按提示操作。构建默认查找 `artifacts/tooling/msys64` 或 `C:/msys64`；其他位置可通过 `YOVOICE_MSYS2` 指定。

## 运行 App

```sh
git clone https://github.com/leemysw/yovoice.git
cd yovoice
make install
make app-run
```

后续命令均在仓库根目录执行。`app-run` 只构建并启动，不执行测试或打包；macOS 下会在终端显示日志。关闭窗口不会退出 App，重新构建前请通过应用菜单退出。日志位于 `~/.yovoice/logs`。

仅开发浏览器界面时运行 `make dev`，访问 `http://127.0.0.1:5173`。本地语音生成需要桌面 App 或 CLI。

在安装了 V-Scheduler 的 Orin / JetPack 6 本机联调真实语音服务：

```bash
npm --prefix frontend ci  # 首次安装兼容语音页面依赖
make dev-browser
# 也兼容原来的同机地址：
VITE_VOS_SPEECH_SERVICE_BASE=http://192.168.1.207:22700 make dev-browser
```

访问 `http://192.168.1.207:5173`（换成开发机实际 IP），无需 VOS 登录桥。
Vite 监听 `0.0.0.0:5173`；Python 语音服务和 Go 后端仅监听本机 `22700`、`7080`，
浏览器 API 全部由 Vite 同源转发。本地 22700 无需对局域网开放。

启动器复用本机已缓存的 `v-voice:l4t_*` 运行镜像，按需通过 `VVOICE_DEV_IMAGE`
选择已有镜像，不拉取或构建镜像。当前源码只读挂载到开发容器，Go 在启动时重新编译，
修改后端后 Ctrl+C 再运行命令即可；前端保留 Vite 热更新。不要求 VOS 安装 V-Voice。
模型目录自动从本机 Scheduler 容器的 `/data` 挂载解析，只读共享，不复制或重复下载；
模型下载操作仍由 Scheduler 的模型仓库 API 负责。

首次启动通过 Scheduler 管理 API 登记独立的 `com.ictrek.v-voice.dev` 身份和执行器，
只沿用同机已有的 `orin-voice-native-bounded-v1` 校准，不改变原 VOS 应用的凭据和执行器。
每次推理仍申请、认领并在原生计算停止及卸载后释放许可；资源不足返回 429，不能绕过。
当前支持 Kokoro（最多 512 字符、速度 1）和 SenseVoice（最多 20 秒、24 kHz、
请求体最多 1 MiB、不支持热词）。CAM++ 等模型文件可显示就绪，但此校准未批准其推理；
GGUF 创作与音乐任务也需要各自校准和批准，不能继承这两个模型的预算。

开发数据和私有调度配置默认保存在 `/tmp/yovoice-dev-data`，可通过 `YOVOICE_DEV_DATA`
指定持久目录。提交凭据仅存后端 `0600` 配置文件，重启复用，不发给浏览器。
`VVOICE_DEV_TOKEN` 是单独的浏览器开发凭据，如需自定义，应为至少 32 位的字母、数字、
下划线或连字符。正式 VOS 登录不受影响。

按 Ctrl+C 停止整套开发服务。5173、7080 或 22700 已占用时启动器明确报错。
如果看到 `Local compute resources are busy`，检查 Scheduler 调度状态及可用内存；
这台设备的语音预算为 2304 MiB，另有系统安全余量，不能只看 GPU 是否空闲。

其他开发机只联调 Go 和页面时使用 `VVOICE_DEV_SPEECH=off make dev-browser`；
这时语音页提供未安装的源代码目录，不启动推理。如果要连接另一台机器上**已运行的**
V-Voice，显式使用
`VVOICE_DEV_SPEECH=external VITE_VOS_SPEECH_SERVICE_BASE=http://<服务IP>:22700 make dev-browser`；
external 模式只转发语音请求，不为本机创作任务授予调度权限。

## 构建与打包

| 命令 | 产物 |
| --- | --- |
| `make app-build` | `artifacts/macos-arm64/` 或 `artifacts/windows-x64/` 中的 App |
| `make app-package` | `artifacts/` 中的 macOS DMG/ZIP 或 Windows Setup EXE |
| `make cli-build` | CLI 可执行文件和 `artifacts/tools/` |
| `python3 scripts/package-cli.py` | `artifacts/` 中的独立 CLI ZIP |

CLI 需保留同级的 `tools/` 目录。完整安装包应在目标平台构建。macOS DMG 打包需要已登录的桌面会话和 Finder 自动化权限。

Windows 未安装 GNU Make 时，可在 PowerShell 中运行：

```powershell
./scripts/desktop/build-windows.ps1
./scripts/desktop/build-windows.ps1 -Package
./scripts/desktop/build-windows.ps1 -Package -Cuda  # 另生成 CUDA 12.4 / 13.3 完整安装包
python scripts/package-cli.py
```

模型转换与 App 打包独立。准备兼容的 Kokoro 模型时，可在仓库中运行 `python scripts/prepare-kokoro-models.py --help` 查看用法。

## 测试

```sh
pnpm --dir web exec playwright install chromium
make check
```

`make check-core` 检查 Go 格式与静态分析，并运行带竞态检测的测试；`make check-web` 执行前端构建与浏览器测试。原生安装和 GPU 推理还需在目标平台验证。

## 项目结构

| 目录 | 用途 |
| --- | --- |
| `cmd/` | CLI 和本地服务入口 |
| `internal/` | Go 服务实现，按职责分包（见下） |
| `desktop/macos/`、`desktop/windows/` | 原生 App 宿主 |
| `web/src/` | 前端应用 |
| `web/browser-tests/` | 浏览器测试 |
| `scripts/` | 构建与打包工具 |

### 架构约定

- 前端依赖方向为 `app → features → shared`，`shared` 不引用业务模块。
- Go 服务按职责分包，依赖只能自上而下：

  | 层 | 包 | 职责 |
  | --- | --- | --- |
  | 传输 | `desktop`、`remote` | 桌面本机服务与 RPC 分发；远程 HTTP API、异步任务与 MCP |
  | 应用 | `workbench` | 作品、素材、角色、模型、运行时、生成与工程归档 |
  | 基础 | `engine`、`store`、`download`、`audio` | 推理进程、状态持久化、下载解包、音频解析与转码 |
  | 模型 | `schema`、`catalog` | 持久化结构与校验；模型目录与生成参数 |
  | 叶子 | `msg`、`diag`、`platform` | 消息码、诊断日志、平台差异 |

  传输层只解码请求并调用 `Workbench` 的公开方法，不访问其内部状态。`testkit` 仅供测试引用。
- 桌面调用并发执行。`Workbench` 用编辑锁串行化“读取 → 校验引用 → 写入”的短事务，转码、下载、推理与工程导入导出不持锁；后台操作同一时间只运行一个。
- 模型目录、生成参数和 OmniVoice 属性同时嵌入 Go 服务并供界面引用，`internal/catalog/*.json` 与 `web/src/shared/lib/*.json` 需保持一致（`engine.json` 仅供服务端与构建脚本使用，没有界面副本）。
- 消息码在 `internal/msg` 中声明，须加入 `msg.All` 并在两种界面语言中提供文案。
- 升级 audio.cpp 时只修改 `internal/catalog/engine.json`：`version` 是推荐版本，`minimum` 是请求格式与模型包所需的最低版本，另含运行包校验值；在线安装与 `scripts/desktop/` 构建脚本都从它读取。已安装内核的版本记录在状态中，低于 `minimum` 时必须升级，低于 `version` 时界面提供可选升级。只有确实依赖新内核时才提高 `minimum`。
- Windows `-Package` 生成完整 CPU 安装包与只含应用本体的 `-update.exe`；自动更新只下载后者，`engine/` 目录及其中的 `yovoice-engine.json`（内置内核的版本与后端）在更新时保持不变。

后三项由 `go test` 校验。

公开指南使用英文 `*.md` 和中文 `*_zh.md`。修改用户可见行为时，同步更新两种语言及其链接。

从 v0.1.7 起，CHANGELOG.md 的发布说明需分别包含 `### English` 和 `### 简体中文` 两部分。发布流程在构建前检查两种语言是否齐全。
