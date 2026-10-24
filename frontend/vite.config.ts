/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { '/api': { target: 'http://localhost:8000', changeOrigin: false } },
  },
  build: { outDir: 'dist' },
  test: { environment: 'jsdom', globals: false, setupFiles: ['./src/test/setup.ts'] },
});
