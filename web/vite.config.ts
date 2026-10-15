import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig({
  plugins: [react(), {
    name: 'v-voice-vos-brand',
    transformIndexHtml(html) {
      return process.env.VITE_VOS === 'true'
        ? html.replace('<title>yovoice</title>', '<link rel="icon" href="./v-voice.png"/><title>V-Voice</title>').replace("frame-src 'none'", "frame-src 'self'")
        : html;
    },
  }],
  base: './',
  server: { port: 5173, strictPort: true },
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
