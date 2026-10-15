// 在构建机验证真实 VOS Go 传输；只模拟平台身份，不使用上游预览状态或模拟推理。
import assert from 'node:assert/strict';
import { createServer, request } from 'node:http';
import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';
import { mkdirSync, mkdtempSync, openSync, readFileSync } from 'node:fs';
import path from 'node:path';

const root = path.resolve(import.meta.dirname, '..');
const build = process.env.VVOICE_BROWSER_BUILD;
assert(build && build.startsWith(path.join(process.env.HOME, 'dev/build') + '/'));
mkdirSync(build, { recursive: true });
const data = mkdtempSync(path.join(build, 'browser-'));
const require = createRequire(path.join(root, 'web/package.json'));
const { chromium } = require('@playwright/test');
const prefix = '/app/com.ictrek.v-voice';
const modelCount = JSON.parse(readFileSync(path.join(root, 'internal/catalog/catalog.json'))).length;
let identities = 0;
const identity = createServer((req, res) => {
  assert.equal(req.headers.authorization, 'Bearer isolated-browser-user');
  identities++;
  res.setHeader('Content-Type', 'application/json');
  res.end(JSON.stringify({ sub: 'isolated-browser-user', enable: true, role_code: 'system_admin' }));
});
await new Promise(resolve => identity.listen(0, '127.0.0.1', resolve));
const proxy = createServer((req, res) => {
  const pathname = new URL(req.url, 'http://localhost').pathname.replace(prefix, '');
  // 文档静态页及空目录夹具只验证多语言文档；实际推理由独立 contract 验收负责。
  if (pathname === '/api/v1/models') { res.setHeader('Content-Type', 'application/json'); res.end('[]'); return; }
  if (pathname.startsWith('/service/')) {
    const file = path.resolve(root, 'frontend/dist', pathname.slice('/service/'.length) || 'index.html');
    if (!file.startsWith(path.join(root, 'frontend/dist') + path.sep)) { res.writeHead(404); res.end(); return; }
    try {
      res.setHeader('Content-Type', ({ '.js': 'application/javascript', '.css': 'text/css', '.png': 'image/png' })[path.extname(file)] ?? 'text/html');
      res.end(readFileSync(file));
    } catch { res.writeHead(404); res.end(); }
    return;
  }
  const upstream = request({ hostname: '127.0.0.1', port: 7080, path: req.url.startsWith(prefix) ? req.url.slice(prefix.length) || '/' : req.url, method: req.method, headers: req.headers }, reply => {
    res.writeHead(reply.statusCode, reply.headers); reply.pipe(res);
  });
  upstream.on('error', () => { res.statusCode = 503; res.end('Isolated backend unavailable'); });
  req.pipe(upstream);
});
await new Promise(resolve => proxy.listen(0, '127.0.0.1', resolve));
const child = spawn(path.join(build, 'vvoice-studio'), [], {
  env: { ...process.env, VVOICE_STUDIO_DATA_DIR: data, VVOICE_STUDIO_ASSETS: path.join(root, 'web/dist'),
    VOS_USERINFO_URL: `http://127.0.0.1:${identity.address().port}/userinfo`,
    VVOICE_SCHEDULER_CONFIG: path.join(data, 'absent-config.json'), MODEL_HUB_SHARED_MODELS_PATH: path.join(data, 'modelhub') },
  stdio: ['ignore', openSync(path.join(data, 'server.log'), 'a'), 'inherit'],
});
let browser;
try {
  for (let i = 0; i < 100; i++) {
    if (child.exitCode !== null) throw new Error('Isolated backend failed to start');
    try { if ((await fetch('http://127.0.0.1:7080/health')).ok) break; } catch {}
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || undefined });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.addInitScript(() => {
    let localeListener;
    window.vos_platform = {
      getState: async () => { localeListener?.({ locale: 'en' }); return { locale: 'zh-CN' }; },
      broadcast: { on: (_event, listener) => {
        localeListener = listener;
        const update = event => listener({ locale: event.detail });
        window.addEventListener('isolated-vos-locale', update);
        return () => window.removeEventListener('isolated-vos-locale', update);
      } },
      api: { v1000: { oauth2: {
      authorize: async input => ({ code: 'isolated-test-code', state: input.state }),
      token: async () => ({ access_token: 'isolated-browser-user', expires_in: 3600 }),
    } } } };
  });
  const base = `http://127.0.0.1:${proxy.address().port}${prefix}`;
  await page.goto(base + '/');
  await page.waitForSelector('.document-title');
  await page.waitForFunction(() => document.documentElement.lang === 'en');
  await page.getByTestId('nav-api-docs').click();
  const docs = page.frameLocator('[data-testid="api-documentation"] iframe');
  await docs.getByRole('tab', { name: 'Creative speech and scheduling', exact: true }).click();
  await docs.getByText('Voice cloning, design and emotion control', { exact: true }).waitFor();
  assert(!/[\u3400-\u9fff]/.test(await docs.locator('.api-guide').innerText()), 'Chinese labels remained in English creative API docs');
  assert(await docs.locator('html').evaluate(element => element.scrollWidth <= element.clientWidth + 1), 'API documentation overflowed its embedded viewport');
  await page.screenshot({ path: path.join(build, 'v-voice-api-en.png'), fullPage: true });
  await docs.locator('.language-select').selectOption('zh-TW');
  await docs.getByRole('heading', { name: '創作語音與排程', exact: true }).waitFor();
  await docs.getByText('聲音複製、設計與情緒控制', { exact: true }).waitFor();
  await page.screenshot({ path: path.join(build, 'v-voice-api-zh-tw.png'), fullPage: true });
  await docs.locator('.language-select').selectOption('zh-CN');
  await docs.getByRole('heading', { name: '创作语音与调度', exact: true }).waitFor();
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('isolated-vos-locale', { detail: 'zh-TW' })));
  await page.waitForFunction(() => document.documentElement.lang === 'zh-TW');
  assert.equal(await page.getByTestId('nav-api-docs').textContent(), 'API 文件');
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('isolated-vos-locale', { detail: 'en' })));
  await page.waitForFunction(() => document.documentElement.lang === 'en');
  await page.locator('[data-testid="sidebar"] .project-link').first().click();
  await page.waitForSelector('.document-title', { state: 'visible' });
  assert.equal(await page.title(), 'V-Voice');
  assert.equal(await page.locator('.browser-titlebar b').textContent(), 'V-Voice');
  assert(await page.locator('.browser-titlebar img').evaluate(img => img.complete && img.naturalWidth > 0));
  await page.locator('.document-title').fill('V-Voice isolated QA');
  let state;
  for (let i = 0; i < 40; i++) {
    const result = await fetch(base + '/studio-api/call', { method: 'POST', headers: { Authorization: 'Bearer isolated-browser-user', 'Content-Type': 'application/json' }, body: JSON.stringify({ method: 'state.get', data: {} }) });
    state = await result.json();
    if (state.result.state.drafts.some(d => d.title === 'V-Voice isolated QA')) break;
    await new Promise(resolve => setTimeout(resolve, 250));
  }
  assert(state.result.state.drafts.some(d => d.title === 'V-Voice isolated QA'), 'real backend did not persist draft');
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('isolated-vos-locale', { detail: 'zh-CN' })));
  await page.waitForFunction(() => document.documentElement.lang === 'zh-CN');
  assert.equal(await page.locator('.document-title').inputValue(), 'V-Voice isolated QA');
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('isolated-vos-locale', { detail: 'en' })));
  await page.waitForFunction(() => document.documentElement.lang === 'en');
  assert.equal(state.result.catalog.length, modelCount, 'upstream model catalog was truncated');
  await page.getByTestId('nav-settings').click();
  await page.waitForSelector('[data-model-id]');
  assert.equal(await page.locator('[data-model-id]').count(), modelCount);
  assert.equal(await page.getByTestId('nav-speech-service').getAttribute('href'), './service/');
  await page.screenshot({ path: path.join(build, 'v-voice-settings.png'), fullPage: true });
  await page.reload();
  await page.waitForSelector('.document-title');
  assert.equal(await page.locator('.document-title').inputValue(), 'V-Voice isolated QA');
  await page.screenshot({ path: path.join(build, 'v-voice-studio.png'), fullPage: true });
  assert(identities > 0);
  assert.deepEqual(errors, []);
  console.log(`PASS: V-Voice title/logo, ${modelCount} model variants, real Go persistence, reload, VOS locale event/snapshot ordering without draft loss, dedicated API docs in EN/zh-CN/zh-TW without untranslated EN labels; native inference not tested`);
} finally {
  await browser?.close();
  child.kill('SIGTERM');
  await new Promise(resolve => { if (child.exitCode !== null) resolve(); else child.once('exit', resolve); });
  proxy.close(); identity.close();
}
