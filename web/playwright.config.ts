import { defineConfig } from '@playwright/test';
const port = Number(process.env.PLAYWRIGHT_TEST_PORT ?? 4173);
const url = `http://127.0.0.1:${port}`;
export default defineConfig({ testDir: './browser-tests', testMatch: '*.spec.ts', fullyParallel: true, use: { baseURL: url, viewport: { width: 1440, height: 920 }, launchOptions: { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || undefined } }, webServer: { command: `pnpm run dev --port ${port} --strictPort`, url, reuseExistingServer: false } });
