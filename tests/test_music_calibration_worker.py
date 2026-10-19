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
        result = self.execute('import sys; sys.stdin.read()')
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


if __name__ == '__main__':
    unittest.main()
