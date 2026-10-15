# V-Voice VOS integration

The V-yovoice repository is the successor source repository for
`com.ictrek.v-voice`, not a second app installed alongside the same service.
Existing ASR, translation, streaming, hotwords, speaker recognition, TTS,
discovery and management routes remain compatible. The original console remains
available alongside the voice-creation workbench.

## Acceptance gates

- Retained Python API tests pass without deleting existing coverage.
- The complete V-Voice 0.0.12 catalog is retained unchanged; creation model
  support includes every upstream model/precision, not a selected subset.
- Browser creation uses a real backend, not the upstream preview simulator.
- VOS-authenticated users have separate projects, voices and output files.
- Shared ONNX and GGUF models install through Model Hub from ModelScope only;
  consumers use its read-only export, without duplicating weights per user.
- V-Router discovery remains compatible; unknown/new models are not implicitly
  approved for scheduling.
- V-Scheduler admission follows its current v1 contract, never fails open, never
  charges one computation twice, and does not treat an async receipt or client
  disconnect as stop evidence.
- All six existing platform profiles, image publication, Feishu records,
  versioning, GitHub release, VOS App Store publication and VAI gitlink are checked
  before declaring a release complete.

## Scheduling contract sources

Read together before changing execution entry points:

- https://github.com/ictrektech/V-Scheduler/blob/main/docs/application-integration.md
- https://github.com/ictrektech/V-Scheduler/blob/main/docs/integration-standard.md
- https://github.com/ictrektech/V-Scheduler/blob/main/api/openapi-v1.json
- https://github.com/ictrektech/V-Router/blob/main/docs/resource-scheduling.md

Synchronous/streaming calls through V-Router use its approved permit ownership.
Direct local calls must enter the same admission boundary, not bypass it or obtain
a second full reservation. Native asynchronous creation requires durable business
jobs/outbox and approved executor start/inspect/cancel, fence, lease watchdog and
confirmed-stop semantics. Scheduler task submission contains no prompts, media,
arbitrary paths or credentials. Inputs and outputs remain owned by V-Voice.

Production enablement needs per-node approved executors and fixed measured
resource templates, application-scoped service credentials in private storage,
and the V-Router per-model approval. Package dependencies alone do not supply
these. Do not claim W2 recovery or actual-node conformance from mocked tests.

## Private configuration and rollback

Provision `/data/scheduler.local.json` with mode `0600`; start from
`config/scheduler.example.json` but replace all placeholders with this app's
approved credentials and per-node executor IDs. `models` maps legacy native IDs
and `audiocpp-...` API IDs to `model.infer` executors; bare creative model IDs map
to `voice.generate` executors. Both must belong to the V-Voice submitter app ID.
`gateway_executors` separately approves V-Router-owned synchronous executors,
which the Scheduler principal must explicitly grant in `permit_executors`.
`upstream_url` must match the real V-Router upstream base URL exactly. Combined
ASR/speaker calls need an explicit `secondary_models` entry and a measured fixed
template covering both models.

The Agent binds `voice.generate` to the V-Voice base URL's `/scheduler` execution
adapter with the dedicated executor credential. Its `start/inspect/cancel` URLs
are `/scheduler/executions/{attempt}/{action}`; parameters contain only `job_id`.
Set the Agent executor `url` to the V-Voice base URL, without `/scheduler`;
the Agent appends the execution route itself.
Unknown restart attempts retain reservations and require stop reconciliation;
automatic retry/W2 recovery is not claimed. Queued request snapshots and outputs
stay in V-Voice storage, never in Scheduler parameters.

The app ID, public port, legacy routes, speaker/hotword files and `/data` mount
are retained. Creative user data lives separately in `/data/studio`. Rolling
back to V-Voice 0.0.12 leaves that directory untouched. Do not delete old data or
install both app packages against the same port/app ID simultaneously.

## Upstream maintenance

See `UPSTREM` for the fork origin and merge baseline. Retain upstream notices and
desktop sources; VOS-specific adapters live separately so future merges stay
bounded. Model licenses remain independent of the application source license.

## Brand and build migration

The installed application is named **V-Voice**, retaining `com.ictrek.v-voice`,
port 22700, original icon, all six profiles and the `v-voice` registry repository.
The VOS workbench title/favicon and the retained service console use that same
brand. Upstream names in internal module/message identifiers and attribution
remain intact for merge compatibility; they are not a separate VOS app identity.

