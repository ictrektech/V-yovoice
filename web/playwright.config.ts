import { defineConfig } from '@playwright/test';

// 已封存：功能稳定、很少再改的用例，日常提交不跑；每周定时、发布前或设置 PW_ALL=1 时全量运行。
// 改到这些功能时用 `pnpm run test:all`（或 PW_ALL=1 加文件名定向跑）验证，常改的功能移出列表。
const sealed = [
  'book', 'caption-export', 'guide', 'library', 'logs', 'performances',
  'subtitles', 'timeline', 'timeline-logic', 'update', 'assets',
].map(name => `**/${name}.spec.ts`);

const port = Number(process.env.PLAYWRIGHT_TEST_PORT ?? 4173);
const url = `http://127.0.0.1:${port}`;
export default defineConfig({
  testDir: './browser-tests', testMatch: '*.spec.ts', testIgnore: process.env.PW_ALL ? [] : sealed, fullyParallel: true,
  use: { baseURL: url, viewport: { width: 1440, height: 920 }, reducedMotion: 'reduce', launchOptions: { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || undefined } },
  webServer: { command: `pnpm run dev --port ${port} --strictPort`, url, reuseExistingServer: false },
});
