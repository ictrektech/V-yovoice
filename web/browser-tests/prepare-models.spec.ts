import { test, expect } from '@playwright/test';
import { emptyState } from '../src/shared/workbench';
import { readFileSync } from 'node:fs';
const catalog = JSON.parse(readFileSync(new URL('../../internal/catalog/catalog.json', import.meta.url), 'utf8'));

test('各功能页可原地准备相关模型，关闭不离开原页面，未暴露 PyTorch 配乐', async ({ page }) => {
  test.setTimeout(60000);
  test.skip(process.env.VITE_VOS !== 'true', '需要 VOS 构建');
  await page.addInitScript(() => {
    localStorage.setItem('v-voice-creator-locale', 'zh-CN');
    window.vos_platform = { getState: async () => ({ locale: 'zh-CN' }), api: { v1000: { oauth2: {
      authorize: async input => ({ code: 'fixture-code', state: input.state }),
      token: async () => ({ access_token: 'fixture-token', expires_in: 3600 }),
    } } } };
  });
  await page.route('**/service/**', route => route.fulfill({ contentType: 'text/html', body: '<html><body>Speech model preparation</body></html>' }));
  const calls: { method: string; data: { id?: string } }[] = [];
  let downloading = '';
  await page.route('**/studio-api/call', route => {
    const request = route.request().postDataJSON();
    calls.push(request);
    if (request.method === 'model.download') downloading = request.data.id;
    if (request.method === 'model.cancel') downloading = '';
    return route.fulfill({ json: { result: { state: emptyState(), catalog, engine: { version: 'v0.9.1', minimum: 'v0.9.1' }, desktop: false } } });
  });
  await page.route('**/api/v1/scheduler/binding', route => route.fulfill({ json: { configured: true, approved_model_count: 1 } }));
  await page.route('**/api/v1/creative-models', route => route.fulfill({ json: downloading ? [{ key: `audiocpp-${downloading}`, status: 'downloading', downloaded_bytes: 100, total_bytes: 1000 }] : [] }));
  await page.goto('/');
  await expect(page.getByTestId('nav-background-music')).toHaveCount(0);
  for (const destination of ['asr', 'tts', 'speaker', 'hotwords', 'text', 'story', 'music', 'score', 'characters', 'settings', 'api-docs']) {
    const navigation = destination === 'score' ? 'music' : destination;
    await page.getByTestId(`nav-${navigation}`).click();
    if (destination === 'score') await page.getByRole('tab', { name: /编曲/ }).click();
    await page.getByTestId('prepare-models').click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    const speech = destination === 'hotwords' ? 'asr' : destination;
    if (['asr', 'tts', 'speaker'].includes(speech)) {
      await expect(dialog.locator('iframe')).toHaveAttribute('src', new RegExp(`kind=${speech}`));
    } else {
      const rows = dialog.locator('[data-model-id]');
      await expect(rows.first()).toBeVisible();
      const ids = await rows.evaluateAll(items => items.map(item => item.getAttribute('data-model-id')));
      if (destination === 'music') {
        expect(ids.every(id => id?.startsWith('ace-step-') || id?.startsWith('yue2-') || id?.startsWith('sheetsage2-') || id?.startsWith('lyric-align-') || id?.endsWith('-sf2'))).toBeTruthy();
        expect(ids).toContain('sheetsage2-orig');
        expect(ids).toContain('lyric-align-q8');
        expect(ids.some(id => id?.endsWith('-sf2'))).toBeTruthy();
      }
      if (destination === 'score') expect(ids.every(id => id?.endsWith('-sf2'))).toBeTruthy();
      if (destination === 'music') {
        await dialog.getByRole('button', { name: '下载模型', exact: true }).first().click();
        await expect.poll(() => calls.find(call => call.method === 'model.download')?.data.id).toBe(ids[0]);
        await dialog.getByRole('button', { name: '暂停', exact: true }).click();
        await expect.poll(() => calls.some(call => call.method === 'model.cancel' && call.data.id === ids[0])).toBeTruthy();
        if (process.env.VVOICE_QA_DIR) {
          const hint = dialog.getByText('在这里下载或继续准备当前页面所需模型。关闭后回到原页面，下载会在后台继续。');
          expect(await hint.evaluate(element => element.clientHeight >= element.scrollHeight)).toBeTruthy();
          await page.screenshot({ path: `${process.env.VVOICE_QA_DIR}/prepare-models-desktop.png` });
          await page.setViewportSize({ width: 900, height: 800 });
          const bounds = await dialog.boundingBox();
          expect(bounds && bounds.x >= 0 && bounds.x + bounds.width <= 900).toBeTruthy();
          await page.screenshot({ path: `${process.env.VVOICE_QA_DIR}/prepare-models-narrow.png` });
          await page.setViewportSize({ width: 1440, height: 920 });
        }
      }
    }
    await dialog.getByRole('button', { name: '关闭', exact: true }).last().click();
    await expect(dialog).toHaveCount(0);
    await expect(page.getByTestId(`nav-${navigation}`)).toHaveClass(/selected/);
  }
});
