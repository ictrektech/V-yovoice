# V-Voice VOS package

中文逐步操作手册：[VOS V-Voice 正式发布流程](../.agents/runbooks/vos-v-voice-release.md)。

The release contains one pull-mode package for six mutually exclusive profiles:

| Profile | Feishu sheet | Runtime |
|---|---|---|
| `amd` | `AMD_with_mxn100` | AMD64 CPU |
| `amd-cuda` | `AMD_with_cuda` | AMD64 CUDA |
| `arm` | `ARM_without_cuda` / `SOPHON_bm1688` | ARM64 CPU |
| `arm-cuda` | `ARM_with_cuda` | ARM64 CUDA |
| `l4t` | `l4t` | Jetson CUDA |
| `thor` | `thor_spark` | Thor CUDA |

Run `docker/build_image.sh --sheet <sheet>` on a matching build host. After every
required image and Feishu cell is published, run `ictrek.app/scripts/update_version.sh patch`
locally to trigger packaging and App Store publication.

The AMD CUDA image makes Python ONNX Runtime and sherpa-onnx share the provider
bridge shipped with sherpa-onnx. This prevents their different bridge versions
from hanging or crashing CUDA session creation in the same process. Verify
alternating Python ORT and sherpa CUDA inference on the target GPU before publishing.

Preview the selected build and publication plan with
`bash docker/build_image.sh --sheet l4t --dry-run`. This prints the target image,
build steps and Feishu sheets without downloading, building, pushing or writing
Feishu. It also works with `--build-only`, `--publish-only` and the other build
modes; local artifacts and wheel availability are not checked during preview.

ARM CUDA and Thor share the compiler-cache reference when their validated base
image is identical. Their runtime images and Feishu records remain separate;
the source archive and CUDA build arguments still participate in cache checks.

For frontend-only changes after the current day's full backend image is built,
use `docker/build_image.sh --sheet <sheet> --assets-only` with freshly built
`artifacts/web`. This preserves the validated inference runtime and refreshes only
the creation UI. It builds without publishing; verify the resulting image before
the usual `--publish-only` step. Use the normal full build for backend changes.

The narrowly scoped `--music-ui-only` variant also copies `vvoice/music.py` to
refresh effective input-limit metadata alongside the UI. It must only be used
when native adapters, admission logic, dependencies and binaries are unchanged;
verify its packaged Python hash, HTTP metadata, tests and UI before publishing.

Packaging resolves the current published V-Scheduler version, never a guessed
version. Its built-in shared model repository needs no separate Model Hub app.
Local packaging uses `GH_TOKEN`, then `GITHUB_TOKEN`, then the existing GitHub CLI
login (`gh auth login`) to query releases without anonymous API rate limits.
When the dependency repository is private, the existing
App Store credentials open the approved loopback SSH tunnel; the packager reads
the latest App Store record and confirms that its `app.tar.gz` exists and matches
the recorded size. The protocol minimum is still enforced. No cross-repository
GitHub token is required.

The Actions manual trigger runs a read-only dependency-access preflight without
building a package or publishing. Use it before a version bump when changing the
release connection. Only `vos-v-voice-v*` tags run the actual release. The tunnel
is closed on success and failure. A retry after GitHub publication reuses that
release's existing package for App Store publication rather than replacing it.

VOS 0.0.22 is a packaging-only endpoint migration: new installations prefer
`http://v-scheduler:6005` for the model repository and trusted bindings use
`http://v-scheduler:8080/scheduler/api/v1`. Existing model paths and explicit
repository settings are retained. All six profiles reuse the exact 0.0.21
native service images; inference code, dependencies and resource settings do not change.

If CI fails before the public version tag exists, commit the correction and use
`vos-release.yml`'s `workflow_dispatch` with `retry_version` equal to the current
`ictrek.app/VERSION`. This retries that unpublished version from the selected
commit without moving its original trigger tag. The guard refuses an existing
public version; leaving the input blank keeps the dependency-only preflight.
