#!/usr/bin/env bash
set -euo pipefail
# 原生音乐依赖独立安装，避免改变已有 ONNX 服务的 NumPy/Transformers 环境。
index="${VVOICE_MUSIC_PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"
# 不继承基础镜像已失效的 Jetson 索引或 pip 配置。
export PIP_INDEX_URL="$index" PIP_EXTRA_INDEX_URL="" PIP_CONFIG_FILE=/dev/null
python3 -m pip install --no-cache-dir --target /opt/vvoice/venv-bootstrap --index-url "$index" virtualenv
parent_sites="$(python3 -c 'import json,site; print(json.dumps(site.getsitepackages()))')"
PYTHONPATH=/opt/vvoice/venv-bootstrap python3 -m virtualenv --system-site-packages /opt/vvoice/music-python
music_python=/opt/vvoice/music-python/bin/python
# L4T 的 CUDA Torch 位于父虚拟环境，而非系统 site-packages。
"$music_python" "$(dirname "${BASH_SOURCE[0]}")/inherit_parent_packages.py" "$parent_sites"
if ! "$music_python" -c 'import torch' >/dev/null 2>&1; then
  torch_index=https://download.pytorch.org/whl/cpu
  torch_version=2.7.1
  if [[ "${VVOICE_PROVIDER:-cpu}" == cuda ]]; then
    # PyPI 的 Linux AMD64 Torch 2.8.0 固定依赖 CUDA 12.8，沿用可达镜像下载。
    torch_index="$index"
    torch_version=2.8.0
  elif [[ "$(uname -m)" == aarch64 ]]; then
    torch_index="$index"
  fi
  "$music_python" -m pip install --no-cache-dir --index-url "$torch_index" --extra-index-url "$index" "torch==$torch_version" "torchaudio==$torch_version"
elif ! "$music_python" -c 'import torchaudio' >/dev/null 2>&1; then
  version="$("$music_python" -c 'import torch; print(torch.__version__.split("+")[0].split("a")[0])')"
  "$music_python" -m pip install --no-cache-dir --no-deps --index-url "$index" "torchaudio==$version"
fi
if [[ "${VVOICE_PROVIDER:-cpu}" == cuda ]]; then
  "$music_python" -c 'import torch; assert torch.version.cuda, "GPU profile requires a CUDA-enabled Torch build"'
fi
"$music_python" -m pip install --no-cache-dir --index-url "$index" \
  einops einops-exts packaging safetensors sentencepiece tqdm 'huggingface-hub<1' 'transformers>=4.51,<4.58'
mkdir -p /tmp/vvoice-music-sources
curl -4 -fL --retry 4 --connect-timeout 15 --max-time 900 \
  "${GITHUB_ACCELERATOR:-https://gh-proxy.com/}https://github.com/Stability-AI/stable-audio-3/archive/779434a908193105335fd8d833418603625b2859.zip" \
  -o /tmp/vvoice-music-sources/stable-audio.zip
"$music_python" -m pip install --no-cache-dir --no-deps /tmp/vvoice-music-sources/stable-audio.zip
if [[ "${VVOICE_PROVIDER:-cpu}" == cuda ]]; then
  "$music_python" -m pip install --no-cache-dir --index-url "$index" \
    'accelerate>=1.12' 'diffusers>=0.37' diskcache 'loguru>=0.7' 'matplotlib>=3.7' \
    'numba>=0.63' 'numpy<2' 'peft>=0.18' 'pytorch-wavelets>=1.3' 'pywavelets>=1.9' \
    'scipy>=1.10' toml 'vector-quantize-pytorch>=1.27' 'huggingface-hub<1' 'transformers>=4.51,<4.58'
  curl -4 -fL --retry 4 --connect-timeout 15 --max-time 900 \
    "${GITHUB_ACCELERATOR:-https://gh-proxy.com/}https://github.com/ACE-Step/ACE-Step-1.5/archive/ca1e85fe9430179831e6bc6be790c332190a3866.zip" \
    -o /tmp/vvoice-music-sources/ace-step.zip
  "$music_python" -m pip install --no-cache-dir --no-deps /tmp/vvoice-music-sources/ace-step.zip
fi
"$music_python" -c 'import torch, torchaudio, stable_audio_3, transformers; from transformers import MusicgenForConditionalGeneration'
rm /tmp/vvoice-music-sources/stable-audio.zip
if [[ -f /tmp/vvoice-music-sources/ace-step.zip ]]; then rm /tmp/vvoice-music-sources/ace-step.zip; fi
rmdir /tmp/vvoice-music-sources
