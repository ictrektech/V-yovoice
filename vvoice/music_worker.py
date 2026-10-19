"""一次音乐计算一个子进程：退出即卸载 Torch 模型，父进程核验停止后释放许可。"""
import json
import os
from pathlib import Path
import sys
import ctypes
import signal


def main():
    # Linux 宿主意外退出时结束音乐计算，不能留下脱离许可生命周期的孤儿进程。
    if sys.platform == 'linux':
        parent = os.getppid()
        # 容器主服务正常就是 PID 1；按设置死亡信号前后的父进程一致性判断。
        if (os.getenv('VVOICE_MUSIC_PARENT_PID') != str(parent) or
                ctypes.CDLL(None).prctl(1, signal.SIGKILL) != 0 or os.getppid() != parent):
            raise SystemExit('Music parent process unavailable')
    # 固定本地权重；适配器不得临时向外网下载补件或执行用户提供的模型代码。
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TRANSFORMERS_OFFLINE'] = '1'
    output = Path(sys.argv[1])
    os.environ['HF_HOME'] = str(output.parent / 'hf-cache')
    os.environ['HF_MODULES_CACHE'] = str(output.parent / 'hf-modules')
    os.environ['TORCH_HOME'] = str(output.parent / 'torch-cache')
    from .music_runtime import generate_music
    request = json.load(sys.stdin)
    body, _ = generate_music(request.pop('model'), **request)
    with output.open('xb') as target:
        target.write(body)


if __name__ == '__main__':
    main()
