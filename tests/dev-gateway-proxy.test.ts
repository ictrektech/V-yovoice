import { after, before, test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';
import { taskMatches } from '../web/dev-models.ts';
import { createServer as createViteServer, type ViteDevServer } from '../web/node_modules/vite/dist/node/index.js';

const root = fileURLToPath(new URL('../', import.meta.url));
const directory = mkdtempSync(join(tmpdir(), 'vvoice-proxy-'));
const token = 'server-only-gateway-test-key';
const supported = JSON.parse(execFileSync('python3', [join(root, 'scripts/dev-catalog.py')], { encoding: 'utf8' }));
let servicesAvailable = true;
let tasks: { model_id: string; phase: string; task_id: string; files?: string[] }[] = [];
const calls: { path: string; body: string; authorization?: string; cookie?: string; apiKey?: string }[] = [];
const upstream = createServer(async (request, response) => {
  let body = '';
  for await (const chunk of request) body += chunk;
  calls.push({ path: request.url ?? '', body, authorization: request.headers.authorization,
    cookie: request.headers.cookie, apiKey: request.headers['x-api-key'] as string | undefined });
  if (request.url === '/api/v1/models') {
    response.setHeader('Content-Type', 'application/json');
    response.end(JSON.stringify({ models: servicesAvailable ? [
      { id: 'sensevoice-int8', qualified: 'v-voice/sensevoice-int8', capabilities: ['asr'] },
      { id: 'kokoro-multilang', qualified: 'v-voice/kokoro-multilang', capabilities: ['tts'] },
    ] : [] }));
  } else if (request.url === '/hub/api/v1/models?status=all') {
    response.end(JSON.stringify(supported.speech.filter((model: { key: string }) => ['sensevoice-int8', 'kokoro-multilang'].includes(model.key))
      .map((model: { modelscope_repo: string }) => ({ model_id: 'ms://' + model.modelscope_repo, status: 'ready' }))));
  } else if (request.url === '/hub/api/v1/tasks') {
    response.end(JSON.stringify(tasks));
  } else if (request.url?.startsWith('/hub/api/v1/models/files?')) {
    const repo = new URL(request.url, 'http://localhost').searchParams.get('model_id')!.replace('ms://', '');
    const model = supported.speech.find((model: { modelscope_repo: string }) => model.modelscope_repo === repo);
    const files = model.key === 'kokoro-multilang'
      ? ['vvoice-model.json', 'model.onnx', 'voices.bin', 'tokens.txt', 'espeak-ng-data/en_dict', 'lexicon-us-en.txt', 'lexicon-zh.txt'].map(path => ({ path }))
      : model.required_files;
    response.end(JSON.stringify({ files: files.map((file: { path: string }) => ({ ...file, downloaded: true })) }));
  } else if (request.url?.match(/^\/hub\/api\/v1\/tasks\/[^/]+\/cancel$/)) {
    response.end('{}');
  } else if (request.url === '/hub/api/v1/models/pull') {
    if (JSON.parse(body).append) { response.writeHead(400).end(JSON.stringify({ detail: 'append requires a ready model' })); }
    else { response.writeHead(202).end(JSON.stringify({ task_id: 'platform-download-task' })); }
  } else if (request.url?.startsWith('/v1/audio/voices?')) {
    response.end(JSON.stringify({ voices: [{ id: 'remote-voice', sid: 3, language: 'en' }] }));
  } else if (request.url === '/v1/audio/speech') {
    response.setHeader('Content-Type', 'audio/wav');
    response.end('RIFF-from-platform');
  } else if (request.url === '/v1/audio/transcriptions') {
    response.end(JSON.stringify({ text: 'Transcribed by platform service' }));
  } else if (request.url === '/v1/chat/completions') {
    response.writeHead(429, { 'Content-Type': 'application/json', 'Retry-After': '2' });
    response.end(JSON.stringify({ error: { message: 'WAIT_MEMORY_HEADROOM' } }));
  } else { response.writeHead(404).end(); }
});
let vite: ViteDevServer;
let base = '';
const previous = { gateway: process.env.VVOICE_GATEWAY_BASE, file: process.env.VVOICE_GATEWAY_TOKEN_FILE, service: process.env.VITE_VOS_SERVICE_BASE, hub: process.env.MODEL_HUB_API_URL };
before(async () => {
  await new Promise<void>(resolve => upstream.listen(0, '127.0.0.1', resolve));
  writeFileSync(join(directory, 'token'), token, { mode: 0o600 });
  process.env.VVOICE_GATEWAY_BASE = `http://127.0.0.1:${(upstream.address() as { port: number }).port}`;
  process.env.VVOICE_GATEWAY_TOKEN_FILE = join(directory, 'token');
  process.env.MODEL_HUB_API_URL = process.env.VVOICE_GATEWAY_BASE + '/hub';
  process.env.VITE_VOS_SERVICE_BASE = 'http://127.0.0.1:7080';
  vite = await createViteServer({ root: join(root, 'web'), configFile: join(root, 'web/vite.config.ts'),
    logLevel: 'error', server: { host: '127.0.0.1', port: 0, strictPort: false } });
  await vite.listen();
  base = `http://127.0.0.1:${(vite.httpServer!.address() as { port: number }).port}`;
});
after(async () => {
  await vite?.close();
  await new Promise(resolve => upstream.close(resolve));
  for (const [name, value] of Object.entries({ VVOICE_GATEWAY_BASE: previous.gateway, VVOICE_GATEWAY_TOKEN_FILE: previous.file, VITE_VOS_SERVICE_BASE: previous.service, MODEL_HUB_API_URL: previous.hub })) {
    if (value === undefined) delete process.env[name]; else process.env[name] = value;
  }
  rmSync(directory, { recursive: true });
});

test('实际 Vite 代理：目录、ASR 文件、TTS 音频和网关错误完整往返', async () => {
  const models = await fetch(base + '/api/v1/models').then(response => response.json());
  assert.equal(models.length, 45);
  const asrModel = models.find((model: { key: string }) => model.key === 'sensevoice-int8');
  const ttsModel = models.find((model: { key: string }) => model.key === 'kokoro-multilang');
  assert.equal(asrModel.inference_key, 'v-voice/sensevoice-int8');
  assert.equal(ttsModel.inference_key, 'v-voice/kokoro-multilang');
  assert.ok('af_heart' in ttsModel.voices);
  const headers = { Authorization: 'Bearer browser-development-token', Cookie: 'browser-session=private', 'X-API-Key': 'browser-key' };
  const speech = await fetch(base + '/v1/audio/speech', { method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify({ model: ttsModel.inference_key, voice: 'af_heart', input: 'hello' }) });
  assert.equal(speech.headers.get('content-type'), 'audio/wav');
  assert.equal(await speech.text(), 'RIFF-from-platform');
  assert.equal(JSON.parse(calls.at(-1)!.body).model, 'v-voice/kokoro-multilang');
  const form = new FormData();
  form.set('model', asrModel.inference_key);
  form.set('file', new Blob(['RIFF-audio-input']), 'sample.wav');
  const asr = await fetch(base + '/v1/audio/transcriptions', { method: 'POST', headers, body: form });
  assert.equal((await asr.json()).text, 'Transcribed by platform service');
  assert.ok(calls.at(-1)!.body.includes('v-voice/sensevoice-int8') && calls.at(-1)!.body.includes('RIFF-audio-input'));
  const busy = await fetch(base + '/v1/chat/completions', { method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' }, body: '{}' });
  assert.equal(busy.status, 429);
  assert.equal(busy.headers.get('retry-after'), '2');
  assert.equal((await busy.json()).error.message, 'WAIT_MEMORY_HEADROOM');
  assert.ok(calls.every(call => call.authorization === `Bearer ${token}` && !call.cookie && !call.apiKey));
  assert.ok(calls.every(call => !call.path.includes('/permits') && !call.path.includes('/executors')));
});

test('未安装 VOS V-Voice 时仍展示 45 个支持模型，文件准备不等同于服务可调用', async () => {
  servicesAvailable = false;
  const models = await fetch(base + '/api/v1/models').then(response => response.json());
  assert.equal(models.length, 45);
  assert.deepEqual(['asr', 'tts', 'speaker'].map(kind => models.filter((model: { kind: string }) => model.kind === kind).length), [9, 35, 1]);
  assert.equal(models.filter((model: { files_ready: boolean }) => model.files_ready).length, 2);
  assert.equal(models.filter((model: { status: string }) => model.status === 'ready').length, 0);
  assert.equal(models.find((model: { key: string }) => model.key === 'sensevoice-int8').status, 'downloaded');
  assert.equal(models.find((model: { key: string }) => model.key === 'kokoro-multilang').status, 'downloaded');
});

test('安装按钮提交平台下载任务，GGUF 只补下载所选文件，失败后不扩大到整个仓库', async () => {
  assert.equal((await fetch(base + '/api/v1/models/whisper-tiny/pull', { method: 'POST' })).status, 202);
  const native = JSON.parse(calls.at(-1)!.body);
  assert.equal(native.source, 'ms');
  assert.equal(native.model_id, 'vivibit/v-voice-whisper-tiny-int8');
  const model = supported.speech.find((model: { shared_files?: unknown[]; import_required?: boolean }) => model.shared_files?.length && !model.import_required);
  const response = await fetch(base + `/api/v1/models/${model.key}/pull`, { method: 'POST' });
  assert.equal(response.status, 202);
  const payload = JSON.parse(calls.at(-1)!.body);
  assert.deepEqual(payload.files, model.shared_files.map((file: { path: string }) => file.path));
  assert.equal(payload.append, undefined);
  assert.equal(payload.force, false);
  const count = calls.length;
  assert.equal((await fetch(base + '/api/v1/models/not-supported/pull', { method: 'POST' })).status, 404);
  assert.equal(calls.length, count);
});

test('暂停只取消所选模型的活动下载，不影响其他精度或已结束任务', async () => {
  const model = supported.speech.find((model: { shared_files?: unknown[] }) => model.shared_files?.length);
  tasks = [
    { model_id: 'ms://' + model.modelscope_repo, phase: 'DOWNLOADING', task_id: 'selected', files: [model.shared_files[0].path] },
    { model_id: 'ms://' + model.modelscope_repo, phase: 'DOWNLOADING', task_id: 'other-precision', files: ['another.gguf'] },
    { model_id: 'ms://' + model.modelscope_repo, phase: 'FAILED', task_id: 'finished', files: [model.shared_files[0].path] },
  ];
  assert.equal(taskMatches(model, tasks[1]), false);
  const count = calls.length;
  const response = await fetch(base + `/api/v1/models/${model.key}/stop`, { method: 'POST' });
  assert.equal(response.status, 200);
  assert.deepEqual((await response.json()).tasks, ['selected']);
  assert.deepEqual(calls.slice(count).filter(call => call.path.endsWith('/cancel')).map(call => call.path), ['/hub/api/v1/tasks/selected/cancel']);
  tasks = [];
});
