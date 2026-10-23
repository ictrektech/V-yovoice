import type { State } from '../workbench';
import { parseCallError } from './call-error';
import { sha256 } from '@noble/hashes/sha2.js';

// VOS 构建只使用真实服务；普通上游浏览器预览仍使用模拟后端。
export const isVos = import.meta.env.VITE_VOS === 'true';
const base = '/app/com.ictrek.v-voice';
type OAuth = {
  authorize: (input: Record<string, string>) => Promise<{ code: string; state: string }>;
  token: (input: Record<string, string>) => Promise<{ access_token: string; expires_in?: number }>;
};
declare global { interface Window { vos_platform?: {
  api?: { v1000?: { oauth2?: OAuth } };
  getState?: () => Promise<{ locale?: unknown }>;
  broadcast?: { on: (event: 'locale-change', listener: (state: { locale?: unknown }) => void) => () => void };
} } }
let session: { token: string; expires: number } | undefined;
let signingIn: Promise<string> | undefined;

function base64url(value: Uint8Array) {
  return btoa(String.fromCharCode(...value)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

async function signIn(): Promise<string> {
  let oauth: OAuth | undefined;
  for (let i = 0; i < 100; i++) {
    oauth = window.vos_platform?.api?.v1000?.oauth2;
    if (oauth) break;
    await new Promise(resolve => setTimeout(resolve, 50));
  }
  if (!oauth) throw new Error('Please open V-Voice from VOS / 请从 VOS 打开 V-Voice');
  const verifier = base64url(crypto.getRandomValues(new Uint8Array(32)));
  const state = base64url(crypto.getRandomValues(new Uint8Array(24)));
  const nonce = base64url(crypto.getRandomValues(new Uint8Array(24)));
  const challenge = base64url(sha256(new TextEncoder().encode(verifier)));
  const authorization = await oauth.authorize({ client_id: 'com.ictrek.v-voice', response_type: 'code', scope: 'openid profile email', state, nonce, code_challenge: challenge, code_challenge_method: 'S256' });
  if (authorization.state !== state || !authorization.code) throw new Error('VOS OIDC state mismatch');
  const tokens = await oauth.token({ grant_type: 'authorization_code', client_id: 'com.ictrek.v-voice', code: authorization.code, code_verifier: verifier });
  if (!tokens.access_token) throw new Error('VOS access token missing');
  session = { token: tokens.access_token, expires: Date.now() + Math.max(30, (tokens.expires_in ?? 3600) - 60) * 1000 };
  return session.token;
}

async function token() {
  if (session && session.expires > Date.now()) return session.token;
  signingIn ??= signIn().finally(() => { signingIn = undefined; });
  return signingIn;
}

export async function vosFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  headers.set('Authorization', `Bearer ${await token()}`);
  const response = await fetch(`${base}${path}`, { ...init, headers });
  if (response.status === 401) { session = undefined; throw new Error('VOS sign-in expired / VOS 登录已过期'); }
  return response;
}

export async function vosCall<T>(method: string, data: unknown): Promise<T> {
  const requestId = crypto.randomUUID().replaceAll('-', '');
  const response = await vosFetch('/studio-api/call', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ method, data, requestId }) });
  if (!response.ok) throw new Error((await response.text()).slice(0, 300));
  const result = await response.json();
  if (result.error) throw parseCallError(result.error);
  return result.result as T;
}

// 一个共享轮询循环，卸载后取消；不为每个 React 订阅重复建立连接。
const listeners = new Set<(state: State) => void>();
let polling: ReturnType<typeof setTimeout> | undefined;
let running = false;
async function poll() {
  if (running || !listeners.size) return;
  running = true;
  try { const result = await vosCall<{ state: State }>('state.get', {}); listeners.forEach(listener => listener(result.state)); }
  catch { /* 主调用展示鉴权/服务错误，轮询失败不覆盖用户正在编辑的表单。 */ }
  finally { running = false; if (listeners.size) polling = setTimeout(poll, 1500); }
}
export function subscribeVos(listener: (state: State) => void) {
  listeners.add(listener);
  if (!polling && !running) void poll();
  return () => { listeners.delete(listener); if (!listeners.size) { clearTimeout(polling); polling = undefined; } };
}

export async function vosMedia(kind: 'voices' | 'outputs', file: string) {
  const response = await vosFetch(`/studio-api/media/${kind}/${encodeURIComponent(file)}`);
  if (!response.ok) throw new Error('Audio unavailable');
  return URL.createObjectURL(await response.blob());
}
