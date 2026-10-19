import { test, expect } from '@playwright/test';
import { emptyState } from '../src/shared/workbench';

test('VOS 原生配乐切换模型后不发送不支持的排除内容', async ({ page }) => {
  test.skip(process.env.VITE_VOS !== 'true', '独立运行 VOS 构建用例');
  const models = [
    ['musicgen-small', 'MusicGen Small'], ['ace-step-1.5-turbo', 'ACE-Step 1.5 Turbo'],
    ['stable-audio-3-small-music', 'Stable Audio 3 Small-Music'], ['stable-audio-3-medium', 'Stable Audio 3 Medium'],
  ].map(([key, name]) => ({ key, name, status: 'ready', size: 1, modelscope_repo: `vivibit/v-music-${key}`, runtime_available: true, admission_ready: true, loaded: false, max_duration_seconds: 30 }));
  await page.addInitScript(() => {
    window.vos_platform = { getState: async () => ({ locale: 'zh-CN' }), api: { v1000: { oauth2: {
      authorize: async input => ({ code: 'fixture-code', state: input.state }),
      token: async () => ({ access_token: 'fixture-token', expires_in: 3600 }),
    } } } };
  });
  await page.route('**/studio-api/call', route => route.fulfill({ json: { result: { state: emptyState(), catalog: [], engine: { version: 'v0.9.1', minimum: 'v0.9.1' }, desktop: false } } }));
  await page.route('**/api/v1/scheduler/binding', route => route.fulfill({ json: { configured: true, approved_model_count: 11 } }));
  await page.route('**/api/v1/music-models', route => route.fulfill({ json: models }));
  const wave = Buffer.alloc(44 + 3200);
  wave.write('RIFF', 0); wave.writeUInt32LE(wave.length - 8, 4); wave.write('WAVEfmt ', 8);
  wave.writeUInt32LE(16, 16); wave.writeUInt16LE(1, 20); wave.writeUInt16LE(1, 22);
  wave.writeUInt32LE(16000, 24); wave.writeUInt32LE(32000, 28); wave.writeUInt16LE(2, 32);
  wave.writeUInt16LE(16, 34); wave.write('data', 36); wave.writeUInt32LE(3200, 40);
  const requests: { model: string; negative_prompt: string }[] = [];
  await page.route('**/v1/audio/music/generations', route => {
    requests.push(route.request().postDataJSON());
    return route.fulfill({ contentType: 'audio/wav', body: wave });
  });
  await page.goto('/');
  await page.getByTestId('nav-background-music').click();
  await page.getByLabel('配乐描述', { exact: true }).fill('Soft piano background music');
  for (const model of models) {
    await page.getByRole('combobox', { name: '配乐模型', exact: true }).click();
    await page.getByRole('option', { name: model.name, exact: true }).click();
    await page.getByRole('button', { name: '生成配乐', exact: true }).click();
    await expect.poll(() => requests.at(-1)?.model).toBe(model.key);
    const supportsNegative = model.key.startsWith('stable-audio-3-');
    expect(requests.at(-1)?.negative_prompt).toBe(supportsNegative ? 'vocals, speech, distortion' : '');
    if (supportsNegative) await expect(page.getByLabel('排除内容', { exact: true })).toBeEnabled();
    else await expect(page.getByLabel('排除内容', { exact: true })).toBeDisabled();
    await expect(page.getByRole('link', { name: '下载配乐', exact: true })).toBeVisible();
  }
});
