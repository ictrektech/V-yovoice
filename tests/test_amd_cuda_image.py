"""AMD CUDA 成品只保留运行库，不重复打包库别名或安装包。"""
from pathlib import Path


def test_amd_cuda_preserves_cudnn_links_and_mounts_wheels():
    dockerfile = (Path(__file__).resolve().parents[1] / 'docker/Dockerfile.amd-cuda').read_text()
    assert 'cp -a /usr/lib/x86_64-linux-gnu/libcudnn*.so* /cudnn-runtime/' in dockerfile
    assert 'COPY --from=cudnn /cudnn-runtime/ /usr/lib/x86_64-linux-gnu/' in dockerfile
    assert 'COPY --from=cudnn /usr/lib/x86_64-linux-gnu/libcudnn' not in dockerfile
    assert '--mount=type=bind,from=sherpa_wheels,source=/,target=/tmp/sherpa-wheels' in dockerfile
    assert 'COPY --from=sherpa_wheels' not in dockerfile
    assert 'rm -rf /tmp/sherpa-wheels' not in dockerfile
