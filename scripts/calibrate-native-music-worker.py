#!/usr/bin/env python3
"""仅供持有外层校准许可的隔离容器使用；不启动业务 API、不预约第二份许可。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import wave

NATIVE_ENTRY = '''
from vvoice.music_worker import main
main()
import json, sys, torch
from pathlib import Path
Path(sys.argv[2]).write_text(json.dumps({
    'torch_threads': torch.get_num_threads(),
    'torch_interop_threads': torch.get_num_interop_threads(),
    'torch_version': torch.__version__,
    'cuda_available': torch.cuda.is_available(),
}))
'''


def kill_and_wait(process):
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def birth_marker(pid):
    # comm 字段可能包含空格或括号，starttime 是右括号后第 20 项。
    stat = Path(f'/proc/{pid}/stat').read_text()
    return {'pid': pid, 'start_ticks': stat.rsplit(')', 1)[1].split()[19],
            'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}


def record(path, value):
    temporary = path.with_suffix('.tmp')
    with temporary.open('x') as target:
        json.dump(value, target, sort_keys=True)
    temporary.chmod(0o600)
    temporary.replace(path)


def run_worker(command, payload, root, cancelled, timeout=1800):
    process = None
    started = time.monotonic()
    with (root / 'native.log').open('xb') as log:
        try:
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=log,
                                       stderr=subprocess.STDOUT, start_new_session=True,
                                       env={**os.environ, 'VVOICE_MUSIC_PARENT_PID': str(os.getpid())})
            marker = birth_marker(process.pid)
            record(root / 'native-started', marker | {'phase': 'worker_spawned_before_runtime_import'})
            process.stdin.write(json.dumps(payload).encode())
            process.stdin.close()
            while process.poll() is None:
                if cancelled.is_set() or (root / 'cancel').exists() or time.monotonic() - started > timeout:
                    kill_and_wait(process)
                    return marker | {'stopped': True, 'cancelled': cancelled.is_set() or (root / 'cancel').exists(),
                                     'timed_out': time.monotonic() - started > timeout,
                                     'exit_code': process.returncode}
                time.sleep(0.05)
            return marker | {'stopped': True, 'cancelled': False, 'timed_out': False,
                             'exit_code': process.returncode}
        finally:
            if process is not None and process.poll() is None:
                kill_and_wait(process)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', default=os.getenv('CALIBRATION_MODEL', 'musicgen-small'))
    parser.add_argument('--data', type=Path, default=Path('/data'))
    args = parser.parse_args()
    # 此标识不是业务授权凭据，只防止误启动；外层必须先获取真实许可和硬资源限制。
    if os.getenv('VVOICE_EXTERNAL_CALIBRATION_PERMIT') != 'active':
        parser.error('requires outer Scheduler calibration permit and isolated container')
    from vvoice.catalog import model_files_ready
    from vvoice.music_catalog import find_model, runtime_settings, supported
    from vvoice.config import settings
    item = find_model(args.model)
    assert supported(item, settings.provider), 'incompatible provider'
    ready, reason = model_files_ready(item)
    assert ready, 'weights not verified: ' + reason
    root = args.data
    root.mkdir(parents=True, exist_ok=True)
    output = root / 'calibration.wav'
    assert not output.exists(), 'use a fresh isolated output directory'
    request = dict(model=args.model, prompt='Soft instrumental piano background music.',
                   negative_prompt='', duration=10, seed=42, bpm=None, key_name='',
                   time_signature='', instrumental=True, response_format='wav')
    evidence = {'model': args.model, 'execution_settings': {'music': runtime_settings()},
                'inputs': {'duration_seconds': 10, 'prompt_characters': len(request['prompt']),
                           'negative_prompt_characters': 0},
                'modelscope_repo': item['modelscope_repo'], 'verified_files': item['shared_files'],
                'catalog_sha256': hashlib.sha256(json.dumps(item['shared_files'], sort_keys=True).encode()).hexdigest()}
    record(root / 'calibration-input.json', evidence)
    cancelled = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: cancelled.set())
    python = os.getenv('VVOICE_MUSIC_PYTHON', sys.executable)
    runtime_evidence = root / 'native-runtime.json'
    process = run_worker([python, '-c', NATIVE_ENTRY, str(output), str(runtime_evidence)], request, root, cancelled)
    evidence['native_process'] = process
    if process['cancelled'] or process['timed_out'] or process['exit_code'] != 0:
        record(root / 'calibration-stop.json', evidence)
        raise SystemExit(0 if process['cancelled'] else 1)
    evidence['observed_runtime'] = json.loads(runtime_evidence.read_text())
    for key in ('torch_threads', 'torch_interop_threads'):
        assert evidence['observed_runtime'][key] == runtime_settings()[key], 'runtime thread mismatch'
    with wave.open(str(output), 'rb') as audio:
        evidence['output'] = {'duration_seconds': audio.getnframes() / audio.getframerate(),
                              'sample_rate': audio.getframerate(), 'channels': audio.getnchannels(),
                              'bytes': output.stat().st_size,
                              'sha256': hashlib.sha256(output.read_bytes()).hexdigest()}
    assert evidence['output']['duration_seconds'] > 0, 'empty audio'
    record(root / 'calibration-result.json', evidence)


if __name__ == '__main__':
    main()
