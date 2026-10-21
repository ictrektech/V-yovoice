import { test, expect } from '@playwright/test';

// 真实同源父页面写入平台偏好，覆盖旧版 VOS 没有语言桥接能力的场景。
test('旧版 VOS 首帧及已打开页面跟随平台语言，空模型状态不误报接入失败', async ({ page }) => {
  test.skip(process.env.VITE_VOS !== 'true', '需要 VOS 前端构建');
  await page.addInitScript(() => {
    localStorage.removeItem('v-voice-creator-locale');
    localStorage.setItem('VIVIBIT-test-preferences-locale', JSON.stringify('zh-CN'));
  });
  let configured = false;
  await page.route('**/legacy-host', route => route.fulfill({ contentType: 'text/html', body: '<iframe title="V-Voice" src="/"></iframe>' }));
  await page.route('**/api/v1/scheduler/binding', route => route.fulfill({ json: { configured, approved_model_count: configured ? 1 : 0 } }));
  await page.route('**/api/v1/discovery', route => route.fulfill({ json: { models: [] } }));
  await page.route('**/api/v1/creative-models', route => route.fulfill({ json: [] }));
  await page.goto('/legacy-host');
  const app = page.frameLocator('iframe');
  await expect(app.getByTestId('scheduler-status')).toContainText('尚无就绪的语音模型');
  await page.evaluate(() => localStorage.setItem('VIVIBIT-test-preferences-locale', JSON.stringify('en-US')));
  await expect(app.getByTestId('scheduler-status')).toContainText('No speech models are ready');
  await page.evaluate(() => localStorage.setItem('VIVIBIT-test-preferences-locale', JSON.stringify({ value: 'zh-TW' })));
  await expect(app.getByTestId('scheduler-status')).toContainText('尚無就緒的語音模型');
  configured = true;
  await expect(app.getByTestId('scheduler-status')).toHaveCount(0, { timeout: 10000 });
});

test('已有模型但尚未绑定时保留接入状态，不误导下载', async ({ page }) => {
  test.skip(process.env.VITE_VOS !== 'true', '需要 VOS 前端构建');
  await page.addInitScript(() => {
    localStorage.setItem('v-voice-creator-locale', 'zh-CN');
  });
  await page.route('**/api/v1/scheduler/binding', route => route.fulfill({ json: { configured: false } }));
  await page.route('**/api/v1/discovery', route => route.fulfill({ json: { models: [{ id: 'sensevoice-int8' }] } }));
  await page.route('**/api/v1/creative-models', route => route.fulfill({ json: [] }));
  await page.goto('/');
  await expect(page.getByTestId('scheduler-status')).toContainText('正在等待 V-Scheduler 自动接入');
  await expect(page.getByTestId('scheduler-status')).not.toContainText('尚无就绪');
});
