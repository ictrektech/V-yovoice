import type { IncomingMessage, ServerResponse } from 'node:http';
import { readFileSync, openSync, closeSync, fstatSync, constants } from 'node:fs';

type CatalogModel = {
  key: string; name: string; kind: string; family?: string; languages?: string[];
  voices?: Record<string, { sid: number; language: string } | undefined>;
};
type GatewayModel = { id: string; qualified?: string; kind?: string; capabilities?: string[]; endpoints?: string[] };

export function gatewayConfig(base: string, tokenFile?: string) {
  const url = new URL(base);
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash) {
    throw new Error('VVOICE_GATEWAY_BASE 必须为不含凭据的 HTTP(S) 网关地址');
  }
  const normalized = url.href.replace(/\/+$/, '').replace(/\/v1$/, '');
  let token = '';
  if (tokenFile) {
    const file = openSync(tokenFile, constants.O_RDONLY | constants.O_NOFOLLOW);
    try {
      const info = fstatSync(file);
      if (!info.isFile() || (info.mode & 0o077) || info.size > 4096) throw new Error('网关凭据文件必须为普通私有文件（0600）');
      token = readFileSync(file, 'utf8').trim().replace(/^Bearer /, '');
    } finally { closeSync(file); }
    if (!token || /\s/.test(token)) throw new Error('网关凭据格式无效');
  }
  return { base: normalized, token };
}

export function speechModels(rows: GatewayModel[], catalog: CatalogModel[]) {
  return rows.flatMap(row => {
    // 匿名 OpenAI 目录没有能力字段，只匹配 V-Voice 已知的完整公开 ID。
    const known = catalog.find(model => (row.qualified ?? row.id) === `v-voice/${model.key}`);
    const capabilities = [...(row.capabilities ?? []), ...(row.endpoints ?? []).map(value => value.replace(/^\/?v1\//, '').replace(/^\//, '')), row.kind ?? ''];
    const kind = capabilities.some(value => ['asr', 'transcription', 'transcriptions', 'audio/transcriptions'].includes(value)) ? 'asr'
      : capabilities.some(value => ['tts', 'speech', 'audio/speech'].includes(value)) ? 'tts'
        : capabilities.includes('speaker') ? 'speaker' : known?.kind;
    if (!kind) return [];
    const voices: Record<string, { sid: number; language: string }> = {};
    for (const [key, voice] of Object.entries(known?.voices ?? {})) if (voice) voices[key] = voice;
    return [{ key: row.qualified ?? row.id, name: known?.name ?? row.qualified ?? row.id, kind,
      family: known?.family ?? 'V-Scheduler', backend: 'gateway', status: 'ready', loaded: false,
      languages: known?.languages ?? [], voices, modelscope_repo: '',
      import_required: true, description: '由 V-Scheduler 已接入的模型服务提供推理。' }];
  });
}

class GatewayError extends Error {
  status: number;
  constructor(status: number, message: string) { super(message); this.status = status; }
}

export function gatewayMiddleware(config: { base: string; token: string }, catalog: CatalogModel[]) {
  async function get(path: string) {
    let response: Response;
    try {
      response = await fetch(config.base + path, { headers: config.token ? { Authorization: `Bearer ${config.token}` } : {},
        signal: AbortSignal.timeout(10_000), redirect: 'error' });
    } catch { throw new GatewayError(502, '无法连接 V-Scheduler 模型网关，请检查 VVOICE_GATEWAY_BASE。'); }
    if (!response.ok) throw new GatewayError(response.status, response.status === 401 || response.status === 403
      ? 'V-Scheduler 拒绝访问，请通过 VVOICE_GATEWAY_TOKEN_FILE 配置有效的 VOS 用户凭据或网关 Key。'
      : `V-Scheduler 模型目录请求失败（HTTP ${response.status}）。`);
    return response.json();
  }
  async function models() {
    const value = await get(config.token ? '/api/v1/models' : '/v1/models');
    const rows: GatewayModel[] = config.token ? value.models : value.data;
    if (!Array.isArray(rows) || rows.some(row => typeof row.id !== 'string')) throw new GatewayError(502, 'V-Scheduler 模型目录格式无效。');
    const speech = speechModels(rows, catalog);
    for (const model of speech.filter(model => model.kind === 'tts')) {
      try {
        const value = await get(`/v1/audio/voices?model=${encodeURIComponent(model.key)}`);
        const voices: { id: string; sid?: number; language?: string }[] = value.voices ?? value.data;
        if (Array.isArray(voices)) model.voices = Object.fromEntries(voices.filter(voice => typeof voice.id === 'string')
          .map(voice => [voice.id, { sid: voice.sid ?? 0, language: voice.language ?? '' }]));
      } catch {
        // 部分上游没有音色查询接口；仅保留已知 V-Voice 契约的音色，不猜测 ID。
      }
    }
    return speech;
  }
  return async (request: IncomingMessage, response: ServerResponse, next: () => void) => {
    const path = new URL(request.url ?? '/', 'http://localhost').pathname;
    if (!path.startsWith('/api/')) { next(); return; }
    const send = (status: number, body: unknown) => {
      response.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' }).end(JSON.stringify(body));
    };
    try {
      if (request.method !== 'GET') {
        send(501, { detail: '网关客户端不管理模型文件、热词或声纹库，请在 VOS 对应服务中管理。' }); return;
      }
      switch (path) {
        case '/api/v1/models': send(200, await models()); return;
        case '/api/v1/creative-models': send(200, []); return;
        case '/api/v1/scheduler/binding':
          await get('/v1/models');
          send(200, { mode: 'gateway', configured: true, approved_model_count: 0 }); return;
        case '/api/v1/discovery':
          send(200, { service_id: 'v-voice-gateway-client', mode: 'gateway', authentication: 'gateway', models: await models() }); return;
        default: send(501, { detail: '此接口属于 V-Voice 原生服务，V-Scheduler 网关未提供此管理能力。' });
      }
    } catch (error) {
      send(error instanceof GatewayError ? error.status : 502, { detail: error instanceof GatewayError ? error.message : 'V-Scheduler 模型目录响应无效。' });
    }
  };
}
