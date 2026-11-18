import { fileURLToPath, URL } from 'node:url';
import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig, loadEnv } from 'vite';

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const rootEnv = loadEnv(
    mode,
    fileURLToPath(new URL('../..', import.meta.url)),
    'CLERK_PUBLISHABLE_KEY',
  );
  const webEnv = loadEnv(mode, fileURLToPath(new URL('.', import.meta.url)), 'VITE_');
  return {
    define: {
      'import.meta.env.VITE_CLERK_PUBLISHABLE_KEY': JSON.stringify(
        webEnv.VITE_CLERK_PUBLISHABLE_KEY ?? rootEnv.CLERK_PUBLISHABLE_KEY ?? '',
      ),
    },
    server: { proxy: { '/v1': 'http://127.0.0.1:8080' } },
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url)),
      },
    },
  };
});
