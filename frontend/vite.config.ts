/// <reference types="vitest/config" />
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath, URL } from 'node:url'
import { defineConfig, loadEnv } from 'vite'

// Env files live at the repo root so backend and frontend share one `.env`.
// Only VITE_* variables are ever exposed to the browser bundle.
const envDir = fileURLToPath(new URL('..', import.meta.url))

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, envDir, 'VITE_')
  return {
    envDir,
    plugins: [react(), tailwindcss()],
    resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
    server: { host: true, port: 5173, strictPort: true },
    build: { sourcemap: mode !== 'production', outDir: 'dist' },
    define: { __APP_NAME__: JSON.stringify(env.VITE_APP_NAME ?? 'BoltRun') },
    test: {
      environment: 'jsdom',
      globals: true,
      setupFiles: ['./src/test/setup.ts'],
      css: false,
    },
  }
})
