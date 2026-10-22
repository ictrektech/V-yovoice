import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
const serviceBase = process.env.VITE_VOS_SERVICE_BASE?.replace(/\/+$/, '') ?? '';
// 空白表示与工作台共用本机服务；设备开发可显式指向它的 22700 端口。
const speechServiceBase = (process.env.VITE_VOS_SPEECH_SERVICE_BASE ?? '').replace(/\/+$/, '');

export default defineConfig({
  plugins: [react(), {
    name: 'v-voice-vos-brand',
    transformIndexHtml(html) {
      return process.env.VITE_VOS === 'true' || serviceBase
        ? html.replace('<title>yovoice</title>', '<link rel="icon" href="./v-voice.png"/><title>V-Voice</title>').replace("frame-src 'none'", "frame-src 'self'")
        : html;
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
