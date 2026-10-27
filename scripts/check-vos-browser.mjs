// 在构建机验证真实 VOS Go 传输；只模拟平台身份，不使用上游预览状态或模拟推理。
import assert from 'node:assert/strict';
import { createServer, request } from 'node:http';
import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
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
const legacyModels = JSON.parse(readFileSync(path.join(root, 'catalog/models.json'))).models.map(model => ({ ...model, status: 'ready' }));
// 补充真实目录中的仅导入变体，验证旧模型页也不能显示不存在的下载。
for (const model of JSON.parse(readFileSync(path.join(root, 'internal/catalog/catalog.json'))).filter(model => !model.remotePath)) {
  legacyModels.push({ key: `audiocpp-${model.id}`, name: `${model.name} ${model.precision}`, kind: 'tts', family: model.family,
    description: 'Import-only model', languages: [], modelscope_repo: 'vivibit/v-voice-audiocpp-gguf', status: 'not_installed', import_required: true });
}
const creativeModels = JSON.parse(readFileSync(path.join(root, 'internal/catalog/catalog.json'))).map(model => ({ key: `audiocpp-${model.id}`, status: 'not_installed' }));
let identities = 0;
const identity = createServer((req, res) => {
  assert.equal(req.headers.authorization, 'Bearer isolated-browser-user');
  identities++;
  res.setHeader('Content-Type', 'application/json');
  res.end(JSON.stringify({ sub: 'isolated-browser-user', enable: 1, role_code: 'system_admin' }));
});
await new Promise(resolve => identity.listen(0, '127.0.0.1', resolve));
const proxy = createServer((req, res) => {
  const pathname = new URL(req.url, 'http://localhost').pathname.replace(prefix, '');
  // 文档静态页及空目录夹具只验证多语言文档；实际推理由独立 contract 验收负责。
  if (pathname === '/api/v1/models') { res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify(legacyModels)); return; }
  if (pathname === '/api/v1/creative-models') { res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify(creativeModels)); return; }
  if (pathname === '/api/v1/hotwords' || pathname === '/api/v1/speakers') { res.setHeader('Content-Type', 'application/json'); res.end('[]'); return; }
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
  await page.exposeFunction('assertPkce', (challenge, verifier) => {
    assert.equal(challenge, createHash('sha256').update(verifier).digest('base64url'));
  });
  await page.addInitScript(() => {
    // 模拟局域网 HTTP 缺少的安全上下文 API；不能再只验 localhost。
    Object.defineProperty(crypto, 'randomUUID', { configurable: true, value: undefined, writable: true });
    Object.defineProperty(crypto, 'subtle', { configurable: true, value: undefined });
    let localeListener;
    let pkceChallenge;
    window.vos_platform = {
      getState: async () => { localeListener?.({ locale: 'en' }); return { locale: 'zh-CN' }; },
      broadcast: { on: (_event, listener) => {
        localeListener = listener;
        const update = event => listener({ locale: event.detail });
        window.addEventListener('isolated-vos-locale', update);
        return () => window.removeEventListener('isolated-vos-locale', update);
      } },
      api: { v1000: { oauth2: {
      authorize: async input => { if (input.code_challenge_method !== 'S256') throw new Error('S256 required'); pkceChallenge = input.code_challenge; return { code: 'isolated-test-code', state: input.state }; },
      token: async input => { await window.assertPkce(pkceChallenge, input.code_verifier); return { access_token: 'isolated-browser-user', expires_in: 3600 }; },
    } } } };
  });
  const base = `http://127.0.0.1:${proxy.address().port}${prefix}`;
  await page.goto(base + '/');
  await page.waitForSelector('.document-title');
  await page.waitForFunction(() => document.documentElement.lang === 'en');
  for (const [destination, selector] of [['models', '.model-grid article'], ['asr', 'main select[aria-label]'], ['tts', 'main select[aria-label]'], ['speaker', '.hotword-forms'], ['hotwords', '.hotword-forms']]) {
    await page.getByTestId(`nav-${destination}`).click();
    const service = page.frameLocator(`[data-testid="speech-service-${destination}"] iframe`);
    await service.locator(selector).first().waitFor();
    await service.locator('html[data-workbench-theme="true"]').waitFor();
    assert.equal(await service.locator('html').evaluate(element => getComputedStyle(element).getPropertyValue('--app-white').trim()), await page.locator('html').evaluate(element => getComputedStyle(element).getPropertyValue('--app-white').trim()), 'embedded page does not inherit the workbench theme');
    assert.notEqual(await service.locator('body').evaluate(element => getComputedStyle(element).backgroundColor), 'rgb(7, 11, 20)', 'old dark service background remained');
    if (destination === 'models') {
      assert.equal(await service.locator('.model-grid article').count(), legacyModels.length, 'legacy model cards missing');
      for (const model of legacyModels.filter(model => model.import_required)) {
        const card = service.locator('.model-card').filter({ has: service.getByText(model.key, { exact: true }) });
        assert.equal(await card.getByRole('button').count(), 0, 'import-only card offers an unavailable download');
        assert((await card.innerText()).includes('Administrator-provided weights required in V-Scheduler'));
      }
      await service.getByRole('tab').filter({ hasText: 'ASR' }).click();
      assert.equal(await service.locator('.model-grid article').count(), legacyModels.filter(model => model.kind === 'asr').length);
      await page.screenshot({ path: path.join(build, 'v-voice-models-integrated.png'), fullPage: true });
    }
    const untranslated = (await service.locator('main').innerText()).split('\n').filter(line => /[\u3400-\u9fff]/.test(line));
    assert.deepEqual(untranslated, [], `Chinese remained in English ${destination}: ${untranslated.join('; ')}`);
    if (destination === 'models') {
      await page.getByTestId('nav-models-creative-category').click();
      assert.equal(await page.getByTestId('nav-models-creative-category').getAttribute('aria-current'), 'page');
      assert.equal(await page.locator('[data-testid="model-management"] [role="tablist"]').count(), 0, 'duplicate top model tabs remained');
      assert.equal(await page.locator('#creative-models-panel [data-model-ids]').evaluateAll(rows => rows.flatMap(row => row.dataset.modelIds.split(' ')).length), modelCount);
      await page.getByText('Administrator-provided weights required in V-Scheduler', { exact: true }).first().waitFor();
      assert(!/[\u3400-\u9fff]/.test(await page.locator('#creative-models-panel').innerText()), 'Chinese remained in English creative model manager');
      await page.screenshot({ path: path.join(build, 'v-voice-creative-models-integrated.png'), fullPage: true });
    }
  }
  assert.equal(await page.getByTestId('nav-background-music').count(), 0);
  await page.getByTestId('nav-music').click();
  await page.getByTestId('prepare-models').click();
  await page.getByRole('dialog').getByTestId('prepare-models-panel').waitFor();
  await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).last().click();
  await page.getByTestId('nav-api-docs').click();
  const docs = page.frameLocator('[data-testid="api-documentation"] iframe');
  await docs.getByRole('tab').first().waitFor();
  for (const tab of await docs.getByRole('tab').all()) {
    await tab.click();
    const label = await tab.innerText();
    const untranslated = await docs.locator('.api-guide').evaluate(element => {
      const copy = element.cloneNode(true);
      copy.querySelectorAll('pre, code, [data-i18n="off"]').forEach(node => node.remove());
      return copy.textContent.match(/[^。\n]*[\u3400-\u9fff][^。\n]*/g) ?? [];
    });
    assert.deepEqual(untranslated, [], `Chinese remained in English API tab ${label}`);
  }
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
  await page.getByTestId('settings-open-models').click();
  await page.getByTestId('speech-service-models').waitFor();
  assert.equal(await page.getByTestId('sidebar').count(), 1, 'settings link escaped the workbench');
  assert.equal(new URL(page.url()).pathname, `${prefix}/`);
  await page.getByTestId('nav-settings').click();
  const settings = page.getByTestId('vos-settings');
  await settings.evaluate(element => { element.scrollTop = element.scrollHeight; });
  assert(await settings.evaluate(element => element.scrollTop > 0), 'VOS settings cannot scroll');
  await page.screenshot({ path: path.join(build, 'v-voice-settings-bottom.png'), fullPage: true });
  await page.getByTestId('nav-models').click();
  assert.equal(await page.getByTestId('nav-models').getAttribute('aria-expanded'), 'true');
  await page.getByTestId('nav-models').click();
  assert.equal(await page.getByTestId('nav-models-category').count(), 0);
  await page.getByTestId('nav-models').click();
  await page.getByTestId('nav-models-category').click();
  await page.getByTestId('nav-settings').click();
  assert.equal(await page.locator('[data-model-ids]').evaluateAll(rows => rows.flatMap(row => row.dataset.modelIds.split(' ')).length), modelCount);
  assert.equal(await page.getByTestId('nav-models').count(), 1);
  await page.screenshot({ path: path.join(build, 'v-voice-settings.png'), fullPage: true });
  await page.reload();
  await page.waitForSelector('.document-title');
  assert.equal(await page.locator('.document-title').inputValue(), 'V-Voice isolated QA');
  await page.screenshot({ path: path.join(build, 'v-voice-studio.png'), fullPage: true });
  await page.goto(base + '/service/');
  await page.getByTestId('return-workbench').click();
  await page.waitForSelector('.document-title');
  assert.equal(await page.locator('.document-title').inputValue(), 'V-Voice isolated QA', 'returning from the compatibility console lost the draft');
  for (const locale of ['ja', 'ko', 'es', 'fr', 'de', 'pt-BR', 'ru', 'it', 'vi']) {
    await page.evaluate(locale => window.dispatchEvent(new CustomEvent('isolated-vos-locale', { detail: locale })), locale);
    await page.waitForFunction(locale => document.documentElement.lang === locale, locale);
    assert.equal(await page.locator('.document-title').inputValue(), 'V-Voice isolated QA', `locale ${locale} lost the draft`);
  }
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('isolated-vos-locale', { detail: 'en' })));
  await page.waitForFunction(() => document.documentElement.lang === 'en');
  assert(identities > 0);
  assert.deepEqual(errors, []);
  console.log(`PASS: V-Voice title/logo, ${modelCount} model variants, real Go persistence, reload, 12 VOS locales and event/snapshot ordering without draft loss, dedicated API docs in EN/zh-CN/zh-TW without untranslated EN labels; native inference not tested`);
} finally {
  await browser?.close();
  child.kill('SIGTERM');
  await new Promise(resolve => { if (child.exitCode !== null) resolve(); else child.once('exit', resolve); });
  proxy.close(); identity.close();
}
