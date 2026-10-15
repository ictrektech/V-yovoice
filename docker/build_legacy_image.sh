#!/usr/bin/env bash
set -euo pipefail
[[ "${VVOICE_LEGACY_STAGE:-}" == 1 ]] || { echo "Internal stage; use docker/build_image.sh" >&2; exit 1; }

cd "$(dirname "$0")/.."
REGISTRY="${REGISTRY:-swr.cn-southwest-2.myhuaweicloud.com/ictrek}"
REPOSITORY="${REGISTRY}/v-voice"
DATE="$(date +%Y%m%d)"
SHERPA_ONNX_VERSION="${SHERPA_ONNX_VERSION:-1.13.8}"

case "$(uname -m)" in
  x86_64|amd64) host_arch=amd ;;
  aarch64|arm64) host_arch=arm ;;
  *) echo "unsupported architecture" >&2; exit 1 ;;
esac

sheet=""
build=true
publish=true
mode=full
while [[ $# -gt 0 ]]; do
  case "$1" in
    --sheet) sheet="$2"; shift 2 ;;
    --build-only) [[ "$mode" == full ]] || { echo "choose only one build mode" >&2; exit 1; }; mode=build-only; publish=false; shift ;;
    --publish-only) [[ "$mode" == full ]] || { echo "choose only one build mode" >&2; exit 1; }; mode=publish-only; build=false; shift ;;
    -h|--help) echo "Usage: $0 --sheet <AMD_with_cuda|AMD_with_mxn100|ARM_without_cuda|SOPHON_bm1688|ARM_with_cuda|l4t|thor_spark> [--build-only|--publish-only]"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 1 ;;
  esac
done
[[ -n "$sheet" ]] || { echo "--sheet is required" >&2; exit 1; }

dockerfile=""
tag_prefix=""
build_args=(--build-arg "NODE_IMAGE=${REGISTRY}/node:${host_arch}_22-alpine" --build-arg "SHERPA_ONNX_VERSION=${SHERPA_ONNX_VERSION}")
case "$sheet" in
  AMD_with_mxn100) [[ "$host_arch" == amd ]]; dockerfile=docker/Dockerfile.cpu; tag_prefix=amd; build_args+=(--build-arg "PYTHON_BASE_IMAGE=${REGISTRY}/python:amd_3.12-slim") ;;
  AMD_with_cuda) [[ "$host_arch" == amd ]]; dockerfile=docker/Dockerfile.amd-cuda; tag_prefix=amd_cu128; build_args+=(--build-arg "CUDA_RUNTIME_BASE_IMAGE=${REGISTRY}/nvidia-cuda:amd_12.8.1-runtime-ubuntu22.04" --build-arg "CUDA_CUDNN_BASE_IMAGE=${REGISTRY}/nvidia-cuda:amd_12.8.1-cudnn-devel-ubuntu22.04") ;;
  ARM_without_cuda|SOPHON_bm1688) [[ "$host_arch" == arm ]]; dockerfile=docker/Dockerfile.cpu; tag_prefix=arm; build_args+=(--build-arg "PYTHON_BASE_IMAGE=${REGISTRY}/python:arm_3.12-slim") ;;
  ARM_with_cuda) [[ "$host_arch" == arm ]]; dockerfile=docker/Dockerfile.arm-cuda; tag_prefix=arm_cu130; build_args+=(--build-arg "ARM_CUDA_BASE_IMAGE=${REGISTRY}/nvidia-pytorch:arm_25.08-py3") ;;
  l4t) [[ "$host_arch" == arm ]]; dockerfile=docker/Dockerfile.l4t; tag_prefix=l4t; build_args+=(--build-arg "L4T_BASE_IMAGE=${REGISTRY}/pytorch_py312:jet_2.7.0") ;;
  thor_spark) [[ "$host_arch" == arm ]]; dockerfile=docker/Dockerfile.thor; tag_prefix=thor; build_args+=(--build-arg "THOR_BASE_IMAGE=${REGISTRY}/nvidia-pytorch:arm_25.08-py3") ;;
  *) echo "unsupported sheet: $sheet" >&2; exit 1 ;;
