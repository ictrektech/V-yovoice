# V-yovoice image smoke

Run the check on the matching build host after `--build-only` and before pushing the candidate image. It starts one temporary container with `docker run --rm`; it does not mount data, publish ports, execute inference, or retain a container.

Pin the image catalog to the source used for the build:

```bash
EXPECTED_CATALOG_SHA256="$(
  python3 -c 'import hashlib, pathlib; print(hashlib.sha256(pathlib.Path("internal/catalog/catalog.json").read_bytes()).hexdigest())'
)"
```

Use these mappings:

| Profile | Build host | Image tag | Acceleration contract |
| --- | --- | --- | --- |
| `amd-cuda` | `czy@10.144.144.232` | `amd_cu128_X.Y.Z` | Sherpa CUDA 12; Python ONNXRuntime CPU bridge; audio.cpp linked to CUDA |
| `l4t` | `czy@192.168.1.207` | `l4t_X.Y.Z` | Sherpa CUDA 12; ONNXRuntime CUDA; audio.cpp linked to CUDA |
| `thor` | `czy@192.168.1.229` | `thor_X.Y.Z` | Sherpa CUDA 13; ONNXRuntime CUDA; audio.cpp linked to CUDA |

```bash
python3 .agents/skills/vos-preflight-package/scripts/vos_image_smoke.py \
  --ssh czy@10.144.144.232 \
  --profile amd-cuda \
  --image "swr.cn-southwest-2.myhuaweicloud.com/ictrek/v-voice:amd_cu128_${RELEASE_VERSION}" \
  --expected-catalog-sha256 "$EXPECTED_CATALOG_SHA256"

python3 .agents/skills/vos-preflight-package/scripts/vos_image_smoke.py \
  --ssh czy@192.168.1.207 \
  --profile l4t \
  --image "swr.cn-southwest-2.myhuaweicloud.com/ictrek/v-voice:l4t_${RELEASE_VERSION}" \
  --expected-catalog-sha256 "$EXPECTED_CATALOG_SHA256"

python3 .agents/skills/vos-preflight-package/scripts/vos_image_smoke.py \
  --ssh czy@192.168.1.229 \
  --profile thor \
  --image "swr.cn-southwest-2.myhuaweicloud.com/ictrek/v-voice:thor_${RELEASE_VERSION}" \
  --expected-catalog-sha256 "$EXPECTED_CATALOG_SHA256"
```

The check fails unless it confirms:

- the image architecture matches the profile
- required workbench, audio.cpp, frontend, and catalog files exist
- forbidden PyTorch-family packages are absent
- audio.cpp resolves both `libcuda.so` and `libcudart.so`
- ONNX and Sherpa providers match the profile's acceleration contract
- the catalog contains unique, non-empty model IDs and matches the source SHA256

`--expected-catalog-sha256` is optional for checking an older image with no matching local source. For a release candidate built from the current checkout, always pass it so all three profiles must contain the same catalog.

Only after all applicable checks pass should the preflight candidate be pushed. Use `scripts/package.py --image ...` overrides for the target profiles when creating the candidate package, so candidate tags do not need to be written to Feishu. Feishu and `--publish-only` remain part of the formal publication decision.
