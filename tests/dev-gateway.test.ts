import { after, before, test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { mkdtempSync, writeFileSync, chmodSync, rmSync, symlinkSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { gatewayConfig, gatewayMiddleware, speechModels } from '../web/dev-gateway.ts';

const catalog = [{ key: 'sensevoice-int8', name: 'SenseVoice', kind: 'asr' }];

test('按明确能力筛选语音服务，保留网关完整 ID', () => {
  const rows = speechModels([
    { id: 'same', qualified: 'first/same', capabilities: ['asr'] },
    { id: 'same', qualified: 'second/same', endpoints: ['/v1/audio/speech'] },
    { id: 'qwen', qualified: 'chat/qwen', capabilities: ['chat'] },
    { id: 'bge', capabilities: ['embedding'] },
  ], catalog);
  assert.deepEqual(rows.map(row => [row.key, row.kind]), [['first/same', 'asr'], ['second/same', 'tts']]);
  assert.ok(rows.every(row => row.backend === 'gateway' && row.import_required));
});

test('匿名目录仅映射 V-Voice 已知公开 ID，不根据名字猜能力', () => {
  const rows = speechModels([{ id: 'v-voice/sensevoice-int8' }, { id: 'chat/sensevoice-int8' }, { id: 'sensevoice-int8' }], catalog);
  assert.deepEqual(rows.map(row => row.key), ['v-voice/sensevoice-int8']);
});

test('拒绝 URL 内嵌凭据、公开凭据文件和符号链接', () => {
  assert.throws(() => gatewayConfig('http://user:secret@localhost:22888'));
  const directory = mkdtempSync(join(tmpdir(), 'vvoice-gateway-'));
  try {
    const path = join(directory, 'token');
    writeFileSync(path, 'Bearer server-only-key', { mode: 0o600 });
    assert.deepEqual(gatewayConfig('http://localhost:22888/v1/', path), { base: 'http://localhost:22888', token: 'server-only-key' });
    symlinkSync(path, join(directory, 'link'));
    assert.throws(() => gatewayConfig('http://localhost', join(directory, 'link')));
    chmodSync(path, 0o644);
    assert.throws(() => gatewayConfig('http://localhost', path));
  } finally { rmSync(directory, { recursive: true }); }
});

let upstreamBase = '';
let clientBase = '';
const received: { path: string; authorization?: string }[] = [];
const upstream = createServer((request, response) => {
  received.push({ path: request.url ?? '', authorization: request.headers.authorization });
  response.setHeader('Content-Type', 'application/json');
  if (request.headers.authorization === 'Bearer rejected') {
    response.writeHead(401).end('{}'); return;
  }
  if (request.url === '/api/v1/models') {
    response.end(JSON.stringify({ models: [{ id: 'transcriber', qualified: 'registered/transcriber', capabilities: ['asr'], upstream_url: 'private-url' }] }));
  } else if (request.url === '/v1/models') {
    response.end(JSON.stringify({ data: [{ id: 'v-scheduler/ollama-qa/qwen3:4b-instruct' }] }));
  } else { response.writeHead(404).end('{}'); }
});
let authorization = '';
const client = createServer((request, response) => {
  gatewayMiddleware({ base: upstreamBase, token: authorization }, catalog)(request, response, () => response.writeHead(404).end());
});
before(async () => {
  await new Promise<void>(resolve => upstream.listen(0, '127.0.0.1', resolve));
  upstreamBase = `http://127.0.0.1:${(upstream.address() as { port: number }).port}`;
  await new Promise<void>(resolve => client.listen(0, '127.0.0.1', resolve));
  clientBase = `http://127.0.0.1:${(client.address() as { port: number }).port}`;
});
after(async () => { await Promise.all([new Promise(resolve => client.close(resolve)), new Promise(resolve => upstream.close(resolve))]); });

test('仅有聊天服务时返回空语音列表，网关连接仍成功', async () => {
  authorization = '';
  const response = await fetch(clientBase + '/api/v1/models');
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), []);
  const status = await fetch(clientBase + '/api/v1/scheduler/binding').then(response => response.json());
  assert.equal(status.mode, 'gateway');
  assert.equal(status.configured, true);
  assert.equal(received.at(-1)?.authorization, undefined);
});

test('私有目录使用服务端凭据，输出不泄露凭据或上游地址', async () => {
  authorization = 'server-only-key';
  const response = await fetch(clientBase + '/api/v1/models');
  const body = await response.text();
  assert.equal(JSON.parse(body)[0].key, 'registered/transcriber');
  assert.equal(received.at(-1)?.authorization, 'Bearer server-only-key');
  assert.ok(!body.includes('server-only-key') && !body.includes('private-url'));
});

test('鉴权失败不会伪装成空目录，管理请求不转发到平台', async () => {
  authorization = 'rejected';
  assert.equal((await fetch(clientBase + '/api/v1/models')).status, 401);
  const count = received.length;
  assert.equal((await fetch(clientBase + '/api/v1/models/asr/pull', { method: 'POST' })).status, 501);
  assert.equal(received.length, count);
});
