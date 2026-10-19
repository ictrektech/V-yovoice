"""校准包装的真实子进程生命周期测试，不加载模型、不替代推理验收。"""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

spec = importlib.util.spec_from_file_location('music_calibration', Path(__file__).resolve().parents[1] / 'scripts/calibrate-native-music-worker.py')
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


@unittest.skipUnless(sys.platform == 'linux', 'Linux /proc lifecycle evidence only')
class WorkerLifecycleTests(unittest.TestCase):
    def execute(self, code, cancelled=False, timeout=5):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stop = threading.Event()
            if cancelled:
                stop.set()
            result = worker.run_worker([sys.executable, '-c', code], {}, root, stop, timeout)
            marker = json.loads((root / 'native-started').read_text())
            self.assertEqual(marker['pid'], result['pid'])
            self.assertEqual(marker['start_ticks'], result['start_ticks'])
            self.assertFalse(Path(f"/proc/{result['pid']}").exists())
            self.assertTrue(result['stopped'])
            return result

    def test_normal_exit_is_reaped(self):
        result = self.execute('import os,sys; assert os.environ["VVOICE_MUSIC_PARENT_PID"] == str(os.getppid()); sys.stdin.read()')
        self.assertEqual(result['exit_code'], 0)
        self.assertFalse(result['cancelled'])

    def test_cancel_kills_and_reaps_native_worker(self):
        result = self.execute('import time; time.sleep(60)', cancelled=True)
        self.assertTrue(result['cancelled'])
        self.assertLess(result['exit_code'], 0)

    def test_timeout_kills_and_reaps_native_worker(self):
        result = self.execute('import time; time.sleep(60)', timeout=0)
        self.assertTrue(result['timed_out'])
        self.assertLess(result['exit_code'], 0)

    def test_real_linux_worker_parent_handshake_without_model_inference(self):
        code = '''
import sys, types
runtime = types.ModuleType('vvoice.music_runtime')
runtime.generate_music = lambda *_args, **_kwargs: (b'fixture-only', 'audio/wav')
sys.modules['vvoice.music_runtime'] = runtime
from vvoice.music_worker import main
main()
'''
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / 'fixture.wav'
            result = worker.run_worker([sys.executable, '-c', code, str(output)],
                                       {'model': 'fixture'}, root, threading.Event())
            self.assertEqual(result['exit_code'], 0)
            self.assertEqual(output.read_bytes(), b'fixture-only')
            self.assertTrue(result['stopped'])


if __name__ == '__main__':
    unittest.main()
