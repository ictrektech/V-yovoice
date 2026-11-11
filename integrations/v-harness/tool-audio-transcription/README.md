---
description: "Installable V-yovoice audio transcription tools, profile settings and verbatim transcript cards."
kind: "package-bundle"
---

# V-yovoice audio transcription

English | [中文](README.zh.md)

## Summary

Paste an MP3 into a normal Web or Desktop conversation and ask what it says. The agent calls V-yovoice on demand. A durable audio card after the closing answer provides playback, byte-range seeking and the complete original independently from assistant summaries. It supports multiple files, continued questions, explicit reprocessing and restored sessions. No local recognition model or plugin market is required.

## Install and configure

Use the prebuilt `ictrek-dsh-tool-audio-transcription-0.1.1.tgz` with v-harness **0.1.36** and DSH **0.2.1-rc.2 / 0.2.1-rc.5**. In **Plugins → Add plugin**, enter a tarball URL or absolute path readable by the Host. This is not an upload picker: a Mac path cannot name a file on a remote VOS Host. For VOS, copy the archive into the intended tenant's workspace and use its in-tenant path, for example `/home/admin/workspace/audio-plugin-acceptance/plugin.tgz`; the container's shared `/tmp` is not visible inside the tenant. Alternatively, enter the immutable release URL `https://github.com/ictrektech/V-yovoice/releases/download/harness-plugin-latest/audio-transcription.tgz`. Install into that tenant's profile, not the shared runtime.

After npm publication, the market can install `@ictrek/dsh-tool-audio-transcription` from an accessible registry.

CLI example, executed as the profile owner on the Host:

```sh
dsh plugin --profile web add /absolute/host/path/ictrek-dsh-tool-audio-transcription-0.1.1.tgz
```

Enable the installed bundle. Open its configuration, save the V-yovoice **service root URL** (without `/v1`), select **Check connection / list models**, choose a ready ASR model and save again. Use an address reachable from the Host, including from its container. Desktop uses its managed Desktop profile: install through its Plugins page, not an unrelated `web` profile. Follow any restart or refresh notice from the Host. Unconfigured installations remain loadable and report configuration requirements when transcription is attempted.

Settings persist in the current profile. The service must expose `/api/v1/models`, `/api/v1/models/{key}/input-limits`, and `/v1/audio/transcriptions`. This integration targets the VOS V-yovoice ASR service, not the Desktop/CLI synthesis-only API. Model discovery crosses the authenticated DSH Remote connection; only the Host accesses V-yovoice. A VOS tenant's network policy must permit that service address; a service reachable outside the tenant can still be blocked inside it. The plugin does not change gateway settings or network isolation. No credentials are embedded in the archive.

When input limits advertise `/v1/audio/transcriptions/full`, the Host sends the original file to that endpoint and accepts only a complete, matching response. V-yovoice owns conversion and segmentation. Older services continue using the single-segment endpoint and its model limits; the plugin does not silently transcode audio.

## Use

Attach one or more audio files and ask for transcription, a summary, or a specific answer. Multiple files are selected individually. The turn card sits after the final assistant answer and shows one player per uploaded file; playback is user-initiated. Its central play control, elapsed and remaining time, and waveform seek bar follow the host light or dark theme. The waveform supports click, drag, hover time, and keyboard seeking. Sources up to 20 MiB and 10 minutes are decoded locally into real peaks; larger sources, decode failures, or restricted hosts use the high-contrast progress bar instead. Peaks are cached in memory for the current browser session and never enter the conversation log. Short originals are shown directly, while long originals expand from a preview. A copy action preserves the complete text. Empty recognition is reported explicitly. If the browser or attachment provider cannot stream the source, the saved original and explicit reason remain visible. If no final answer exists, the same card remains after the stopped Turn. Desktop file references must be explicitly supplied by the user in the same conversation and remain self-contained and readable through the current execution filesystem.

