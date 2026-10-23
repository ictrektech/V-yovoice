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

通过本地页面复用 VOS 平台中已有的模型服务：

```bash
npm --prefix frontend ci  # 首次安装语音页面依赖
VVOICE_GATEWAY_BASE=http://192.168.1.207:22888 make dev-browser
```

访问 `http://<开发机IP>:5173`，无需 VOS 注入登录桥。开发机不必是 VOS 宿主机，
只需能访问平台网关。省略 `VVOICE_GATEWAY_BASE` 时连接 `http://127.0.0.1:22888`；
也可填写以 `/v1` 结尾的 API base。`22700` 是 V-Voice 原生服务端口，不能替代网关。
旧的 `VITE_VOS_SPEECH_SERVICE_BASE`、`VVOICE_DEV_SPEECH` 选项已移除。

调用链为：浏览器 → 本地 Vite → V-Scheduler `/v1/*` → 平台已有推理服务。
Vite 监听 `0.0.0.0:5173`，Go 仅在 `127.0.0.1:7080` 保存作品和提供媒体接口。
启动器不会启动 Python/Docker 推理、读取共享权重、登记执行器或申请第二份调度许可；
准入、路由、执行与释放由平台已有链路负责。端口 5173 或 7080 被占用会明确报错。
按 Ctrl+C 停止页面和 Go 服务，不影响平台模型服务。

模型管理读取源码中的完整支持目录（当前 45 个：9 ASR、35 TTS、1 声纹），
不要求 VOS 安装 V-Voice。开发启动时仅用 Python 标准库导出模型描述，不启动 Python 推理。
下载、暂停和重新下载提交给平台模型仓库；共享 GGUF 只下载所选模型的文件。
`MODEL_HUB_API_URL` 默认使用网关主机的 `36005` 端口，例如
`http://192.168.1.207:36005`；也可设为网关的 `/model-hub` 地址。
同源网关地址复用服务端网关凭据，直连模型仓库时不转发网关凭据。

“文件已准备”表示平台已有所需文件，不代表推理服务已经运行。
ASR/TTS 选择器仅列出网关已有的对应服务；部署推理服务仍由平台完成，
V-Voice 不是显示目录和下载文件的必装依赖。仅有聊天、向量或重排服务不能转写或合成。
`/v1/models` 保留平台完整服务目录与模型 ID；推理请求保留完整网关模型 ID，
音频上传、音频响应与平台错误原样转发。

如果网关需要登录，或需要读取完整能力目录及私有模型，在本机创建 `0600` 凭据文件，
写入有效的 VOS 用户 access token 或网关 Key（可带 `Bearer ` 前缀），再运行：

```bash
VVOICE_GATEWAY_BASE=http://192.168.1.207:22888 \
VVOICE_GATEWAY_TOKEN_FILE=/absolute/private/gateway-token \
make dev-browser
```

凭据仅由 Vite 服务端读取，不进入前端构建。浏览器开发凭据和 Cookie 不会转发给平台。
读取能力目录需要获准访问网关 `/api/v1/models` 的身份；仅支持推理的应用凭据不能代替。
凭据失效时显示服务鉴权错误，支持目录仍保留。网关匿名调用策略由平台本身决定。

本模式不提供热词库、声纹库管理或本地创作执行器。
推理实例装卸和业务库管理应在平台对应服务中完成；不支持的管理请求明确返回 501。
网关返回的 429、输入边界和模型就绪状态继续有效，不在开发模式绕过。

开发数据默认保存在 `/tmp/yovoice-dev-data`，可用 `YOVOICE_DEV_DATA` 指定持久目录。
`VVOICE_DEV_TOKEN` 是本地作品接口的开发凭据，和网关凭据不同；自定义值至少 32 位，
仅包含字母、数字、下划线和连字符。正式 VOS 安装的鉴权和推理流程保持原样。

定向验证开发网关适配器：`node --experimental-strip-types --test tests/dev-gateway*.test.ts`。
测试用受控上游验证代理契约；只有平台已有真实 ASR/TTS 服务并完成调用后，才能认定真实语音推理通过。

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
