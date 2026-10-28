# V-Voice VOS integration

The V-yovoice repository is the successor source repository for
`com.ictrek.v-voice`, not a second app installed alongside the same service.

The current runtime is ONNX / audio.cpp / soundfont only. PyTorch-native ACE-Step,
Stable Audio 3 and MusicGen models and their standalone music API are retired.
Existing weights and user data are not removed, and previous releases remain a
rollback option. GGUF music remains available in the music editor. Prepare models
on each feature page opens its relevant model controls without navigating away.
Existing ASR, translation, streaming, hotwords, speaker recognition, TTS,
discovery and management routes remain compatible. The original console remains
available alongside the voice-creation workbench.

## Acceptance gates

- Retained Python API tests pass without deleting existing coverage.
- The complete V-Voice 0.0.12 catalog is retained unchanged; creation model
  support includes every upstream model/precision, not a selected subset.
- Browser creation uses a real backend, not the upstream preview simulator.
- VOS-authenticated users have separate projects, voices and output files.
- Shared ONNX and GGUF models install through V-Scheduler's built-in model repository from ModelScope only;
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

For installation-time automatic admission, V-Voice advertises its versioned
binding endpoint in discovery. The same-VOS V-Scheduler application pushes the
app-scoped credentials and approved model/executor mappings after provisioning
its own resource policy. V-Voice checks the actual executor contracts before an
atomic private write, rejects old revisions, and hot-loads changes. See
[the exact handoff contract and 229 release gates](scheduler-auto-binding.md).
Discovery alone does not prove this handshake or resource approval succeeded.
The interface shows a waiting status while the binding is absent; management
remains accessible, inference does not bypass admission.

Existing administrator-provisioned deployments remain compatible with
`/data/scheduler.local.json` in mode `0600`; start from
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

Model management is also a main sidebar destination. Its speech tab retains all
legacy cards and their controls; its creator tab includes every upstream model
precision, music model and soundfont with V-Scheduler download/stop/verification
state. A ready shared repository cannot make its missing individual models ready.
Import-only variants are explicitly marked instead of offering a false download.

On a matching build host, run `bash docker/build_image.sh --sheet <sheet>` with
the same sheet names/options as the previous V-Voice release. It builds the
original service stage from the current source using the migrated profile
Dockerfiles, then adds the pinned audio.cpp runtime and Go/React workbench.
`--build-only` does not publish; `--publish-only` pushes the validated image and
records its `platform_X.Y.Z` tag in the canonical Feishu spreadsheet. Specify the
same `--version X.Y.Z` for both steps; the default build version is the next VOS patch.
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
GitHub Release or App Store records and fails if the required unified V-Scheduler
package cannot be verified. Separate Model Hub and V-Router applications are not
dependencies. The retained `MODEL_HUB_API_URL`, `MODEL_HUB_SHARED_MODELS_PATH` and
`/modelhub` mount are compatibility names for V-Scheduler's built-in repository
and existing shared files, not independent services. This does not authorize
modifying or releasing V-Scheduler.

## Public API and gateway discovery

Catalog browsing reads file metadata without scanning every installed weight.
The model-management API reports GGUF models as `verifying` until bounded background
checks finish; public discovery never advertises an unverified model. Native generation and
score rendering independently verify only the selected package before use;
verification honors cancellation and caches immutable-file results across users.
This keeps large shared catalogs from blocking the creator or legacy ASR UI.

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

## v0.3.0 私有旋律谱 RPC

下列调用均经带 VOS 身份认证的 `POST /studio-api/call`，不属于公开 OpenAI 语音协议。
排队调用必须携带稳定的 32 位十六进制 `requestId`，返回当前用户的任务 ID。

| method | data | 行为 |
| --- | --- | --- |
| `melody.plan` | YuE2 音乐作品快照 | 排队规划 ABC 旋律谱；执行时不覆盖排队后的正文编辑 |
| `melody.cover` | `{projectId, base64}` | 上传不超过 20 MiB 的歌曲，使用已安装的 SheetSage2 扒谱；音频最长 10 分钟 |
| `melody.listen` | `{abc}` | 使用已安装的音色库排队渲染试听，返回任务 ID |
| `melody.result` | `{id: 任务ID}` | 试听未获调度确认时返回 null；成功后返回 `{fileName}`，失败或取消返回错误 |
| `melody.inspect` / `melody.transform` | `{abc}` / `{abc, op, tempo}` | 校验或转换谱面，不加载推理模型 |
| `melody.dismiss` | `{id: 谱面结果ID}` | 丢弃当前用户尚未接收的谱面结果 |

辅助模型由服务端选择并固定到排队快照，客户端不能通过 `modelId` 自报预算。
规划、扒谱和试听均使用既有 Scheduler 执行器与停止核验流程，缺少批准映射时拒绝排队。
作品删除仍受排队输入保护。查询和取消沿用 `state.get`、`operation.cancel`；
ABC 结果通过用户状态发布，试听通过 `melody.result` 查询，音频下载仍需身份认证并等待调度确认。
SheetSage2 不会作为 TTS 暴露给标准语音发现接口。模型镜像发布与目标设备审批需另行完成，
加入模型目录不表示已下载或已批准。桌面 Ocho、任意路径导入、文件导出和命令执行不在 VOS 白名单中。


## 第三批：逐字歌词与数据库升级

`generation.lyricWords` 是经身份认证的时间戳元数据操作，参数为 `{id, words: [{word, start, end}]}`；
沿用每用户历史的所有权校验，范围必须落在该版本音频时长内。`voice.suggest` 接受 `{id}`，
只分析当前用户的参考录音并返回建议范围，不加载推理模型。

`generation.alignLyrics` 参数为 `{id, lines?: [{text, start, end}]}`，必须携带稳定 `requestId`。
服务端固定使用已安装且获审批的 `lyric-align-q8`，整首最长 20 分钟，按不超过 100 秒的人声片段处理；
由原有 Scheduler 队列执行，不能通过客户端 `modelId` 自报预算。状态仍通过 `state.get` 查询，
取消仍用 `operation.cancel`。同一版本的上一次对齐确认终态并停止后才能重试；
排队期间不允许修改歌词校准或删除输入。新时间戳在调度确认前不可见，失败或取消保留此前可见的校准；
已确认的重试结果不会被旧失败任务遮住。

状态库升级到版本 2，升级前会在用户目录留下 `yovoice.upgrade-v1-*.db` 快照；
旧代码不支持直接打开新版数据库，回滚代码时须使用升级前的数据库副本。
VOS 原有共享路径、历史保留和仅导入模型不变。Kokoro 在 VOS 中沿用镜像内的系统库，
桌面端才使用按模型下载的 wheel。新增模型仍需另行发布 ModelScope 镜像并在目标设备审批。
