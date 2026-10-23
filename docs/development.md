# Development

English · [简体中文](development_zh.md)

This guide is for building yovoice from source. For prebuilt packages, see [CLI installation](cli.md#installation) or [Releases](https://github.com/leemysw/yovoice/releases).

## Requirements

- Node.js 22+, pnpm 9.15.2, Go 1.26+, Python 3.12+.
- Make, Bash, curl, and a C compiler for the bundled audio converter.
- macOS: Apple Silicon, macOS 14+, and Xcode Command Line Tools.
- Windows: Windows 10/11 x64, .NET SDK 8, WebView2 Runtime, and MSYS2 MinGW64. Install Inno Setup 6 to create installers. Make targets require GNU Make.

On Windows, install the audio build tools in the MSYS2 MinGW64 terminal:

```sh
pacman -Syu
pacman -S --needed make curl diffutils mingw-w64-x86_64-gcc mingw-w64-x86_64-python
```

Reopen the terminal if the update requests it. The build finds MSYS2 at `artifacts/tooling/msys64` or `C:/msys64`; set `YOVOICE_MSYS2` for another location.

## Run the app

```sh
git clone https://github.com/leemysw/yovoice.git
cd yovoice
make install
make app-run
```

Run all following commands from the repository root. `app-run` builds and starts the app without tests or packaging. On macOS, it streams logs to the terminal. Closing the window keeps the app running; quit from the app menu before rebuilding. Logs are in `~/.yovoice/logs`.

For browser-only UI development, run `make dev` and open `http://127.0.0.1:5173`. Local speech generation requires the desktop app or CLI.

To reuse model services already running in VOS from a local development page:

```bash
npm --prefix frontend ci  # first setup of the speech pages
VVOICE_GATEWAY_BASE=http://192.168.1.207:22888 make dev-browser
```

Open `http://<development-host-IP>:5173`; no VOS login bridge is required.
The development machine need not host VOS; it only needs access to the gateway.
The default is `http://127.0.0.1:22888`; a base ending in `/v1` is also accepted.
Port 22700 belongs to the native V-Voice service and is not the gateway.
The previous `VITE_VOS_SPEECH_SERVICE_BASE` and `VVOICE_DEV_SPEECH` options are removed.

Requests follow browser → local Vite → V-Scheduler `/v1/*` → existing platform
inference service. Vite listens on `0.0.0.0:5173`; Go handles local project storage
and media on loopback port 7080. The launcher starts no Python/Docker inference,
mounts no weights, registers no executors, and acquires no duplicate permits.
Platform routing and execution retain responsibility for resource admission and
release. Occupied ports 5173 or 7080 fail startup. Ctrl+C stops local development
services without stopping platform model services.

`/v1/models` retains the full platform catalog and qualified IDs. Speech pages
filter explicit ASR/TTS/speaker capabilities. Anonymous OpenAI catalogs lack those
fields, so only exact known `v-voice/<model>` IDs are mapped; unknown model names
are never treated as proof of speech capability. Missing speech services are
shown as unavailable. Downloaded weights do not prove an inference service exists;
Qwen chat, embedding and reranking models cannot supply ASR/TTS. Inference retains
qualified model IDs and forwards audio uploads, audio responses and platform errors.

If the gateway requires authentication, or to read full capabilities and private
models, create a local 0600 file containing a valid VOS user access token or gateway
Key (an optional `Bearer ` prefix is accepted), then run:

```bash
VVOICE_GATEWAY_BASE=http://192.168.1.207:22888 \
VVOICE_GATEWAY_TOKEN_FILE=/absolute/private/gateway-token \
make dev-browser
```

Only the Vite server reads this credential; it is not bundled into the frontend.
Browser development credentials and cookies are not forwarded. Capability discovery
requires permission to read gateway `/api/v1/models`; inference-only application
credentials do not replace that identity. Invalid credentials produce an auth
error rather than an empty catalog. Anonymous inference follows platform policy.

This mode does not implement native V-Voice model installation, hotword/speaker
library management or local creation executors. Manage these in the corresponding
platform service. Unsupported management requests return 501. Platform 429 responses,
input limits and model readiness remain effective.

Data defaults to `/tmp/yovoice-dev-data`; use `YOVOICE_DEV_DATA` for a persistent
location. `VVOICE_DEV_TOKEN` is a separate local project API credential; custom
values require at least 32 letters, digits, underscores or hyphens. Production VOS
authentication and inference are unchanged.

Run focused gateway checks with
`node --experimental-strip-types --test tests/dev-gateway*.test.ts`.
Controlled upstreams verify proxy contracts; real speech inference is only verified
when an existing platform ASR/TTS service successfully handles a request.

## Build and package

| Command | Output |
| --- | --- |
| `make app-build` | Runnable app in `artifacts/macos-arm64/` or `artifacts/windows-x64/` |
| `make app-package` | macOS DMG/ZIP or Windows Setup EXE in `artifacts/` |
| `make cli-build` | CLI executable and `artifacts/tools/` |
| `python3 scripts/package-cli.py` | Standalone CLI ZIP in `artifacts/` |

Keep `tools/` beside the CLI executable. Complete packages must be built on their target platform. macOS DMG packaging requires a logged-in desktop session and Finder automation permission.

On Windows without GNU Make, use PowerShell:

```powershell
./scripts/desktop/build-windows.ps1
./scripts/desktop/build-windows.ps1 -Package
./scripts/desktop/build-windows.ps1 -Package -Cuda  # also build the CUDA 12.4 / 13.3 full installers
python scripts/package-cli.py
```

Model conversion is separate from app packaging. For compatible Kokoro model preparation, run `python scripts/prepare-kokoro-models.py --help` from the repository.

## Tests

```sh
pnpm --dir web exec playwright install chromium
make check
```

Use `make check-core` for Go formatting, static analysis and tests with the race detector, or `make check-web` for the frontend build and browser tests. Native installation and GPU inference also need testing on the target platform.

## Project layout

| Directory | Purpose |
| --- | --- |
| `cmd/` | CLI and local service entry points |
| `internal/` | Go service, split into packages by responsibility (see below) |
| `desktop/macos/`, `desktop/windows/` | Native app hosts |
| `web/src/` | Frontend application |
| `web/browser-tests/` | Browser tests |
| `scripts/` | Build and packaging tools |

### Architecture conventions

- Frontend dependencies flow `app → features → shared`; `shared` never imports feature modules.
- The Go service is split into packages by responsibility. Dependencies only point downward:

  | Layer | Packages | Responsibility |
  | --- | --- | --- |
  | Transport | `desktop`, `remote` | Local desktop server and RPC dispatch; remote HTTP API, async jobs and MCP |
  | Application | `workbench` | Projects, media, characters, models, runtime, generation and project archives |
  | Infrastructure | `engine`, `store`, `download`, `audio` | Inference process, state persistence, downloads and extraction, audio parsing and conversion |
  | Model | `schema`, `catalog` | Persisted structures and validation; model catalog and generation options |
  | Leaf | `msg`, `diag`, `platform` | Message codes, diagnostic logs, platform differences |

  Transport packages only decode requests and call public `Workbench` methods; they never touch its internal state. `testkit` is for tests only.
- Desktop calls run concurrently. `Workbench` serializes short read-validate-write transactions with an edit lock; conversion, downloads, inference and project import/export run without it. Only one background operation runs at a time.
- The model catalog, generation options and OmniVoice attributes are embedded in the Go service and imported by the UI. Keep `internal/catalog/*.json` and `web/src/shared/lib/*.json` identical (`engine.json` is used only by the service and build scripts and has no UI copy).
- Declare message codes in `internal/msg`, add them to `msg.All`, and provide copy in both UI languages.
- To upgrade audio.cpp, edit only `internal/catalog/engine.json`: `version` is the recommended release, `minimum` is the oldest runtime the request mapping and model packages support, plus the archive checksums. Runtime installs and the build scripts in `scripts/desktop/` read it. The installed runtime version is stored in the state; below `minimum` an upgrade is required, below `version` the UI offers an optional upgrade. Raise `minimum` only when the app actually depends on the newer runtime.
- On Windows, `-Package` builds the full CPU installer and the app-only `-update.exe`. Auto-update downloads only the latter, leaving `engine/` and its `yovoice-engine.json` (bundled runtime version and backend) untouched.

`go test` enforces the last three.

Public guides use English `*.md` and Chinese `*_zh.md` files. Keep both versions and their links in sync when changing user-facing behavior.

Release notes from v0.1.7 onward must include separate `### English` and `### 简体中文` sections in CHANGELOG.md. The release workflow checks both sections before building.
