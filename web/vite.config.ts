import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { readFile } from 'node:fs/promises';
import { extname, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
const serviceBase = process.env.VITE_VOS_SERVICE_BASE?.replace(/\/+$/, '') ?? '';
// 空白表示与工作台共用本机服务；设备开发可显式指向它的 22700 端口。
const speechServiceBase = (process.env.VITE_VOS_SPEECH_SERVICE_BASE ?? '').replace(/\/+$/, '');
const speechAssets = resolve(fileURLToPath(new URL('../frontend/dist/', import.meta.url)));

export default defineConfig({
  plugins: [react(), {
    name: 'v-voice-vos-brand',
    transformIndexHtml(html) {
      return process.env.VITE_VOS === 'true' || serviceBase
        ? html.replace('<title>yovoice</title>', '<link rel="icon" href="./v-voice.png"/><title>V-Voice</title>').replace("frame-src 'none'", "frame-src 'self'")
        : html;
    },
    configureServer(server) {
      // 兼容页必须使用独立入口，不能被 Vite 的工作台首页回退接管。
      server.middlewares.use('/service', async (request, response) => {
        const pathname = new URL(request.url ?? '/', 'http://localhost').pathname;
        if (pathname === '/runtime-config.js') {
          response.writeHead(200, { 'Content-Type': 'text/javascript' }).end('window.__APP_VERSION__="development";');
          return;
        }
        let file: string;
        try { file = resolve(speechAssets, `.${decodeURIComponent(pathname === '/' ? '/index.html' : pathname)}`); }
        catch { response.writeHead(400).end(); return; }
        if (!file.startsWith(speechAssets + sep)) { response.writeHead(404).end(); return; }
        try {
          const body = await readFile(file);
          const contentType = ({ '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.png': 'image/png', '.svg': 'image/svg+xml' } as Record<string, string>)[extname(file)] ?? 'application/octet-stream';
          response.writeHead(200, { 'Content-Type': contentType, 'Cache-Control': 'no-store' }).end(body);
        } catch {
          response.writeHead(503, { 'Content-Type': 'text/plain; charset=utf-8' }).end('语音管理页面尚未构建，请运行 npm --prefix frontend ci 和 npm --prefix frontend run build。');
        }
      });
    },
  }],
  base: './',
  server: {
    port: 5173,
    strictPort: true,
    // 浏览器同源访问本地 Go 服务，Cookie、事件流和媒体请求保留现有安全边界。
    proxy: serviceBase ? {
      '/studio-api': { target: serviceBase, changeOrigin: true },
      '/api/v1/scheduler/binding': { target: serviceBase, changeOrigin: true },
      '/api': { target: speechServiceBase || serviceBase, changeOrigin: true },
      '/v1': { target: speechServiceBase || serviceBase, changeOrigin: true },
    } : undefined,
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    rollupOptions: {
      output: {
        // 稳定的 React 运行时独立缓存，业务改动无需重新加载这一部分。
        manualChunks: { react: ['react', 'react-dom', 'react-dom/client'] },
      },
    },
  },
});
