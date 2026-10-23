import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { test, expect } from '@playwright/test';
import { emptyState } from '../src/shared/workbench';

test('语音服务入口不回退到工作台首页', async ({ request }) => {
  const response = await request.get('/service/?page=models&standalone=1');
  const body = await response.text();
  expect(body).not.toContain('/src/main.tsx');
  if (existsSync(fileURLToPath(new URL('../../frontend/dist/index.html', import.meta.url)))) {
    expect(response.status()).toBe(200);
    expect(body).toContain('./assets/');
    const config = await request.get('/service/runtime-config.js');
    expect(config.headers()['content-type']).toContain('text/javascript');
  } else {
    expect(response.status()).toBe(503);
    expect(body).toContain('语音管理页面尚未构建');
  }
  const traversal = await request.get('/service/%2e%2e%2fpackage.json');
  expect(traversal.status()).toBe(404);
});

test('本地工作台提供语音模型目录而不进入登录', async ({ request }) => {
  test.skip(!process.env.VITE_VOS_SERVICE_BASE, '需要本地真实后端');
  const models = await request.get('/api/v1/models');
  expect(models.status()).toBe(200);
  expect(Array.isArray(await models.json())).toBe(true);
  const discovery = await request.get('/api/v1/discovery');
  expect(discovery.status()).toBe(200);
  expect((await discovery.json()).authentication).toBe(process.env.VVOICE_GATEWAY_BASE ? 'gateway' : 'none');
});

test('语音模型及相关导航只显示一套工作台侧栏', async ({ page }) => {
  test.skip(!process.env.VITE_VOS_SERVICE_BASE && process.env.VITE_VOS !== 'true', '需要 VOS 导航');
  test.skip(!existsSync(fileURLToPath(new URL('../../frontend/dist/index.html', import.meta.url))), '需要构建语音管理页面');
  const state = emptyState();
  await page.addInitScript(() => {
    localStorage.setItem('v-voice-creator-locale', 'zh-CN');
    window.vos_platform = { api: { v1000: { oauth2: {
      authorize: async input => ({ code: 'test-code', state: input.state }),
      token: async () => ({ access_token: 'test-user' }),
    } } } };
  });
  await page.route('**/studio-api/call', route => route.fulfill({ json: { result: { state: { ...state, preferences: { ...state.preferences, uiLocale: 'zh-CN' } }, catalog: [] } } }));
  await page.route('**/api/v1/**', route => route.fulfill({ json: [] }));
  await page.goto('/');
  for (const destination of ['models-category', 'asr', 'tts', 'speaker', 'hotwords', 'api-docs']) {
    await page.getByTestId(`nav-${destination}`).click();
    const frame = page.frameLocator('iframe');
    await expect(frame.locator('.shell > main')).toBeVisible();
    await expect(frame.getByTestId('sidebar')).toHaveCount(0);
    await expect(page.getByTestId('sidebar')).toHaveCount(1);
  }
});
