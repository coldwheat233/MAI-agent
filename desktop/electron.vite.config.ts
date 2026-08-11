import { resolve } from 'path'
import { defineConfig, externalizeDepsPlugin } from 'electron-vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  main: {
    plugins: [externalizeDepsPlugin()],
    build: {
      outDir: 'out/main',
    },
  },
  preload: {
    plugins: [externalizeDepsPlugin()],
    build: {
      outDir: 'out/preload',
    },
  },
  renderer: {
    root: resolve('src/renderer'),
    plugins: [
      react(),
      {
        name: 'strip-crossorigin',
        transformIndexHtml(html) {
          return html.replace(/\s*crossorigin\b/g, '')
        },
      },
    ],
    build: {
      outDir: 'out/renderer',
      rollupOptions: {
        input: resolve('src/renderer/index.html'),
      },
    },
    resolve: {
      alias: {
        '@': resolve('src/renderer'),
      },
    },
    server: {
      port: 5173,
      proxy: {
        '/ws': { target: 'http://localhost:8765', ws: true },
        '/api': 'http://localhost:8765',
      },
    },
  },
})
