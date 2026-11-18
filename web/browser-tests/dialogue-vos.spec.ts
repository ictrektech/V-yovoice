import { expect, test } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { emptyState } from '../src/shared/workbench';

const catalog = JSON.parse(readFileSync(new URL('../../internal/catalog/catalog.json', import.meta.url), 'utf8')).models;

test('没有麦克风时实时对话不可开始并给出明确提示', async ({ page }) => {
  test.skip(process.env.VITE_VOS !== 'true', '需要 VOS 构建');
  await page.addInitScript(() => {
    localStorage.setItem('v-voice-creator-locale', 'zh-CN');
    window.vos_platform = { getState: async () => ({ locale: 'zh-CN' }), api: { v1000: { oauth2: {
      authorize: async input => ({ code: 'fixture-code', state: input.state }),
      token: async () => ({ access_token: 'fixture-token', expires_in: 3600 }),
    } } } };
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { enumerateDevices: async () => [] },
    });
  });
  await page.route('**/api/v1/dialogue/status', route => route.fulfill({
    json: { supported: true, model_installed: true, state: 'ready_idle', busy: false, idle_unload_seconds: 120 },
  }));
  await page.route('**/api/v1/scheduler/binding', route => route.fulfill({ json: { configured: true, approved_model_count: 1 } }));
  await page.route('**/api/v1/creative-models', route => route.fulfill({ json: [] }));
  await page.route('**/studio-api/call', route => route.fulfill({
    json: { result: { state: emptyState(), catalog, catalogRevision: 'fixture', assistant: { available: false } } },
  }));

  await page.goto('/');
  await page.getByTestId('nav-dialogue').click();
  await expect(page.getByRole('heading', { name: '实时对话' })).toBeVisible();
  await expect(page.getByText('未找到麦克风，请连接输入设备后重试。')).toBeVisible();
  await expect(page.getByTestId('dialogue-start')).toBeDisabled();
  await expect(page.getByText(/NotFoundError/)).toHaveCount(0);
});

test('实时对话先准备麦克风再连接会话', async ({ page }) => {
  test.skip(process.env.VITE_VOS !== 'true', '需要 VOS 构建');
  await page.addInitScript(() => {
    localStorage.setItem('v-voice-creator-locale', 'zh-CN');
    window.vos_platform = { getState: async () => ({ locale: 'zh-CN' }), api: { v1000: { oauth2: {
      authorize: async input => ({ code: 'fixture-code', state: input.state }),
      token: async () => ({ access_token: 'fixture-token', expires_in: 3600 }),
    } } } };
    const events: string[] = [];
    (window as unknown as { __dialogueEvents: string[] }).__dialogueEvents = events;
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: {
        enumerateDevices: async () => [{ kind: 'audioinput' }],
        getUserMedia: async () => {
          events.push('microphone');
          return { getTracks: () => [{ stop() {} }] };
        },
      },
    });
    class FakeNode {
      gain = { value: 0 };
      connect(_node?: unknown) {}
    }
    class FakeAudioContext {
      sampleRate = 48000;
      destination = new FakeNode();
      async resume() {}
      async close() {}
      createMediaStreamSource() { return new FakeNode(); }
      createScriptProcessor() { return new FakeNode(); }
      createGain() { return new FakeNode(); }
    }
    Object.defineProperty(window, 'AudioContext', { configurable: true, value: FakeAudioContext });
    class FakeWebSocket {
      static OPEN = 1;
      readyState = 0;
      onopen: (() => void) | null = null;
      onmessage: ((event: MessageEvent) => void) | null = null;
      onerror: (() => void) | null = null;
      onclose: (() => void) | null = null;
      constructor(url: string) {
        if (url.includes('/dialogue/ws')) events.push('websocket');
        setTimeout(() => {
          this.readyState = FakeWebSocket.OPEN;
          this.onopen?.();
        });
      }
      send() {}
      close() {
        this.readyState = 3;
        this.onclose?.();
      }
    }
    Object.defineProperty(window, 'WebSocket', { configurable: true, value: FakeWebSocket });
  });
  await page.route('**/api/v1/dialogue/status', route => route.fulfill({
    json: { supported: true, model_installed: true, state: 'unloaded', busy: false, idle_unload_seconds: 120 },
  }));
  await page.route('**/api/v1/dialogue/tickets', route => route.fulfill({
    json: { ticket: 'fixture-ticket', expires_at: 0, ws_path: '/api/v1/dialogue/ws' },
  }));
  await page.route('**/api/v1/scheduler/binding', route => route.fulfill({ json: { configured: true, approved_model_count: 1 } }));
  await page.route('**/api/v1/creative-models', route => route.fulfill({ json: [] }));
  await page.route('**/studio-api/call', route => route.fulfill({
    json: { result: { state: emptyState(), catalog, catalogRevision: 'fixture', assistant: { available: false } } },
  }));

  await page.goto('/');
  await page.getByTestId('nav-dialogue').click();
  await page.getByTestId('dialogue-start').click();
  await expect.poll(() => page.evaluate(() => (
    window as unknown as { __dialogueEvents: string[] }
  ).__dialogueEvents)).toEqual(['microphone', 'websocket']);
});

test('不支持的 profile 不显示实时对话入口', async ({ page }) => {
  test.skip(process.env.VITE_VOS !== 'true', '需要 VOS 构建');
  await page.addInitScript(() => {
    localStorage.setItem('v-voice-creator-locale', 'zh-CN');
    window.vos_platform = { getState: async () => ({ locale: 'zh-CN' }), api: { v1000: { oauth2: {
      authorize: async input => ({ code: 'fixture-code', state: input.state }),
      token: async () => ({ access_token: 'fixture-token', expires_in: 3600 }),
    } } } };
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { enumerateDevices: async () => [{ kind: 'audioinput' }] },
    });
  });
  const statusResponse = page.waitForResponse('**/api/v1/dialogue/status');
  await page.route('**/api/v1/dialogue/status', route => route.fulfill({
    json: { supported: false, model_installed: false, state: 'unavailable', busy: false, idle_unload_seconds: 120 },
  }));
  await page.route('**/api/v1/scheduler/binding', route => route.fulfill({ json: { configured: true, approved_model_count: 2 } }));
  await page.route('**/api/v1/creative-models', route => route.fulfill({ json: [] }));
  await page.route('**/studio-api/call', route => route.fulfill({
    json: { result: { state: emptyState(), catalog, catalogRevision: 'fixture', assistant: { available: false } } },
  }));

  await page.goto('/');
  await statusResponse;
  await expect(page.getByTestId('nav-dialogue')).toHaveCount(0);
});
