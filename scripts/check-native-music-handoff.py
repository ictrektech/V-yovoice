#!/usr/bin/env python3
"""隔离联调探针；默认只读，显式 --generate 才申请真实推理许可。"""
import argparse
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

MODELS = ('ace-step-1.5-turbo', 'stable-audio-3-small-music',
          'stable-audio-3-medium', 'musicgen-small')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:22709')
    parser.add_argument('--generate', choices=MODELS)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    base = args.base_url.rstrip('/')
    with urlopen(base + '/health', timeout=30) as response:
        print('health:', response.status)
    with urlopen(base + '/api/v1/discovery', timeout=60) as response:
        discovery = json.load(response)
    music = discovery.get('scheduler', {}).get('execution_settings', {}).get('music')
    assert music, 'missing execution_settings.music'
    print('execution_settings.music:', json.dumps(music, sort_keys=True))
    with urlopen(base + '/api/v1/music-models', timeout=1800) as response:
        inventory = json.load(response)
    rows = inventory if isinstance(inventory, list) else inventory.get('models', [])
    found = {row['key']: row for row in rows}
    assert set(MODELS) <= found.keys(), 'missing native music model'
    for key in MODELS:
        row = found[key]
        print(key, json.dumps({name: row.get(name) for name in
                              ('status', 'admission_ready', 'runtime_available')}, sort_keys=True))
    if not args.generate:
        print('READ_ONLY_PASS; no inference requested')
        return
    if not args.output:
        parser.error('--generate requires --output')
    assert found[args.generate].get('admission_ready'), 'model not calibrated; refusing inference'
    payload = dict(model=args.generate, prompt='Soft instrumental piano background music.',
                   duration=10, negative_prompt='', seed=42, instrumental=True,
                   response_format='wav')
    request = Request(base + '/v1/audio/music/generations',
                      data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
    try:
        with urlopen(request, timeout=1900) as response:
            data = response.read()
            assert data[:4] == b'RIFF' and data[8:12] == b'WAVE', 'not WAV output'
            assert len(data) > 44, 'empty WAV output'
            with args.output.open('xb') as output:
                output.write(data)
            print('GENERATION_PASS:', len(data), 'bytes;', args.output)
    except HTTPError as error:
        raise SystemExit(f'Generation rejected: HTTP {error.code}; inspect service logs privately') from None


if __name__ == '__main__':
    main()
