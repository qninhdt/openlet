import { fileURLToPath, URL } from 'node:url';
import { existsSync, readFileSync } from 'node:fs';
import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig, loadEnv, type Plugin } from 'vite';

function devAccountsPlugin(rootDir: string): Plugin {
  return {
    name: 'openlet-dev-accounts',
    apply: 'serve',
    configureServer(server) {
      server.middlewares.use('/__dev/accounts', (_req, res) => {
        const project = process.env.OPENLET_DEV_PROJECT || 'dev';
        const file = `${rootDir}/.local/env/${project}/dev-accounts.json`;
        res.setHeader('Content-Type', 'application/json');
        if (!existsSync(file)) {
          res.end(JSON.stringify({ project, accounts: [] }));
          return;
        }
        res.end(readFileSync(file, 'utf8'));
      });
    },
  };
}

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const rootDir = fileURLToPath(new URL('../..', import.meta.url)).replace(/\/$/, '');
  const rootEnv = loadEnv(mode, rootDir, 'CLERK_PUBLISHABLE_KEY');
  const webEnv = loadEnv(mode, fileURLToPath(new URL('.', import.meta.url)), 'VITE_');
  const devAuth = process.env.VITE_DEV_AUTH ?? webEnv.VITE_DEV_AUTH ?? '';
  return {
    define: {
      'import.meta.env.VITE_CLERK_PUBLISHABLE_KEY': JSON.stringify(
        webEnv.VITE_CLERK_PUBLISHABLE_KEY ?? rootEnv.CLERK_PUBLISHABLE_KEY ?? '',
      ),
      'import.meta.env.VITE_DEV_AUTH': JSON.stringify(devAuth),
    },
    server: { proxy: { '/v1': 'http://127.0.0.1:8080' } },
    plugins: [react(), tailwindcss(), ...(devAuth === '1' ? [devAccountsPlugin(rootDir)] : [])],
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url)),
      },
    },
  };
});
