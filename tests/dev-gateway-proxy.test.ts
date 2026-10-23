import { after, before, test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createServer as createViteServer, type ViteDevServer } from '../web/node_modules/vite/dist/node/index.js';

const root = fileURLToPath(new URL('../', import.meta.url));
const directory = mkdtempSync(join(tmpdir(), 'vvoice-proxy-'));
const token = 'server-only-gateway-test-key';
const calls: { path: string; body: string; authorization?: string; cookie?: string; apiKey?: string }[] = [];
const upstream = createServer(async (request, response) => {
  let body = '';
  for await (const chunk of request) body += chunk;
  calls.push({ path: request.url ?? '', body, authorization: request.headers.authorization,
    cookie: request.headers.cookie, apiKey: request.headers['x-api-key'] as string | undefined });
  if (request.url === '/api/v1/models') {
    response.setHeader('Content-Type', 'application/json');
    response.end(JSON.stringify({ models: [
      { id: 'asr-native', qualified: 'pool/asr-native', capabilities: ['asr'] },
      { id: 'tts-native', qualified: 'pool/tts-native', capabilities: ['tts'] },
    ] }));
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
const previous = { gateway: process.env.VVOICE_GATEWAY_BASE, file: process.env.VVOICE_GATEWAY_TOKEN_FILE, service: process.env.VITE_VOS_SERVICE_BASE };
before(async () => {
  await new Promise<void>(resolve => upstream.listen(0, '127.0.0.1', resolve));
  writeFileSync(join(directory, 'token'), token, { mode: 0o600 });
  process.env.VVOICE_GATEWAY_BASE = `http://127.0.0.1:${(upstream.address() as { port: number }).port}`;
  process.env.VVOICE_GATEWAY_TOKEN_FILE = join(directory, 'token');
  process.env.VITE_VOS_SERVICE_BASE = 'http://127.0.0.1:7080';
  vite = await createViteServer({ root: join(root, 'web'), configFile: join(root, 'web/vite.config.ts'),
    logLevel: 'error', server: { host: '127.0.0.1', port: 0, strictPort: false } });
  await vite.listen();
  base = `http://127.0.0.1:${(vite.httpServer!.address() as { port: number }).port}`;
});
after(async () => {
  await vite?.close();
  await new Promise(resolve => upstream.close(resolve));
  for (const [name, value] of Object.entries({ VVOICE_GATEWAY_BASE: previous.gateway, VVOICE_GATEWAY_TOKEN_FILE: previous.file, VITE_VOS_SERVICE_BASE: previous.service })) {
    if (value === undefined) delete process.env[name]; else process.env[name] = value;
  }
  rmSync(directory, { recursive: true });
});

test('实际 Vite 代理：目录、ASR 文件、TTS 音频和网关错误完整往返', async () => {
  const models = await fetch(base + '/api/v1/models').then(response => response.json());
  assert.deepEqual(models.map((model: { key: string }) => model.key), ['pool/asr-native', 'pool/tts-native']);
  assert.equal(models[1].voices['remote-voice'].sid, 3);
  const headers = { Authorization: 'Bearer browser-development-token', Cookie: 'browser-session=private', 'X-API-Key': 'browser-key' };
  const speech = await fetch(base + '/v1/audio/speech', { method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify({ model: models[1].key, voice: 'remote-voice', input: 'hello' }) });
  assert.equal(speech.headers.get('content-type'), 'audio/wav');
  assert.equal(await speech.text(), 'RIFF-from-platform');
  assert.equal(JSON.parse(calls.at(-1)!.body).model, 'pool/tts-native');
  const form = new FormData();
  form.set('model', models[0].key);
  form.set('file', new Blob(['RIFF-audio-input']), 'sample.wav');
  const asr = await fetch(base + '/v1/audio/transcriptions', { method: 'POST', headers, body: form });
  assert.equal((await asr.json()).text, 'Transcribed by platform service');
  assert.ok(calls.at(-1)!.body.includes('pool/asr-native') && calls.at(-1)!.body.includes('RIFF-audio-input'));
  const busy = await fetch(base + '/v1/chat/completions', { method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' }, body: '{}' });
  assert.equal(busy.status, 429);
  assert.equal(busy.headers.get('retry-after'), '2');
  assert.equal((await busy.json()).error.message, 'WAIT_MEMORY_HEADROOM');
  assert.ok(calls.every(call => call.authorization === `Bearer ${token}` && !call.cookie && !call.apiKey));
  assert.ok(calls.every(call => !call.path.includes('/permits') && !call.path.includes('/executors')));
});
