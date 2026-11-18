import { defineConfig, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

// The policy pages live in public/paid but keep their root addresses (backend/pages.py
// root_file maps them in production); the dev server does the same.
const policyPages: Plugin = {
  name: 'policy-pages',
  configureServer(server) {
    server.middlewares.use((req, _res, next) => {
      if (/^\/(?:(?:terms|privacy|refunds|support)\.html|legal\.css)(?:\?|$)/.test(req.url ?? '')) {
        req.url = `/paid${req.url}`;
      }
      next();
    });
  },
};

export default defineConfig({
  plugins: [react(), tailwindcss(), policyPages],
  build: {
    target: ['es2022', 'safari16'],
    // The backend serves the build (backend/pages.py reads static/index.html).
    outDir: '../backend/static',
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/api': { target: 'http://localhost:8000' },
      '/mcp': { target: 'http://localhost:8000' },
      '/link': { target: 'http://localhost:8000' },
    },
  },
});
