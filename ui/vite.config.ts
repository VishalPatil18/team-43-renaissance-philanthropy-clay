import { defineConfig } from 'vite';

// `npm run dev` proxies the API started with `python -m claysandbox.api --store <path>`.
export default defineConfig({
  server: { host: '127.0.0.1', port: 5173, strictPort: true, proxy: { '/api': 'http://127.0.0.1:8765' } },
  build: { outDir: 'dist', emptyOutDir: true },
});
