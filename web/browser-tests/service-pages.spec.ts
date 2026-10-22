import { test, expect } from '@playwright/test';

test('本地工作台提供语音模型目录而不进入登录', async ({ request }) => {
  test.skip(!process.env.VITE_VOS_SERVICE_BASE, '需要本地真实后端');
  const models = await request.get('/api/v1/models');
  expect(models.status()).toBe(200);
  expect(Array.isArray(await models.json())).toBe(true);
  const discovery = await request.get('/api/v1/discovery');
  expect(discovery.status()).toBe(200);
  expect((await discovery.json()).authentication).toBe('none');
});
