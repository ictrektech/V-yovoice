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
