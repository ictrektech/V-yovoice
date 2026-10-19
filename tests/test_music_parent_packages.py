"""父虚拟环境依赖可见，音乐依赖仍优先且父环境不被修改。"""
import json
from pathlib import Path
import subprocess
import sys
import venv


def test_nested_music_environment_inherits_without_overwriting_parent(tmp_path):
    parent, child = tmp_path / 'parent', tmp_path / 'child'
    venv.create(parent, with_pip=False)
    parent_python = parent / 'bin/python'
    parent_sites = json.loads(subprocess.check_output([
        str(parent_python), '-c', 'import json,site; print(json.dumps(site.getsitepackages()))']))
    marker = Path(parent_sites[0]) / 'vvoice_inheritance_probe.py'
    marker.write_text('origin = "parent"\n')
    subprocess.run([str(parent_python), '-m', 'venv', '--without-pip', '--system-site-packages', str(child)], check=True)
    child_python = str(child / 'bin/python')
    probe = 'import vvoice_inheritance_probe as m; print(m.origin)'
    assert subprocess.run([child_python, '-c', probe], capture_output=True).returncode != 0
    helper = Path(__file__).resolve().parents[1] / 'docker/inherit_parent_packages.py'
    subprocess.run([child_python, str(helper), json.dumps(parent_sites)], check=True)
    assert subprocess.check_output([child_python, '-c', probe], text=True).strip() == 'parent'
    child_site = subprocess.check_output([child_python, '-c', 'import site; print(site.getsitepackages()[0])'], text=True).strip()
    (Path(child_site) / marker.name).write_text('origin = "child"\n')
    assert subprocess.check_output([child_python, '-c', probe], text=True).strip() == 'child'
    assert marker.read_text() == 'origin = "parent"\n'
