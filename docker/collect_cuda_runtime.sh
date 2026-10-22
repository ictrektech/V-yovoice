#!/usr/bin/env bash
set -euo pipefail
# 仅从开发镜像提取 ONNX/audio.cpp 使用的共享库，不继承 Python、Torch 或编译工具链。
mkdir -p /cuda-runtime
copy_library() {
  local source="$1" target
  target="$(readlink -f "$source")"
  [[ -f "/cuda-runtime/$(basename "$target")" ]] || cp "$target" /cuda-runtime/
  if [[ "$(basename "$source")" != "$(basename "$target")" ]]; then
    ln -sf "$(basename "$target")" "/cuda-runtime/$(basename "$source")"
  fi
}
for library in libcudart libcublas libcublasLt libcufft libcurand libcusolver libcusparse libnvJitLink libnvrtc; do
  found=false
  for source in /usr/local/cuda/lib64/${library}.so*; do
    [[ -f "$source" ]] || continue
    copy_library "$source"
    found=true
  done
  [[ "$found" == true ]] || { echo "Missing CUDA runtime library: $library" >&2; exit 1; }
done
# ARM CUDA 13 的 ORT 还链接 SDK 中的 Protobuf/Abseil；它们是独立 C++ 库，不依赖 Torch。
for source in /usr/local/cuda/lib64/libnvrtc-builtins.so* /usr/lib/aarch64-linux-gnu/libcudnn*.so* /usr/lib/libprotobuf*.so* /usr/lib/libabsl*.so*; do
  [[ ! -f "$source" ]] || copy_library "$source"
done
# audio.cpp 的 CUDA 13 后端需要 NCCL；CUDA 12 镜像不额外携带该库。
if [[ -f /cuda-runtime/libcudart.so.13 ]]; then
  for source in /usr/lib/aarch64-linux-gnu/libnccl.so*; do
    [[ ! -f "$source" ]] || copy_library "$source"
  done
  test -s /cuda-runtime/libnccl.so.2
fi
test -s /cuda-runtime/libcudnn.so.9
mkdir -p /cuda-notices
for notice in /usr/share/doc/cuda-*/copyright /usr/share/doc/libcu*/copyright /usr/share/doc/libnv*/copyright /usr/share/doc/libnccl*/copyright /usr/share/doc/libprotobuf*/copyright /usr/share/doc/libabsl*/copyright /opt/nvidia/entrypoint.d/30-container-license.txt; do
  [[ -f "$notice" ]] || continue
  cp -L "$notice" "/cuda-notices/$(basename "$(dirname "$notice")")-$(basename "$notice")"
done
