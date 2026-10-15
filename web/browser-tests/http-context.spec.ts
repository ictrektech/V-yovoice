import { test, expect } from '@playwright/test';

test('局域网 HTTP 缺少 randomUUID 时工作台仍可打开并生成安全 UUID', async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(crypto, 'randomUUID', { configurable: true, writable: true, value: undefined });
    Object.defineProperty(crypto, 'subtle', { configurable: true, value: undefined });
  });
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  await expect(page.locator('.document-title')).toBeVisible();
  const ids = await page.evaluate(() => Array.from({ length: 100 }, () => crypto.randomUUID()));
  expect(new Set(ids).size).toBe(100);
  for (const id of ids) expect(id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  expect(errors).toEqual([]);
});
