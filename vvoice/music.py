"""统一配乐 API；现有音乐模型通过 V-Voice 自己的调度身份执行。"""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .admission import admit_model, configuration, current, run_blocking, validate_inputs, model_limits
from .catalog import model_files_ready
from .config import settings
from .modelhub import cancel_model, list_models, pull_model
from .music_catalog import catalog, find_model, runtime_settings, supported
from .runtime import detect_provider

router = APIRouter(tags=['Background music'])


class MusicRequest(BaseModel):
    model: str
    prompt: str = Field(min_length=1, max_length=4000)
    duration: float = Field(30, ge=10, le=300)
    negative_prompt: str = Field('', max_length=4000)
    seed: int | None = Field(None, ge=-1, le=2147483647)
    bpm: int | None = Field(None, ge=20, le=300)
    key: str = Field('', max_length=32)
    time_signature: Literal['', '2/4', '3/4', '4/4', '6/8'] = ''
    instrumental: bool = True
    response_format: Literal['wav', 'flac'] = 'wav'


def validate_request(request: MusicRequest) -> dict:
    try:
        item = find_model(request.model)
    except KeyError:
        raise HTTPException(404, 'Music model not found') from None
    if not request.prompt.strip():
        raise HTTPException(422, 'Music prompt is required')
    if request.duration > item.get('max_duration_seconds', 300):
        raise HTTPException(422, 'Music model duration limit exceeded')
    if not supported(item, detect_provider()):
        raise HTTPException(503, 'Music model requires a compatible accelerator')
    if os.getenv('VVOICE_SCHEDULER_REQUIRED') == 'true':
        config = configuration()
        if config.get('execution_settings', {}).get('music') != runtime_settings():
            raise HTTPException(503, 'Music runtime settings require V-Voice calibration')
        if config.get('input_limits_version') != 1:
            raise HTTPException(503, 'Music input calibration required')
    validate_inputs(request.model, duration_seconds=request.duration,
                    prompt_characters=len(request.prompt), negative_prompt_characters=len(request.negative_prompt))
    return item


class MusicRuntime:
    def __init__(self):
        self.gate = threading.Lock()
        self.lock = threading.Lock()
        self.process = None
        self.model = ''

    def loaded(self, key):
        with self.lock:
            return self.model == key and self.process is not None and self.process.poll() is None

    def generate(self, request: MusicRequest):
        # 不在预约后排队占用预算；唯一原生音乐进程，跨模型/用户也不并发加载。
        if not self.gate.acquire(blocking=False):
            raise HTTPException(429, 'Music runtime busy', headers={'Retry-After': '1'})
        execution = current.get()
        process = None
        try:
            item = find_model(request.model)
            ready, _ = model_files_ready(item)
            if not ready:
                raise HTTPException(503, 'Music weights require complete file verification')
            with tempfile.TemporaryDirectory(prefix='vvoice-music-') as directory:
                output = Path(directory) / ('music.' + request.response_format)
                error = Path(directory) / 'worker.log'
                with error.open('wb') as stderr:
                    python = os.getenv('VVOICE_MUSIC_PYTHON', sys.executable)
                    process = subprocess.Popen([python, '-m', 'vvoice.music_worker', str(output)],
                                               stdin=subprocess.PIPE, stdout=stderr, stderr=stderr, start_new_session=True)
                    with self.lock:
                        self.process, self.model = process, request.model
                    payload = request.model_dump()
                    payload['key_name'] = payload.pop('key')
                    process.stdin.write(json.dumps(payload).encode())
                    process.stdin.close()
                    deadline = time.monotonic() + 1800
                    while process.poll() is None:
                        if (execution and execution.failed) or time.monotonic() > deadline:
                            self.kill(process)
                            raise HTTPException(503, 'Music execution stopped after lease loss or timeout')
                        time.sleep(0.05)
                if process.returncode != 0 or not output.is_file():
                    raise HTTPException(503, 'Music engine failed; check installed runtime and model package')
                if execution and execution.failed:
                    raise HTTPException(503, 'Music compute lease was lost')
                return output.read_bytes()
        finally:
            if process and process.poll() is None:
                self.kill(process)
            with self.lock:
                self.process, self.model = None, ''
            self.gate.release()

    @staticmethod
    def kill(process):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


runtime = MusicRuntime()


@router.get('/api/v1/music-models')
async def models():
    rows = await list_models(catalog())
    for row in rows:
        approved = os.getenv('VVOICE_SCHEDULER_REQUIRED') != 'true'
        limit = None
        if not approved:
            try:
                config = configuration()
                approved = bool(config.get('models', {}).get(row['key'])) and config.get('input_limits_version') == 1 and config.get('execution_settings', {}).get('music') == runtime_settings()
                if approved:
                    limit = model_limits(row['key'])
            except HTTPException:
                approved = False
        row.update(loaded=runtime.loaded(row['key']), runtime_available=supported(row, detect_provider()),
                   admission_ready=approved, execution_settings=runtime_settings())
        if limit:
            row['max_duration_seconds'] = min(row.get('max_duration_seconds', 300), limit['duration_seconds'])
    return rows


async def administrator(request: Request):
    url = os.getenv('VOS_USERINFO_URL', '')
    auth = request.headers.get('Authorization', '')
    if not url or not auth.startswith('Bearer '):
        raise HTTPException(401, 'VOS model administrator sign-in required')
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
            response = await client.get(url, headers={'Authorization': auth})
        user = response.json()
        if response.status_code != 200 or type(user.get('enable')) is not int or user['enable'] != 1 or not user.get('sub'):
            raise HTTPException(401, 'Invalid VOS identity')
    except (httpx.HTTPError, ValueError):
        raise HTTPException(503, 'VOS identity service unavailable') from None
    if user.get('role_code') not in {'system_admin', 'platform_admin'}:
        raise HTTPException(403, 'Model administrator required')


@router.post('/api/v1/music-models/{key}/{action}')
async def manage(key: str, action: Literal['pull', 'stop', 'unload'], request: Request, force: bool = False):
    await administrator(request)
    try:
        find_model(key)
        if action == 'unload':
            if runtime.loaded(key):
                raise HTTPException(409, 'Music generation is active; cannot unload its weights')
            return {'status': 'unloaded', 'model': key}
        return await (pull_model(key, force) if action == 'pull' else cancel_model(key))
    except KeyError:
        raise HTTPException(404, 'Music model not found') from None
    except httpx.HTTPError:
        raise HTTPException(502, 'V-Scheduler model repository unavailable') from None


@router.post('/v1/audio/music/generations', response_class=Response)
async def generate(request: MusicRequest):
    validate_request(request)
    await admit_model(request.model)
    body = await run_blocking(runtime.generate, request)
    return Response(body, media_type='audio/wav' if request.response_format == 'wav' else 'audio/flac',
                    headers={'Content-Disposition': 'inline; filename="music.' + request.response_format + '"',
                             'Cache-Control': 'no-store'})
