import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') }
  },
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:18080',
      '/ws': { target: 'ws://127.0.0.1:18080', ws: true }
    }
  },
  build: {
    outDir: 'dist',
    sourcemap: true
  }
});
