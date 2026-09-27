import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { resolve } from 'node:path'

// The planning dashboard is a second entry point inside this project so it reuses the
// installed toolchain (React, Vite, Tailwind, recharts) rather than duplicating
// node_modules. It builds to dist-planning/, which the planning API mounts as static
// files — the legacy dashboard on :8080 keeps its own dist/ untouched.
export default defineConfig({
  plugins: [react()],
  root: resolve(__dirname, 'planning'),
  publicDir: false,
  css: { postcss: resolve(__dirname, 'postcss.planning.config.js') },
  build: {
    outDir: resolve(__dirname, 'dist-planning'),
    emptyOutDir: true,
    chunkSizeWarningLimit: 1200,
  },
  server: {
    port: 5174,
    proxy: {
      // Dev only. In the built app the API is same-origin, so requests are relative.
      '/api': { target: 'http://127.0.0.1:8090', changeOrigin: true, rewrite: (p) => p.replace(/^\/api/, '') },
    },
  },
})