The creator's language selector defaults to **Follow VOS**. It subscribes before
reading the platform snapshot so a delayed snapshot cannot overwrite a newer
language event. English, Simplified Chinese and Traditional Chinese are available
in the creator and the retained console. An explicit creator override is stored in this app only; changing
language does not reload or discard the current draft. The retained service
console keeps its existing English/Simplified Chinese/Traditional Chinese support.

The creator sidebar has a dedicated **API documentation** page, reusing the full
service guide in an isolated same-origin view. It covers ASR, streaming, TTS,
hotwords, speaker APIs, model discovery, creative speech extensions and Scheduler
admission. The guide opens in the creator's current language and includes its own
three-language selector. Technical paths, parameter names and executable examples
are not translated. Raw `/openapi.json` remains available for machine clients.

On a matching build host, run `bash docker/build_image.sh --sheet <sheet>` with
the same sheet names/options as the previous V-Voice release. It builds the
original service stage from the current source using the migrated profile
Dockerfiles, then adds the pinned audio.cpp runtime and Go/React workbench.
`--build-only` does not publish; `--publish-only` pushes the validated image and
records its fixed `platform_YYYYMMDD` tag in the canonical Feishu spreadsheet.
Intermediate base images are local build artifacts, never a second publication.
Same-architecture hosts may reuse the prepared Go/web artifacts and pinned source
archive via `--reuse-prepared-artifacts`; synchronize current source first. This
does not reuse historical service images or skip native image compilation.

For staged model mirroring, `scripts/publish_creative_models.py` verifies each
download against the upstream catalog. After all batches are published, run it
with `--downloadable-only --audit-only` for the anonymous 41-file SHA256/size gate.
Adding `--publish` finalizes the complete source/license index without uploading
weights again. The two upstream import-only variants remain supported but are not
misrepresented as publicly downloadable files.

After code delivery and all affected images/Feishu records are verified, run the
migrated `ictrek.app/scripts/update_version.sh` **locally**. It rejects a dirty
worktree or either existing release tag, pushes only `vos-v-voice-v...`, and lets
GitHub Actions produce the public release/package and publish to VOS App Store.
Do not call the packaging script manually as a substitute for that release gate.
Packaging resolves dependency requirements from their actual latest published
GitHub VOS packages and fails if unavailable or below the required protocol floor
(Model Hub 0.0.94, V-Router 0.0.44, V-Scheduler 0.0.15). This does not authorize
modifying or releasing those applications.

## Public API and gateway discovery

`GET /openapi.json` documents the public V-Voice HTTP contract. Existing
`/v1/audio/transcriptions`, `/v1/audio/translations`, streaming and speaker
interfaces are retained. Standard `POST /v1/audio/speech` accepts `model`,
`input`, `voice`, `response_format`, `speed` and `language` and returns binary
audio. `GET /v1/audio/voices?model=...` returns actual built-in voice IDs.

`GET /api/v1/discovery` and `/v1/models` only advertise ready, verified models;
the existing V-Router poller discovers new creative models without a hardcoded
model list. Use `/api/v1/models` on V-Router for endpoint/capability filtering,
then pass its qualified ID (for example `v-voice/audiocpp-index-2.5-q8`) to the
same standard speech endpoint on V-Router. Gateway prefix rewriting preserves
extension fields and audio responses. Discovery never grants resource admission;
each newly installed model still needs an approved Scheduler template/policy.

Creative speech extensions are **not OpenAI-standard parameters**:

- `reference_audio`: base64-encoded audio bytes, never a server path; select a
  model declaring `voice_cloning`. `reference_text` supplies its transcript;
  OmniVoice and Breeze cloning require it.
- `voice_description`: design/instruction text; requires `voice_design` or
  `voice_instruction`. Qwen3 VoiceDesign requires a non-empty instruction;
  OmniVoice accepts its upstream attribute vocabulary, not arbitrary prose.
- `emotion_text`, `emotion_strength` (0–1): IndexTTS `emotion_control` models.

Capabilities reflect model variants: Qwen3 Base supports cloning, CustomVoice
has named speakers/instructions, and VoiceDesign supports design. Kokoro has
built-in voices, not cloning. Native model-specific input/length/speed limits
still apply and return validation errors. Private projects/reference libraries
are never included in public model discovery or the shared speech API.
