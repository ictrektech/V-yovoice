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

For real speech development on the Orin / JetPack 6 host running V-Scheduler:

```bash
npm --prefix frontend ci  # first setup of the compatibility speech pages
make dev-browser
# The previous same-host command also works:
VITE_VOS_SPEECH_SERVICE_BASE=http://192.168.1.207:22700 make dev-browser
```

Open `http://192.168.1.207:5173`, replacing the IP with your development host's
LAN address. Vite listens on `0.0.0.0:5173` and forwards same-origin requests to
local Python speech and Go services on loopback ports 22700 and 7080. No VOS login
bridge is needed, and port 22700 does not need LAN exposure.

The launcher uses an already cached `v-voice:l4t_*` runtime image; select a cached
image with `VVOICE_DEV_IMAGE` if needed. It never pulls or rebuilds an image.
Current source is mounted read-only, and Go is compiled on startup. Restart the
command after backend changes; the frontend retains Vite hot reload. V-Voice need
not be installed in VOS. Weights are mounted read-only from the local Scheduler
container's `/data` host mount, without copying or downloading them again. Model
downloads still go through Scheduler's model repository API.

The first start registers an independent `com.ictrek.v-voice.dev` service identity
and executor through Scheduler's management API, retaining the local
`orin-voice-native-bounded-v1` calibration. Existing VOS app credentials and
executors are preserved. Every inference acquires and claims a permit and releases
it after native computation stops and weights unload. Resource shortages return
429. Kokoro supports at most 512 characters at speed 1; SenseVoice supports at most
20 seconds, 24 kHz, a 1 MiB request body, and no hotwords. CAM++ weights may appear
ready but this calibration does not approve its inference. GGUF creation and music
also require their own calibrations and approvals.

Data and private Scheduler configuration default to `/tmp/yovoice-dev-data`;
set `YOVOICE_DEV_DATA` to a persistent directory if desired. Submitter credentials
stay in a backend-only 0600 file and are reused on restart. `VVOICE_DEV_TOKEN` is a
separate browser development credential: custom values need at least 32 letters,
digits, underscores or hyphens. Production VOS authentication is unchanged.

Ctrl+C stops the development services. Occupied ports 5173, 7080 or 22700 cause a
clear startup error. For `Local compute resources are busy`, inspect Scheduler's
state and available memory: the speech budget is 2304 MiB plus the system safety
reserve, even when the GPU is idle.

On other development machines, use `VVOICE_DEV_SPEECH=off make dev-browser` for
Go and UI development without inference. To forward speech requests to an
**already running** remote V-Voice, use
`VVOICE_DEV_SPEECH=external VITE_VOS_SPEECH_SERVICE_BASE=http://<service-IP>:22700 make dev-browser`.
External mode does not grant local creation tasks scheduling approval.

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
