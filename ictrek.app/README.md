# V-Voice VOS package

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

Packaging resolves the current published V-Scheduler version, never a guessed
version. Its built-in shared model repository needs no separate Model Hub app.
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
