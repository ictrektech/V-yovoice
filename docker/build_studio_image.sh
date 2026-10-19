#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
registry="${REGISTRY:-swr.cn-southwest-2.myhuaweicloud.com/ictrek}"
build_root="${VVOICE_BUILD_ROOT:-${HOME}/dev/build/v-yovoice}"
artifacts="${build_root}/artifacts"
sheet=""; mode=full
prepare=true
while [[ $# -gt 0 ]]; do
  case "$1" in
    --sheet) sheet="$2"; shift 2 ;;
    --build-only) mode=build; shift ;;
    --publish-only) mode=publish; shift ;;
    --prepare-only) mode=prepare; shift ;;
    --reuse-prepared-artifacts) prepare=false; shift ;;
    *) echo "Usage: $0 --sheet <sheet> [--build-only|--publish-only|--prepare-only]" >&2; exit 1 ;;
  esac
done
case "$(uname -m)" in x86_64) arch=amd64 ;; aarch64|arm64) arch=arm64 ;; *) exit 1 ;; esac
cuda=OFF
backend=cpu
case "$sheet" in
  AMD_with_mxn100) [[ "$arch" == amd64 ]]; prefix=amd ;;
  AMD_with_cuda) [[ "$arch" == amd64 ]]; prefix=amd_cu128; cuda=ON ;;
  ARM_without_cuda|SOPHON_bm1688) [[ "$arch" == arm64 ]]; prefix=arm ;;
  ARM_with_cuda) [[ "$arch" == arm64 ]]; prefix=arm_cu130; cuda=ON ;;
  l4t) [[ "$arch" == arm64 ]]; prefix=l4t; cuda=ON ;;
  thor_spark) [[ "$arch" == arm64 ]]; prefix=thor; cuda=ON ;;
  *) echo "Explicit supported --sheet required" >&2; exit 1 ;;
esac
tag="${prefix}_$(date +%Y%m%d)"
image="${registry}/v-voice:${tag}"
if [[ "$prepare" == true && ( "$mode" == prepare || "$mode" == full || "$mode" == build ) ]]; then
  mkdir -p "$build_root/source" "$artifacts/linux-${arch}" "$build_root/sources"
  rsync -a --exclude=.git --exclude=node_modules --exclude=dist --exclude=__pycache__ "$root/" "$build_root/source/"
  cd "$build_root/source"
  GOCACHE="$build_root/go-cache" GOPROXY="${GOPROXY:-https://goproxy.cn,direct}" CGO_ENABLED=0 \
    go build -trimpath -o "$artifacts/linux-${arch}/vvoice-studio" ./cmd/vvoice-studio
  npx --yes pnpm@9.15.2 --dir web install --frozen-lockfile
  VITE_VOS=true npx --yes pnpm@9.15.2 --dir web run build
  mkdir -p "$artifacts/web"
  rsync -a web/dist/ "$artifacts/web/"
  archive="$build_root/sources/audio.cpp-v0.9.1.tar.gz"
  if [[ ! -f "$archive" ]]; then
    curl -fL --retry 4 --connect-timeout 15 --max-time 900 \
      https://codeload.github.com/0xShug0/audio.cpp/tar.gz/refs/tags/v0.9.1 -o "$archive.partial"
    mv "$archive.partial" "$archive"
  fi
  echo "20f589b7f891eee1e9d35d1fcea5382c925cf3413f4db5ba71d70cd9a991c938  $archive" | sha256sum -c -
