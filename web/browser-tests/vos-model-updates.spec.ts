import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { emptyState } from '../src/shared/workbench';

const catalog = JSON.parse(readFileSync(new URL('../../internal/catalog/catalog.json', import.meta.url), 'utf8'));
const previous = JSON.parse(readFileSync(new URL('../../internal/catalog/previous-model-files.json', import.meta.url), 'utf8'));

test('VOS 旧模型更新使用管理员共享更新接口，时间轴导入走真实传输', async ({ page }) => {
  test.skip(process.env.VITE_VOS !== 'true', '需要 VOS 构建');
  await page.addInitScript(() => {
    localStorage.setItem('v-voice-creator-locale', 'zh-CN');
    window.vos_platform = { getState: async () => ({ locale: 'zh-CN' }), api: { v1000: { oauth2: {
      authorize: async input => ({ code: 'fixture-code', state: input.state }),
      token: async () => ({ access_token: 'fixture-token', expires_in: 3600 }),
    } } } };
  });
  const state = emptyState();
  const id = 'index-2.5-q8';
  state.models = [{ id, path: '/modelhub/shared/index.gguf', managed: false, sha256: previous.find((model: { id: string }) => model.id === id).sha256 }];
  let updated = false;
  let imported = false;
  await page.route('**/api/v1/scheduler/binding', route => route.fulfill({ json: { configured: true, approved_model_count: 1 } }));
  await page.route('**/api/v1/creative-models', route => route.fulfill({ json: [{ key: `audiocpp-${id}`, status: 'ready' }] }));
  await page.route('**/api/v1/models/audiocpp-index-2.5-q8/pull?force=true', route => {
    expect(route.request().headers().authorization).toBe('Bearer fixture-token');
    updated = true;
    return route.fulfill({ status: 202, json: { status: 'active' } });
  });
  await page.route('**/studio-api/call', route => {
    const request = route.request().postDataJSON();
    if (request.method === 'timeline.fromGeneration') {
      expect(request.data.id).toBe('confirmed-generation');
      imported = true;
      return route.fulfill({ json: { result: { id: 'server-asset', name: 'Server audio', fileName: 'server.wav', duration: 1 } } });
    }
    return route.fulfill({ json: { result: { state, catalog, catalogRevision: 'new-catalog', assistant: { available: false } } } });
  });
  await page.goto('/');
  await page.getByTestId('nav-models-creative-category').click();
  await page.locator(`[data-model-id="${id}"]`).getByRole('button', { name: '更新', exact: true }).click();
  await expect.poll(() => updated).toBeTruthy();
  const asset = await page.evaluate(async () => {
    const { importTimelineGeneration } = await import('/src/shared/lib/client.ts');
    return importTimelineGeneration('confirmed-generation');
  });
  expect(imported).toBeTruthy();
  expect(asset.id).toBe('server-asset');
});
