import { test, expect } from '@playwright/test';
import { emptyState } from '../src/shared/workbench';
import { readFileSync } from 'node:fs';

const catalog = JSON.parse(readFileSync(new URL('../../internal/catalog/catalog.json', import.meta.url), 'utf8')).models;

for (const locale of ['zh-CN', 'en-US']) {
  test(`VOS API 文档同源内嵌可见：${locale}`, async ({ page }) => {
    test.skip(process.env.VITE_VOS !== 'true', '需要 VOS 前端构建');
    await page.addInitScript((locale) => {
      localStorage.setItem('v-voice-creator-locale', locale);
      window.vos_platform = { getState: async () => ({ locale }), api: { v1000: { oauth2: {
        authorize: async input => ({ code: 'fixture-code', state: input.state }),
        token: async () => ({ access_token: 'fixture-token', expires_in: 3600 }),
      } } } };
    }, locale);
    const state = emptyState();
    state.preferences.introSeen = true;
    state.preferences.tourSeen = true;
    await page.route('**/api/v1/scheduler/binding', route => route.fulfill({ json: { configured: true, approved_model_count: 0 } }));
    await page.route('**/api/v1/discovery', route => route.fulfill({ json: { models: [] } }));
    await page.route('**/api/v1/creative-models', route => route.fulfill({ json: [] }));
    await page.route('**/studio-api/call', route => route.fulfill({ json: { result: { state, catalog, catalogRevision: 'fixture', assistant: { available: false } } } }));
    await page.route('**/service/?**', route => route.fulfill({ contentType: 'text/html', body: '<!doctype html><main><h1>API contract fixture</h1></main>' }));
    await page.goto('/');
    await page.getByTestId('nav-api-docs').click();
    const frame = page.getByTestId('api-documentation').locator('iframe');
    await expect(frame).toHaveAttribute('src', new RegExp(`locale=${locale}`));
    await expect(page.frameLocator('[data-testid="api-documentation"] iframe').getByRole('heading', { name: 'API contract fixture' })).toBeVisible();
  });
}
