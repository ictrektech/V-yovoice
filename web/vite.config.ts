import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { readFile } from 'node:fs/promises';
import { extname, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import type { ClientRequest } from 'node:http';
import { execFileSync } from 'node:child_process';
import { gatewayConfig, gatewayMiddleware } from './dev-gateway';
import { modelManagement } from './dev-models';
import speechCatalog from '../catalog/models.json';
const serviceBase = process.env.VITE_VOS_SERVICE_BASE?.replace(/\/+$/, '') ?? '';
const gateway = process.env.VVOICE_GATEWAY_BASE ? gatewayConfig(process.env.VVOICE_GATEWAY_BASE, process.env.VVOICE_GATEWAY_TOKEN_FILE) : undefined;
const supported = gateway ? JSON.parse(execFileSync('python3', [fileURLToPath(new URL('../scripts/dev-catalog.py', import.meta.url))], { encoding: 'utf8' })) : undefined;
const hubURL = gateway ? new URL(gateway.base) : undefined;
if (hubURL) { hubURL.port = '36005'; hubURL.pathname = '/'; }
const hub = hubURL ? gatewayConfig(process.env.MODEL_HUB_API_URL || hubURL.href) : undefined;
if (hub && gateway && new URL(hub.base).origin === new URL(gateway.base).origin) hub.token = gateway.token;
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
      if (gateway && hub && supported) server.middlewares.use(modelManagement(hub, gateway, supported));
      if (gateway) server.middlewares.use(gatewayMiddleware(gateway, speechCatalog.models));
      // 兼容页必须使用独立入口，不能被 Vite 的工作台首页回退接管。
      server.middlewares.use('/service', async (request, response) => {
        const pathname = new URL(request.url ?? '/', 'http://localhost').pathname;
        if (pathname === '/runtime-config.js') {
          response.writeHead(200, { 'Content-Type': 'text/javascript' }).end(`window.__APP_VERSION__="development";window.__VVOICE_GATEWAY__=${!!gateway};`);
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
      '/api': { target: serviceBase, changeOrigin: true },
      '/v1': { target: gateway?.base || serviceBase, changeOrigin: true, ws: true, configure(proxy) {
        if (!gateway) return;
        const authenticate = (upstream: ClientRequest) => {
          // 浏览器开发凭据不是网关身份；真实网关凭据仅由 Vite 服务端持有。
          upstream.removeHeader('authorization');
          upstream.removeHeader('x-api-key');
          upstream.removeHeader('cookie');
          if (gateway.token) upstream.setHeader('authorization', `Bearer ${gateway.token}`);
        };
        proxy.on('proxyReq', authenticate);
        proxy.on('proxyReqWs', authenticate);
      } },
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
