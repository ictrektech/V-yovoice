---
description: "Installable V-yovoice DSH plugin with composer dictation, transcription, text-to-speech, settings and durable audio cards."
kind: "package-bundle"
---

# V-yovoice DSH plugin

English | [中文](README.zh.md)

## Summary

This is the single V-yovoice installation package for DSH. It provides composer dictation, the proven audio transcription flow and text-to-speech through V-Voice's public API, on the shared capability, operation, artifact, session-restoration and playback base. Score and music modules will be added to the same plugin rather than split into separate installs.

Paste an MP3 into a normal conversation and ask what it says. The agent calls V-yovoice on demand. A durable audio card after the closing answer provides playback, byte-range seeking and the complete original independently from assistant summaries. It supports multiple files, continued questions, explicit reprocessing and restored sessions.

## Install and configure

Use the prebuilt `ictrek-dsh-tool-v-yovoice-0.4.0.tgz` with v-harness **0.2.2-rc.3.vos.09** and DSH **0.2.2-rc.3**; the declared range also retains the previously tested DSH 0.2.2-rc.2 compatibility. In **Plugins → Add plugin**, enter a tarball URL or absolute path readable by the Host. This is not an upload picker: a Mac path cannot name a file on a remote VOS Host. For VOS, copy the archive into the intended tenant's workspace and use its in-tenant path; the container's shared `/tmp` is not visible inside the tenant. Install into that tenant's profile, not the shared runtime.

The versioned download is `https://github.com/ictrektech/V-yovoice/releases/download/harness-plugin-v0.4.0/ictrek-dsh-tool-v-yovoice-0.4.0.tgz`; check `compatibility.json` before upgrading.

After npm publication, the market can install `@ictrek/dsh-tool-v-yovoice` from an accessible registry.

CLI example, executed as the profile owner on the Host:

```sh
dsh plugin --profile web add /absolute/host/path/ictrek-dsh-tool-v-yovoice-0.4.0.tgz
```

Enable the installed bundle. Open its configuration, save the V-yovoice **service root URL** (without `/v1`), select **Check connection / list models**, choose a ready ASR model, a ready TTS model and its default voice, then save again. Use an address reachable from the Host, including from its container. Desktop uses its managed Desktop profile: install through its Plugins page, not an unrelated `web` profile. Follow any restart or refresh notice from the Host. Unconfigured installations remain loadable and report configuration requirements when transcription, dictation or speech is attempted.

Settings persist in the current profile. The service must expose `/api/v1/models`, `/api/v1/models/{key}/input-limits`, `/v1/audio/transcriptions`, `/v1/audio/speech`, and `/v1/audio/voices`. This integration targets the VOS V-yovoice service, not the Desktop/CLI synthesis-only API. Model discovery crosses the authenticated DSH Remote connection; only the Host accesses V-yovoice. A VOS tenant's network policy must permit that service address; a service reachable outside the tenant can still be blocked inside it. The plugin does not change gateway settings or network isolation. No credentials are embedded in the archive.

When input limits advertise `/v1/audio/transcriptions/full`, the Host sends the original file to that endpoint and accepts only a complete, matching response. V-yovoice owns conversion and segmentation. Older services continue using the single-segment endpoint and its model limits; the plugin does not silently transcode audio.

## Use

Click the microphone after the model selector to dictate into the current unsent draft. Click it again to start capture, use the expanded toolbar to cancel or stop, and wait for recognition before the text is inserted at the cursor where recording started. Recognition does not send the message. If the draft or its reference chips changed while recognition was running, the transcript stays in the toolbar and can be inserted explicitly at the current cursor. Cancel, Escape, leaving the page or switching Sessions discards capture; the configured maximum duration stops recording automatically. The browser requests the system-default microphone and keeps audio transient: it is sent only to V-yovoice for recognition and is not saved as a conversation attachment. Do not enable DSH's experimental voice-input bundle with this plugin because both occupy the same composer activity seat.

Attach one or more audio files and ask for transcription, a summary, or a specific answer. Multiple files are selected individually. The turn card sits after the final assistant answer and shows one player per uploaded file; playback is user-initiated. Its central play control, elapsed and remaining time, and waveform seek bar follow the host light or dark theme. The waveform supports click, drag, hover time, and keyboard seeking. Sources up to 20 MiB and 10 minutes are decoded locally into real peaks; larger sources, decode failures, or restricted hosts use the high-contrast progress bar instead. Peaks are cached in memory for the current browser session and never enter the conversation log. Short originals are shown directly, while long originals expand from a preview. A copy action preserves the complete text. Empty recognition is reported explicitly. If the browser or attachment provider cannot stream the source, the saved original and explicit reason remain visible. If no final answer exists, the same card remains after the stopped Turn. Desktop file references must be explicitly supplied by the user in the same conversation and remain self-contained and readable through the current execution filesystem.

The tools are `list_audio_files`, `list_audio_models`, `transcribe_audio` and `read_audio_transcript`. For uploaded audio, the agent lists the exact attachment identity before starting recognition so the turn card can display the player while transcription is running. `transcribe_audio` accepts `attachment_id` or `file_path`, never both. `reprocess: true` requests fresh recognition. Older single-segment services reuse matching conversation results unless reprocessing; full-file services cannot expose the current model revision before transcription, so recognition is repeated and prior originals remain readable with `read_audio_transcript`. A failed reprocessing does not replace a successful earlier result; the card keeps and labels the previous successful original. Audio and transcripts persist with the conversation and the existing attachment retention policy.

