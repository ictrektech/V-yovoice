// 构建机隔离验收：真实 Scheduler/Agent、Go 工作台、Python 兼容 API 和 Router；不修改已安装实例。
import assert from 'node:assert/strict';
import { randomBytes } from 'node:crypto';
import { spawn, execFileSync } from 'node:child_process';
import { createServer } from 'node:http';
import { mkdirSync, mkdtempSync, writeFileSync, symlinkSync, linkSync, existsSync, openSync, readFileSync, readdirSync, copyFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const root = path.resolve(import.meta.dirname, '..');
const build = process.env.VVOICE_CONTRACT_BUILD;
assert(build && build.startsWith(path.join(os.homedir(), 'dev/build') + '/'));
const run = mkdtempSync(path.join(build, 'contract-'));
const basePort = Number(process.env.VVOICE_CONTRACT_PORT ?? 38720);
const scheduler = `http://127.0.0.1:${basePort}/api/v1`;
const voice = `http://127.0.0.1:${basePort + 1}`;
const router = `http://127.0.0.1:${basePort + 2}`;
const tokens = Object.fromEntries(['admin', 'voice', 'router', 'worker', 'executor', 'internal', 'db'].map(key => [key, randomBytes(32).toString('hex')]));
const children = [];
const containers = [];
const file = (name, data) => { const dest = path.join(run, name); writeFileSync(dest, typeof data === 'string' || Buffer.isBuffer(data) ? data : JSON.stringify(data), { mode: 0o600 }); return dest; };
const start = (binary, args, name, env = {}) => {
  const log = openSync(path.join(run, name + '.log'), 'a', 0o600);
  const child = spawn(binary, args, { env: { ...process.env, ...env }, stdio: ['ignore', log, log] });
  children.push(child); return child;
};
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function call(url, token, method = 'GET', body) {
  const response = await fetch(url, { method, headers: { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(1800000) });
  const text = await response.text();
  let data; try { data = JSON.parse(text); } catch { data = text; }
  return { status: response.status, data: data?.data ?? data };
}
async function ready(url) {
  for (let i = 0; i < 120; i++) {
    try { if ((await fetch(url, { signal: AbortSignal.timeout(2000) })).ok) return; } catch {}
    await delay(500);
  }
  throw new Error('Isolated service not ready: ' + url);
}
const schedulerBin = process.env.SCHEDULER_BINARY || path.join(os.homedir(), 'dev/build/V-Scheduler/cargo/debug/v-scheduler');
const models = ['audiocpp-kokoro-82m-q8', 'audiocpp-index-2.5-q8'];
const cloning = process.env.VVOICE_CHECK_CLONING === '1';
const legacyRepo = 'vivibit/v-voice-seaco-paraformer-zh-int8';
const legacySource = path.join(build, 'image-modelhub/export/ms', legacyRepo, 'current');
const legacy = existsSync(path.join(legacySource, 'model.int8.onnx')) && existsSync(path.join(build, 'seaco-public-sample.wav'));
const budget = { cpu_millicores: 8000, memory_mib: 24576, gpu_slots: 0, gpu_memory_mib: 0 };
const nodeID = 'v-voice-isolated-check';
const config = {
  principals: [
    { role: 'admin', app_id: 'admin', token: tokens.admin },
    { role: 'submitter', app_id: 'v-voice', token: tokens.voice, permit_executors: ['v-router.voice.infer'] },
    { role: 'submitter', app_id: 'v-router', token: tokens.router },
    { role: 'worker', app_id: 'agent', node_id: nodeID, token: tokens.worker },
  ],
  nodes: [{ id: nodeID, capacities: { cpu_millicores: Math.min(16000, os.cpus().length * 1000), memory_mib: Math.floor(os.totalmem() / 1048576), gpu_slots: 0, gpu_memory_mib: 0 } }],
  executors: [
    { id: 'v-voice.local.infer', contract_version: '1', task_type: 'model.infer', app_id: 'v-voice', node_id: nodeID, resources: budget, upstream_urls: [voice + '/v1'] },
    { id: 'v-router.voice.infer', contract_version: '1', task_type: 'model.infer', app_id: 'v-router', node_id: nodeID, resources: budget, upstream_urls: [voice + '/v1'] },
    { id: 'v-voice.generate', contract_version: '1', task_type: 'voice.generate', app_id: 'v-voice', node_id: nodeID, resources: budget },
  ],
};
const controllerConfig = file('controller.json', config);
const voiceConfig = file('voice.json', {
  url: scheduler, token: tokens.voice, executor_token: tokens.executor, upstream_url: voice + '/v1',
  models: { ...Object.fromEntries(models.map(id => [id, 'v-voice.local.infer'])), 'seaco-paraformer-zh': 'v-voice.local.infer', 'kokoro-82m-q8': 'v-voice.generate' },
  gateway_executors: Object.fromEntries(models.map(id => [id, 'v-router.voice.infer'])),
});
const routerConfig = file('router.json', {
  url: scheduler, token: tokens.router, require_model_policy: true,
  models: Object.fromEntries(models.map(id => ['app-v-voice/' + id, { mode: 'permit', executor_id: 'v-router.voice.infer', upstream_url: voice + '/v1', completion: 'synchronous', max_input_bytes: 1 << 20 }])),
});
const agentConfig = file('agent.json', { controller: scheduler, token: tokens.worker, node_id: nodeID, journal: path.join(run, 'agent-journal.json'), executors: [{ id: 'v-voice.generate', url: voice, token: tokens.executor, health_url: voice + '/health' }] });
const repo = JSON.parse(readFileSync(path.join(root, 'internal/catalog/vos.json'))).modelscope_repo;
const hub = path.join(run, 'modelhub');
mkdirSync(path.join(hub, 'export/ms', repo), { recursive: true });
const weights = path.join(run, 'weights');
mkdirSync(weights);
for (const model of JSON.parse(readFileSync(path.join(root, 'internal/catalog/catalog.json'))).filter(model => (cloning ? models : models.slice(0, 1)).includes('audiocpp-' + model.id))) {
  for (const entry of model.files ?? [{ path: model.remotePath }]) {
    const target = path.join(weights, entry.path);
    mkdirSync(path.dirname(target), { recursive: true });
    const source = path.join(build, 'model-mirror/weights', entry.path);
    if (existsSync(source)) linkSync(source, target);
  }
}
symlinkSync(weights, path.join(hub, 'export/ms', repo, 'current'));
if (legacy) {
  const target = path.join(hub, 'export/ms', legacyRepo, 'current');
  mkdirSync(target, { recursive: true });
  for (const name of ['model.int8.onnx', 'model_eb.int8.onnx', 'frontend.json', 'tokens.json']) {
    linkSync(path.join(legacySource, name), path.join(target, name));
  }
}
copyFileSync(path.join(root, 'docker/yovoice-engine.cpu.json'), path.join(build, 'audio-runtime/cpu/bin/yovoice-engine.json'));
const identity = createServer((_req, res) => { res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify({ sub: 'isolated-voice-user', enable: true, role_code: 'system_admin' })); });
await new Promise(resolve => identity.listen(0, '127.0.0.1', resolve));
const runID = randomBytes(6).toString('hex');
const db = 'v-voice-contract-pg-' + runID;
const apiContainer = 'v-voice-contract-api-' + runID;
const dbEnv = file('postgres.env', `POSTGRES_USER=vscheduler\nPOSTGRES_DB=vscheduler\nPOSTGRES_PASSWORD=${tokens.db}\n`);
const apiEnv = file('api.env', `PYTHONPATH=/src\nVVOICE_STUDIO_ENABLED=true\nVVOICE_SCHEDULER_REQUIRED=true\nVVOICE_SCHEDULER_CONFIG=/config/voice.json\nVVOICE_STUDIO_INTERNAL_TOKEN=${tokens.internal}\nVVOICE_PORT=${basePort + 1}\nMODEL_HUB_SHARED_MODELS_PATH=${hub}\nMODEL_HUB_API_URL=http://127.0.0.1:9\n`);
async function speech(endpoint, model, extra = {}) {
  const response = await fetch(endpoint + '/v1/audio/speech', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ model, input: 'Hello, welcome to V Voice.', voice: 'af_heart', response_format: 'wav', language: 'en', ...extra }), signal: AbortSignal.timeout(1800000) });
  const audio = Buffer.from(await response.arrayBuffer());
  assert.equal(response.status, 200, audio.toString().slice(0, 400));
  assert.equal(audio.toString('ascii', 0, 4), 'RIFF');
  assert(audio.length > 24000, 'empty or implausibly short speech');
  assert.equal(response.headers.get('content-type'), 'audio/wav');
  return audio;
}
try {
  containers.push(db);
  console.log('Starting isolated PostgreSQL / Scheduler / voice services');
  execFileSync('docker', ['run', '-d', '--name', db, '--env-file', dbEnv, '-p', `127.0.0.1:${basePort + 3}:5432`, process.env.VVOICE_CONTRACT_POSTGRES_IMAGE ?? 'registry.ictrek.internal/library/postgres:18'], { stdio: 'pipe', timeout: 120000 });
  let databaseReady = false;
  for (let i = 0; i < 60; i++) { try { execFileSync('docker', ['exec', db, 'pg_isready', '-h', '127.0.0.1', '-U', 'vscheduler'], { stdio: 'pipe' }); databaseReady = true; break; } catch {} await delay(500); }
  assert(databaseReady, 'Isolated PostgreSQL TCP listener did not become ready');
  start(schedulerBin, ['controller', '--config', controllerConfig, '--listen', `127.0.0.1:${basePort}`, '--ui-dir', path.join(build, 'absent-ui')], 'scheduler', { SCHEDULER_DATABASE_URL: `postgres://vscheduler:${tokens.db}@127.0.0.1:${basePort + 3}/vscheduler` });
  await ready(`http://127.0.0.1:${basePort}/health`);
  const go = start(path.join(build, 'vvoice-studio'), [], 'studio', { VVOICE_SHARED_MODELS: 'true', VVOICE_STUDIO_DATA_DIR: path.join(run, 'studio'), VVOICE_SCHEDULER_CONFIG: voiceConfig, VVOICE_STUDIO_INTERNAL_TOKEN: tokens.internal, VVOICE_AUDIOCPP_SERVER: path.join(build, 'audio-runtime/cpu/bin/audiocpp_server'), MODEL_HUB_SHARED_MODELS_PATH: hub, VOS_USERINFO_URL: `http://127.0.0.1:${identity.address().port}/userinfo` });
  await ready('http://127.0.0.1:7080/health');
  start(schedulerBin, ['agent', '--config', agentConfig], 'agent');
  const data = path.join(run, 'api-data'); mkdirSync(data);
  containers.push(apiContainer);
  execFileSync('docker', ['run', '-d', '--name', apiContainer, '--network', 'host', '--env-file', apiEnv, '-v', root + ':/src:ro', '-v', run + '/voice.json:/config/voice.json:ro', '-v', run + ':' + run + ':ro', '-v', path.join(build, 'model-mirror/weights') + ':' + path.join(build, 'model-mirror/weights') + ':ro', '-v', data + ':/data', '-w', '/src', 'swr.cn-southwest-2.myhuaweicloud.com/ictrek/v-voice:amd_20261013', 'python3', '-m', 'uvicorn', 'vvoice.main:app', '--host', '127.0.0.1', '--port', String(basePort + 1)], { stdio: 'pipe', timeout: 120000 });
  await ready(voice + '/health'); await delay(3000);
  let catalog;
  for (let i = 0; i < 120; i++) {
    catalog = await call(voice + '/api/v1/discovery', '');
    if (catalog.data.models.some(model => model.id === models[0])) break;
    await delay(500);
  }
  assert(catalog.data.models.some(model => model.id === models[0]), 'verified model did not become ready');
  console.log('PASS: verified shared GGUF weights enter real V-Voice discovery');
  const direct = await speech(voice, models[0]); file('direct.wav', direct);
  console.log('PASS: direct standard speech uses real Scheduler admission and native audio.cpp CPU inference');
  start(path.join(build, 'v-router'), [], 'router', {
    V_ROUTER_ADDR: `127.0.0.1:${basePort + 2}`, V_ROUTER_STATE_PATH: path.join(run, 'router-state.json'), V_ROUTER_USAGE_PATH: path.join(run, 'router-usage.jsonl'), V_ROUTER_SCHEDULER_CONFIG: routerConfig,
    V_ROUTER_SCHEDULER_REQUIRED: 'true', V_ROUTER_AUTH_DISABLED: 'true', V_ROUTER_V_VOICE_URLS: voice, V_ROUTER_DISCOVERY_INTERVAL: '1s', V_ROUTER_MODEL_HUB_URL: 'http://127.0.0.1:9',
  });
  await ready(router + '/healthz');
  for (let i = 0; i < 30; i++) { const result = await call(router + '/v1/models', ''); if (JSON.stringify(result.data).includes('v-voice/' + models[0])) break; await delay(1000); }
  const viaRouter = await speech(router, 'v-voice/' + models[0]); file('router.wav', viaRouter);
  const permits = (await call(scheduler + '/permits', tokens.admin)).data.items;
  assert.equal(permits.length, 2, 'direct + router execution must allocate exactly two permits, not three');
  assert(permits.every(permit => permit.state === 'released'));
  assert.equal((await call(scheduler + '/reservations', tokens.admin)).data.length, 0);
  console.log('PASS: Router dynamically discovers creative models; one actual computation consumes one released permit');
  if (legacy) {
    const form = new FormData();
    form.set('file', new Blob([readFileSync(path.join(build, 'seaco-public-sample.wav'))], { type: 'audio/wav' }), 'public-sample.wav');
    form.set('model', 'seaco-paraformer-zh'); form.set('hotwords', '魔搭');
    const response = await fetch(voice + '/v1/audio/transcriptions', { method: 'POST', body: form, signal: AbortSignal.timeout(180000) });
    const value = await response.json();
    assert.equal(response.status, 200, JSON.stringify(value));
    assert(value.text.includes('魔搭'));
    const admitted = (await call(scheduler + '/permits', tokens.admin)).data.items;
    assert.equal(admitted.length, 3); assert(admitted.every(permit => permit.state === 'released'));
    console.log('PASS: retained multipart ASR API and SeACo hotwords use real Scheduler admission');
  } else console.log('SKIP: public SeACo sample/weights were not supplied to this fixture');
  const rpc = (method, data, requestId) => call('http://127.0.0.1:7080/studio-api/call', 'isolated-user', 'POST', { method, data, requestId });
  const state = (await rpc('state.get', {})).data.result.state;
  const draft = { ...state.drafts[0], text: 'This is a queued voice test.', title: 'Queued voice check', modelId: 'kokoro-82m-q8', speaker: 'af_heart', synthesisLanguage: 'en-us' };
  assert.equal((await rpc('draft.save', draft)).status, 200);
  const key = randomBytes(16).toString('hex');
  const job = await rpc('generation.start', draft, key);
  assert.equal(job.status, 200); assert(!job.data.error, JSON.stringify(job.data));
  assert.equal((await rpc('generation.start', draft, key)).data.result, job.data.result);
  let task;
  for (let i = 0; i < 180; i++) {
    task = (await call(scheduler + '/tasks', tokens.admin)).data.items.find(task => task.app_task_id === key);
    if (task && ['succeeded', 'failed', 'cancelled'].includes(task.status)) break;
    await delay(1000);
  }
  assert.equal(task?.status, 'succeeded', JSON.stringify(task));
  assert.equal((await call(scheduler + '/tasks', tokens.admin)).data.items.filter(task => task.app_task_id === key).length, 1);
  console.log('PASS: durable creative job, duplicate request deduplication, real Agent execution and Scheduler-confirmed success');
  if (cloning) {
    const clone = await speech(router, 'v-voice/' + models[1], { input: 'Hello.', voice: 'default', reference_audio: direct.toString('base64'), reference_text: 'Hello, welcome to V Voice.' });
    file('clone.wav', clone);
    console.log('PASS: native IndexTTS voice cloning through Router using generated reference speech');
  }
  const active = readdirSync(`/proc/${go.pid}/task`).flatMap(thread => {
    try { return readFileSync(`/proc/${go.pid}/task/${thread}/children`, 'utf8').trim().split(/\s+/).filter(Boolean); }
    catch (error) { if (error.code !== 'ENOENT') throw error; return []; }
  }).join(' ');
  assert.equal(active, '', 'native child remained after confirmed completion');
  console.log('PASS: no inference child remains after confirmed completion');
} finally {
  for (const child of children.reverse()) child.kill('SIGTERM');
  await Promise.all(children.map(async child => {
    if (child.exitCode !== null || child.signalCode !== null) return;
    await Promise.race([new Promise(resolve => child.once('exit', resolve)), delay(10000)]);
    if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL');
  }));
  for (const name of containers.reverse()) { try { execFileSync('docker', ['rm', '-f', name], { stdio: 'pipe', timeout: 15000 }); } catch {} }
  identity.close();
}
