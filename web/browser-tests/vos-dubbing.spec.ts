import { test, expect } from '@playwright/test';
import { emptyState } from '../src/shared/workbench';

test('滚动侧栏后选中正确项目，字幕经 Scheduler 翻译并保留时间码与说话人', async ({ page }, testInfo) => {
  test.skip(process.env.VITE_VOS !== 'true', '需要 VOS 构建');
  await page.addInitScript(() => {
    window.vos_platform = { getState: async () => ({ locale: 'zh-CN' }), api: { v1000: { oauth2: {
      authorize: async input => ({ code: 'fixture-code', state: input.state }),
      token: async () => ({ access_token: 'fixture-token', expires_in: 3600 }),
    } } } };
  });
  const state = emptyState();
  const saved = new Map();
  await page.route('**/api/v1/scheduler/binding', route => route.fulfill({ json: { configured: true } }));
  await page.route('**/studio-api/call', route => {
    const { method, data } = route.request().postDataJSON();
    if (method === 'draft.save') { saved.set(data.id, data); return route.fulfill({ json: { result: true } }); }
    return route.fulfill({ json: { result: { state: { ...state, drafts: [...saved.values(), ...state.drafts] }, catalog: [], assistant: { available: false } } } });
  });
  await page.route('**/api/com.ictrek.v-scheduler/api/v1/models', route => {
    expect(route.request().headers().authorization).toBe('Bearer fixture-token');
    return route.fulfill({ json: { models: [
      { id: 'asr', endpoints: ['audio/transcriptions'] },
      { id: 'text', qualified: 'fixture/text', endpoints: ['/v1/chat/completions'] },
    ] } });
  });
  await page.route('**/api/com.ictrek.v-scheduler/v1/chat/completions', route => {
    const request = route.request().postDataJSON();
    expect(route.request().headers().authorization).toBe('Bearer fixture-token');
    expect(request.model).toBe('fixture/text');
    expect(JSON.parse(request.messages[1].content)).toEqual([{ id: 0, seconds: 2, text: '你好' }]);
    return route.fulfill({ json: { choices: [{ message: { content: '[{"id":0,"text":"Hello"}]' } }] } });
  });
  await page.setViewportSize({ width: 1250, height: 680 });
  await page.goto('/');
  const sidebar = page.getByTestId('sidebar');
  for (const id of ['models-category', 'models-creative-category', 'asr', 'tts', 'speaker', 'hotwords', 'text', 'story', 'music', 'characters', 'api-docs', 'settings', 'story']) {
    const button = sidebar.getByTestId(`nav-${id}`);
    await button.scrollIntoViewIfNeeded();
    await button.click();
    await expect(button).toHaveAttribute('aria-current', 'page');
    await expect(sidebar.locator('.nav-item.selected')).toHaveCount(1);
  }
  await page.screenshot({ path: testInfo.outputPath('sidebar.png') });
  await page.getByTestId('nav-new').click();
  await page.getByRole('menuitem', { name: '故事配音', exact: true }).click();
  await page.locator('.editor-status').getByLabel('字幕文件').setInputFiles({
    name: '对话.vtt', mimeType: 'text/vtt', buffer: Buffer.from('WEBVTT\n\n00:01.000 --> 00:03.000\n<v Alice>你好'),
  });
  await page.getByRole('button', { name: '翻译配音台词', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByRole('button', { name: '翻译台词', exact: true }).click();
  await expect(dialog.getByLabel('第 1 句译文')).toHaveValue('Hello');
  await page.screenshot({ path: testInfo.outputPath('dubbing.png') });
  await dialog.getByLabel('第 1 句译文').fill('Hello there');
  await dialog.getByRole('button', { name: '创建译制作品' }).click();
  await expect(page.getByLabel('第 1 句台词', { exact: true })).toHaveValue('Hello there');
  const dubbed = [...saved.values()].find(draft => draft.matchCueTiming);
  expect(dubbed).toMatchObject({ matchCueTiming: true, language: 'en', subtitles: {
    speakers: [{ sourceName: 'Alice' }], cues: [{ start: 1000, end: 3000, text: 'Hello there' }],
  } });
  expect([...saved.values()]).toContainEqual(expect.objectContaining({ text: '你好' }));
});