Playback uses a plugin-owned authenticated route. It validates that the requested attachment belongs to the named loaded session, streams bounded byte ranges, and never exposes an arbitrary host path. The source is available only while the attachment is retained by the host.

For speech generation, ask the agent to read supplied text aloud. It calls `yovoice_speak` with the exact text, then saves the WAV as a conversation attachment and renders a playback card. A successful result includes the requested text, model and voice. The sound is not autoplayed. The plugin uses the configured TTS model; a request may use another advertised voice for that model. `yovoice_voices` returns the voice IDs and language labels when the user asks about voices or requests an unavailable one. Voice design and emotion parameters are accepted only for models that advertise those capabilities.

## Configuration

| Field | Initial value | Behavior |
|---|---|---|
| `baseUrl` | empty | Host-reachable V-yovoice root URL, without credentials, query or fragment. |
| `model` | empty | Explicit ASR model key; no automatic model substitution. |
| `speechModel` | empty | Explicit TTS model key; no automatic model substitution. |
| `speechVoice` | empty | Default advertised voice ID for the selected TTS model. |
| `requestTimeoutMs` | 1860000 | Acquisition/inference deadline and each service request deadline, including response reading. Existing profile overrides remain in effect. |
| `maxUploadBytes` | 209715200 | Local acquisition cap; the applicable service upload limit also applies. |
| `maxResponseBytes` | 16777216 | Complete service JSON response cap. |
| `maxSpeechBytes` | 268435456 | Maximum generated WAV size accepted for one speech request. |
| `pageCharacters` | 12000 | Maximum UTF-16 characters returned to the model in one transcript window. |
| `maxDictationSeconds` | 120 | Maximum microphone recording duration for composer dictation, from 1 to 600 seconds. The byte bound is derived from 16 kHz mono PCM16 WAV and `maxUploadBytes`; the service's calibrated input limit still applies. |

`audioTranscription.catalog()` returns the configured ASR `selected` model and `models`, plus a `speech` catalogue with the configured TTS model, default voice and available voices. ASR entries contain `key`, `name`, and `ready`; speech entries also expose languages and capabilities.

All fields can be edited on the plugin page. CLI users can set them under the `tool-audio-transcription` row's `config` in their profile patch. The package keeps that Loader id and settings key so existing profiles need no re-entry. Audio decoding, duration limits and scheduler admission belong to V-yovoice. Oversized or unsupported inputs fail explicitly; no client-side splitting or silent truncation is performed. Cancellation or plugin unload stops local requests; a lost connection does not establish whether the remote inference stopped.

## Build and verify

The npm package name is `@ictrek/dsh-tool-v-yovoice`; publication requires company control of the npm account or organization and publishing access. If either old transcription package is installed, disable and remove it before installing this package. This release keeps reading the legacy Loader id, so existing settings are preserved. Do not enable both packages. Session data is separate from the plugin package; do not delete sessions or the workspace.

The plugin source lives in V-yovoice. Build it against an explicit, clean v-harness checkout:

```sh
V_HARNESS_REPO=/absolute/path/to/v-harness \
  pnpm --dir integrations/v-harness/tool-v-yovoice build:release
```

The script checks the pinned host revision, temporarily installs this package into that v-harness workspace, runs the plugin tests, lint, Host/Client compilation, `build:artifacts` and `build:check`, then writes the `.tgz`, SHA256 sidecar and `compatibility.json` under the ignored `dist/dsh-plugin/` directory. It verifies that the archive contains no workspace specifications, source entries, install scripts or local build paths. Publish those three files to the dedicated `harness-plugin-vX.Y.Z` release. Installation must be tested outside the source workspace using the exact published archive.

The pinned 0.2.2-rc.3 host source is checked against the exact reviewed aggregate-test baseline. The script accepts only matching pre-existing TypeScript errors and records the result in `compatibility.json`; additional errors or other build failures stop the release.


## Model Experience

### Audio tools and original text

#### What the model sees

The plugin adds six tool declarations and audio-use prompt sections. Composer dictation adds no tool declaration: its recognized text becomes model-visible only if the user sends the resulting draft. Uploaded audio bytes never enter the language-model request. A successful transcription logs its full text as result metadata; the model receives a bounded original-text window with total length and the next offset. `read_audio_transcript` reads further windows without another ASR call. Generated speech is stored as a durable attachment and is never inserted into the model request as audio bytes. The original is untrusted source material, not instructions. Assistant summaries consume only text actually read.

#### Token effect

Tool declarations and returned text windows consume context tokens. Complete originals remain available to the result card without being inserted wholesale into each model request.

#### KV Cache effect

Enabling or disabling the plugin changes tool/prompt declarations. Recognized text enters ordinary logged tool results and may affect subsequent requests.


## Known Limitations and Deferred Work

- MP3 is the required transcription acceptance format; browser playback and V-yovoice decoding support for other formats depends on the configured host and service. Dictation currently produces final text after recording stops; streaming captions, hold-to-talk/shortcut capture, automatic send, wake words and microphone-device selection are not included. Full-file recordings must fit the service's total limits; older single-segment services enforce their model limits directly. Speech generation currently uses public built-in voices only; reference-voice import, score, music and environmental-sound analysis are not included. A Host stopped by timeout may leave remote work running; check the service before retrying. See the [design document](https://github.com/ictrektech/V-yovoice/blob/main/integrations/v-harness/v-yovoice-plugin-design.md) for later modules and authorization boundaries.