fi
if [[ "$mode" == prepare ]]; then exit 0; fi
if [[ "$mode" == full || "$mode" == build ]]; then
  test -s "$artifacts/linux-${arch}/vvoice-studio"
  test -s "$artifacts/web/index.html"
  echo "20f589b7f891eee1e9d35d1fcea5382c925cf3413f4db5ba71d70cd9a991c938  $build_root/sources/audio.cpp-v0.9.1.tar.gz" | sha256sum -c -
  mkdir -p "$build_root/source"
  rsync -a --exclude=.git --exclude=node_modules --exclude=dist --exclude=__pycache__ "$root/" "$build_root/source/"
  if [[ "$cuda" == ON ]]; then backend=cuda; fi
  # 原 V-Voice 的六套构建配置继续从当前源码生成基础服务，不依赖历史成品镜像。
  cd "$build_root/source"
  base="v-voice-legacy-build:${prefix}"
  compiler_cache=""
  # 编译器快照只按平台基础镜像标识隔离；Python/Go 改动不应重编译未变的 C++ 内核。
  # 核对基础层前缀后才复用旧工具链，最终服务仍从当前源码重新构建。
  if [[ "$sheet" != AMD_with_cuda ]]; then
    case "$sheet" in
      AMD_with_mxn100) platform_base="${registry}/python:amd_3.12-slim" ;;
      ARM_without_cuda|SOPHON_bm1688) platform_base="${registry}/python:arm_3.12-slim" ;;
      l4t) platform_base="${registry}/pytorch_py312:jet_2.7.0" ;;
      *) platform_base="${registry}/nvidia-pytorch:arm_25.08-py3" ;;
    esac
    docker pull "$platform_base"
    platform_id="$(docker image inspect --format '{{.Id}}' "$platform_base")"
    compiler_prefix="$prefix"
    # 两套 ARM CUDA 配置基础镜像和编译参数相同，复用既有 Thor 别名，避免重复编译。
    case "$sheet" in ARM_with_cuda|thor_spark) compiler_prefix=thor ;; esac
    compiler_cache="v-voice-native-compiler:${compiler_prefix}-${platform_id#sha256:}"
    if ! docker image inspect "$compiler_cache" >/dev/null 2>&1 && docker image inspect "$base" >/dev/null 2>&1; then
      docker image inspect "$platform_base" "$base" > "$build_root/sources/compiler-layers-${prefix}.json"
      if python3 - "$build_root/sources/compiler-layers-${prefix}.json" <<'PY'
import json,sys
root, previous = json.load(open(sys.argv[1]))
layers = root['RootFS']['Layers']
raise SystemExit(0 if previous['RootFS']['Layers'][:len(layers)] == layers else 1)
PY
      then docker tag "$base" "$compiler_cache"; fi
    fi
  fi
  REGISTRY="$registry" VVOICE_LEGACY_STAGE=1 bash docker/build_legacy_image.sh --sheet "$sheet" --build-only
  docker tag "$image" "$base"
  compiler="$compiler_cache"
  if [[ -n "$compiler_cache" ]] && ! docker image inspect "$compiler_cache" >/dev/null 2>&1; then docker tag "$base" "$compiler_cache"; fi
  if [[ "$sheet" == AMD_with_cuda ]]; then compiler="${registry}/nvidia-cuda:amd_12.8.1-cudnn-devel-ubuntu22.04"; fi
  docker buildx build --builder default --load --provenance=false --sbom=false \
    --build-context "studio_artifacts=${artifacts}" --build-context "audiocpp_source=${build_root}/sources" \
    --build-arg "VVOICE_BASE_IMAGE=${base}" --build-arg "AUDIOCPP_BUILD_BASE_IMAGE=${compiler}" \
    --build-arg "AUDIOCPP_CUDA=${cuda}" --build-arg "AUDIOCPP_BACKEND=${backend}" --build-arg "TARGETARCH=${arch}" \
    -f docker/Dockerfile.studio -t "$image" .
fi
if [[ "$mode" == full || "$mode" == publish ]]; then
  docker image inspect "$image" >/dev/null
  docker push "$image"
  python3 "$root/scripts/feishu_release.py" --sheet "$sheet" --tag "$tag" --repository "${registry}/v-voice"
  if [[ "$sheet" == ARM_without_cuda ]]; then
    python3 "$root/scripts/feishu_release.py" --sheet SOPHON_bm1688 --tag "$tag" --repository "${registry}/v-voice"
  fi
fi
