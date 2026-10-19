"""在音乐环境末尾追加父环境依赖目录，不改写父环境或覆盖本地依赖。"""
import json
from pathlib import Path
import site
import sys


def inherit_parent_packages(parent_sites):
    if sys.prefix == sys.base_prefix:
        raise RuntimeError('必须在独立音乐虚拟环境内运行')
    destination = Path(site.getsitepackages()[0])
    visible = {str(Path(path).resolve()) for path in sys.path if path}
    additions = []
    for path in parent_sites:
        resolved = str(Path(path).resolve())
        if Path(path).is_dir() and resolved not in visible:
            additions.append(resolved)
            visible.add(resolved)
    (destination / 'vvoice-parent-packages.pth').write_text(
        ''.join(path + '\n' for path in additions), encoding='utf-8')


if __name__ == '__main__':
    inherit_parent_packages(json.loads(sys.argv[1]))