The tools are `list_audio_files`, `list_audio_models`, `transcribe_audio` and `read_audio_transcript`. For uploaded audio, the agent lists the exact attachment identity before starting recognition so the turn card can display the player while transcription is running. `transcribe_audio` accepts `attachment_id` or `file_path`, never both. `reprocess: true` requests fresh recognition. Older single-segment services reuse matching conversation results unless reprocessing; full-file services cannot expose the current model revision before transcription, so recognition is repeated and prior originals remain readable with `read_audio_transcript`. A failed reprocessing does not replace a successful earlier result; the card keeps and labels the previous successful original. Audio and transcripts persist with the conversation and the existing attachment retention policy.

Playback uses a plugin-owned authenticated route. It validates that the requested attachment belongs to the named loaded session, streams bounded byte ranges, and never exposes an arbitrary host path. The source is available only while the attachment is retained by the host.

## Configuration

| Field | Initial value | Behavior |
|---|---|---|
| `baseUrl` | empty | Host-reachable V-yovoice root URL, without credentials, query or fragment. |
| `model` | empty | Explicit ASR model key; no automatic model substitution. |
| `requestTimeoutMs` | 1860000 | Acquisition/inference deadline and each service request deadline, including response reading. Existing profile overrides remain in effect. |
| `maxUploadBytes` | 209715200 | Local acquisition cap; the applicable service upload limit also applies. |
| `maxResponseBytes` | 16777216 | Complete service JSON response cap. |
| `pageCharacters` | 12000 | Maximum UTF-16 characters returned to the model in one transcript window. |

`audioTranscription.catalog()` returns the configured `selected` model and `models`, whose entries contain `key`, `name`, and `ready`.

All fields can be edited on the plugin page. CLI users can set them under the `tool-audio-transcription` row's `config` in their profile patch. Audio decoding, duration limits and scheduler admission belong to V-yovoice. Oversized or unsupported inputs fail explicitly; no client-side splitting or silent truncation is performed. Cancellation or plugin unload stops local requests; a lost connection does not establish whether the remote inference stopped.

## Build and verify

The npm package name is `@ictrek/dsh-tool-audio-transcription`; publication requires company control of the npm account or organization and publishing access. If the old `@deepseek-ai/dsh-tool-audio-transcription` package is installed, record the service address and model, disable and remove the old package, then install the new package and verify the settings. Do not enable both packages. Session data is separate from the plugin package; do not delete sessions or the workspace.

The plugin source lives in V-yovoice. Build it against an explicit, clean v-harness checkout:

```sh
V_HARNESS_REPO=/absolute/path/to/v-harness \
  pnpm --dir integrations/v-harness/tool-audio-transcription build:release
```

The script checks the pinned host revision, temporarily installs this package into that v-harness workspace, runs the plugin tests, lint, Host/Client compilation, `build:artifacts` and `build:check`, then writes the `.tgz`, SHA256 sidecar and `compatibility.json` under the ignored `dist/dsh-plugin/` directory. It verifies that the archive contains no workspace specifications, source entries, install scripts or local build paths. Publish those three files to the dedicated `harness-plugin-vX.Y.Z` release. Installation must be tested outside the source workspace using the exact published archive.


## Model Experience

### Audio tools and original text

#### What the model sees

The plugin adds four tool declarations and an audio-use prompt section. Uploaded audio bytes never enter the language-model request. A successful transcription logs its full text as result metadata; the model receives a bounded original-text window with total length and the next offset. `read_audio_transcript` reads further windows without another ASR call. The original is untrusted source material, not instructions. Assistant summaries consume only text actually read.

#### Token effect

Tool declarations and returned text windows consume context tokens. Complete originals remain available to the result card without being inserted wholesale into each model request.

#### KV Cache effect

Enabling or disabling the plugin changes tool/prompt declarations. Recognized text enters ordinary logged tool results and may affect subsequent requests.


## Known Limitations and Deferred Work

- MP3 is the required acceptance format; browser playback and V-yovoice decoding support for other formats depends on the configured host and service. Full-file recordings must fit the service's total limits; older single-segment services enforce their model limits directly. No streaming recognition, client-side chunking, speech synthesis or environmental-sound analysis is included. A Host stopped by timeout may leave remote work running; check the service before retrying. Market listing and public registry publication are separate follow-up work.