esac

if [[ "$dockerfile" != docker/Dockerfile.cpu ]]; then
  wheel_root="${SHERPA_WHEEL_DIR:-${HOME}/dev/build/v-voice/sherpa-wheels}"
  case "$sheet" in
    AMD_with_cuda) wheel_profile=amd ;;
    l4t) wheel_profile=l4t ;;
    ARM_with_cuda|thor_spark) wheel_profile=arm-cuda13 ;;
  esac
  wheel_dir="${wheel_root}/${wheel_profile}"
  mkdir -p "$wheel_dir"
  if [[ "$host_arch" == amd ]]; then
    wheel="sherpa_onnx-${SHERPA_ONNX_VERSION}+cuda12.cudnn9.onnxruntime1.28.2-cp310-cp310-linux_x86_64.whl"
    if [[ ! -s "$wheel_dir/$wheel" ]]; then
      relative="csukuangfj2/sherpa-onnx-wheels/resolve/main/cuda/${SHERPA_ONNX_VERSION}/${wheel}"
      partial="$wheel_dir/${wheel}.partial"
      for origin in https://huggingface.co https://hf-mirror.com; do
        if curl -fL --connect-timeout 15 --max-time 1800 --retry 5 --retry-all-errors \
          "$origin/$relative" -o "$partial"; then
          mv "$partial" "$wheel_dir/$wheel"
          break
        fi
        rm -f "$partial"
      done
    fi
    [[ -s "$wheel_dir/$wheel" ]] || {
      echo "missing sherpa-onnx CUDA wheel: $wheel_dir/$wheel" >&2
      exit 1
    }
  else
    wheels=("$wheel_dir"/sherpa_onnx-"${SHERPA_ONNX_VERSION}"+*.whl)
    [[ ${#wheels[@]} -eq 1 && -s "${wheels[0]}" ]] || {
      echo "expected exactly one profile-compatible sherpa-onnx wheel in $wheel_dir" >&2
      echo "L4T requires CUDA 12/CUDNN 9; ARM_with_cuda and thor_spark require CUDA 13/ONNX Runtime 1.27." >&2
      exit 1
    }
  fi
  build_args+=(--build-context "sherpa_wheels=${wheel_dir}")
fi

if [[ "$sheet" == l4t ]]; then
  ort_root="${ORT_WHEEL_DIR:-${HOME}/dev/build/v-voice/ort-wheels}/l4t"
  ort_wheel="onnxruntime_gpu-1.23.0-cp312-cp312-linux_aarch64.whl"
  mkdir -p "$ort_root"
  if [[ ! -s "$ort_root/$ort_wheel" ]]; then
    partial="$ort_root/${ort_wheel}.partial"
    curl -fL --connect-timeout 15 --max-time 1800 --retry 5 --retry-all-errors \
      "https://pypi.jetson-ai-lab.io/jp6/cu129/+f/2e3/a07114007df15/$ort_wheel" -o "$partial"
    mv "$partial" "$ort_root/$ort_wheel"
  fi
  build_args+=(--build-context "ort_wheels=${ort_root}")
fi

tag="${tag_prefix}_${DATE}"
image="${REPOSITORY}:${tag}"
if [[ "$build" == true ]]; then
  docker buildx build --builder default --load --provenance=false --sbom=false \
    "${build_args[@]}" -t "v-voice:${tag}" -t "$image" -f "$dockerfile" .
fi
if [[ "$publish" == true ]]; then
  docker image inspect "$image" >/dev/null
  docker push "$image"
  python3 scripts/feishu_release.py --sheet "$sheet" --tag "$tag" --repository "$REPOSITORY"
  if [[ "$sheet" == ARM_without_cuda ]]; then
    python3 scripts/feishu_release.py --sheet SOPHON_bm1688 --tag "$tag" --repository "$REPOSITORY"
  fi
  echo "Published ${image}"
else
  echo "Built ${image}; validation is required before --publish-only"
fi
