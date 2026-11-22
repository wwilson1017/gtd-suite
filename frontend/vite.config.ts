import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { defineConfig, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

// @billing is the selling UI: src/plans/billing-off.tsx (nothing is sold), or a separate
// billing package copied into src/plans/billing/ (git ignores it). tsconfig.app.json's
// paths say the same; vitest.config.ts takes it from here.
const sold = fileURLToPath(new URL('./src/plans/billing/index.ts', import.meta.url));
export const billingAlias = {
  '@billing': existsSync(sold) ? sold : fileURLToPath(new URL('./src/plans/billing-off.tsx', import.meta.url)),
};

// The policy pages live in public/policy but keep their root addresses (backend/pages.py
// root_file maps them in production); the dev server does the same.
const policyPages: Plugin = {
  name: 'policy-pages',
  configureServer(server) {
    server.middlewares.use((req, _res, next) => {
      if (/^\/(?:(?:terms|privacy|support)\.html|legal\.css)(?:\?|$)/.test(req.url ?? '')) {
        req.url = `/policy${req.url}`;
      }
      next();
    });
  },
};

export default defineConfig({
  plugins: [react(), tailwindcss(), policyPages],
  resolve: { alias: billingAlias },
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
