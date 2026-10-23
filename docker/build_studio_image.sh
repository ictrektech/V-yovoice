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
    --assets-only) mode=assets; prepare=false; shift ;;
    --application-only) mode=application; prepare=false; shift ;;
    --reuse-prepared-artifacts) prepare=false; shift ;;
    *) echo "Usage: $0 --sheet <sheet> [--build-only|--publish-only|--prepare-only|--assets-only]" >&2; exit 1 ;;
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
if [[ "$mode" == assets || "$mode" == application ]]; then
  # 仅用于前端变更：沿用已完成的当日后端镜像，验证通过后仍须显式发布。
  test -s "$artifacts/web/index.html"
  test -s "$artifacts/frontend/index.html"
  source_image="$image"
  if [[ "$mode" == application ]]; then
    source_image="${VVOICE_STUDIO_BASE_IMAGE:?--application-only requires the verified published VVOICE_STUDIO_BASE_IMAGE}"
    test -s "$artifacts/linux-${arch}/vvoice-studio"
  fi
  docker run --rm --pull never --entrypoint test "$source_image" -f /opt/vvoice/web/index.html
  docker run --rm --pull never --entrypoint python3 "$source_image" -c "import importlib.util; from pathlib import Path; assert all(importlib.util.find_spec(name) is None for name in ('torch', 'torchaudio', 'transformers', 'diffusers')) and not Path('/opt/vvoice/music-python').exists(), 'Runtime changed: use a full rebuild, not an overlay'"
  # Preserve the published repository identity so containerd can retrieve lazy layers.
  assets_base="$source_image"
  dockerfile="$root/docker/Dockerfile.studio-assets"
  if [[ "$mode" == application ]]; then dockerfile="$root/docker/Dockerfile.application"; fi
  docker buildx build --builder default --load --provenance=false --sbom=false \
    --build-context "studio_artifacts=${artifacts}" --build-arg "TARGETARCH=${arch}" --build-arg "VVOICE_STUDIO_BASE_IMAGE=${assets_base}" \
    -f "$dockerfile" -t "$image" "$root"
  exit 0
fi
if [[ "$prepare" == true && ( "$mode" == prepare || "$mode" == full || "$mode" == build ) ]]; then
  mkdir -p "$build_root/source" "$artifacts/linux-${arch}" "$build_root/sources"
  rsync -a --exclude=.git --exclude=node_modules --exclude=dist --exclude=__pycache__ "$root/" "$build_root/source/"
  cd "$build_root/source"
  GOCACHE="$build_root/go-cache" GOPROXY="${GOPROXY:-https://goproxy.cn,direct}" CGO_ENABLED=0 \
    go build -trimpath -o "$artifacts/linux-${arch}/vvoice-studio" ./cmd/vvoice-studio
  npx --yes pnpm@9.15.2 --dir web install --frozen-lockfile
  VITE_VOS=true npx --yes pnpm@9.15.2 --dir web run build
  mkdir -p "$artifacts/web"
  rsync -a --delete web/dist/ "$artifacts/web/"
  npm --prefix frontend ci
  npm --prefix frontend run build
  mkdir -p "$artifacts/frontend"
  rsync -a --delete frontend/dist/ "$artifacts/frontend/"
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
  test -s "$artifacts/frontend/index.html"
  echo "20f589b7f891eee1e9d35d1fcea5382c925cf3413f4db5ba71d70cd9a991c938  $build_root/sources/audio.cpp-v0.9.1.tar.gz" | sha256sum -c -
  mkdir -p "$build_root/source"
  rsync -a --exclude=.git --exclude=node_modules --exclude=dist --exclude=__pycache__ "$root/" "$build_root/source/"
  if [[ "$cuda" == ON ]]; then backend=cuda; fi
  # 原 V-Voice 的六套构建配置继续从当前源码生成基础服务，不依赖历史成品镜像。
  cd "$build_root/source"
  base="v-voice-legacy-build:${prefix}"
  # 编译器仅用于多阶段构建，最终镜像不继承带 Torch 的 SDK 层。
  case "$sheet" in
      AMD_with_mxn100) platform_base="${registry}/python:amd_3.12-slim" ;;
      ARM_without_cuda|SOPHON_bm1688) platform_base="${registry}/python:arm_3.12-slim" ;;
      AMD_with_cuda) platform_base="${registry}/nvidia-cuda:amd_12.8.1-cudnn-devel-ubuntu22.04" ;;
      l4t) platform_base="${registry}/pytorch_py312:jet_2.7.0" ;;
      *) platform_base="${registry}/nvidia-pytorch:arm_25.08-py3" ;;
  esac
  REGISTRY="$registry" VVOICE_LEGACY_STAGE=1 bash docker/build_legacy_image.sh --sheet "$sheet" --build-only
  docker tag "$image" "$base"
  compiler="${VVOICE_AUDIOCPP_BUILD_BASE_IMAGE:-$platform_base}"
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
