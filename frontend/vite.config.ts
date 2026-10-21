import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

// Dev: the browser talks to Vite, which proxies /api and /media to Django, so the
// session cookie is same-origin and no CORS is needed. Set VITE_API_BASE_URL to a
// full URL to run the frontend against a backend on another origin instead.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const backend = env.VITE_DEV_BACKEND_URL || 'http://127.0.0.1:8000'
  return {
    plugins: [react(), tailwindcss()],
    resolve: { alias: { '@': path.resolve(import.meta.dirname, 'src') } },
    server: {
      port: 5173,
      proxy: {
        '/api': { target: backend, changeOrigin: false },
        '/media': { target: backend, changeOrigin: false },
        // The classic Django portal (orders, inventory, stores...) stays reachable from the dev app.
        '/management': { target: backend, changeOrigin: false },
        '/static': { target: backend, changeOrigin: false },
      },
    },
    build: {
      sourcemap: false,
      rollupOptions: {
        output: {
          manualChunks(id: string) {
            if (/node_modules\/(react|react-dom|react-router|react-router-dom)\//.test(id)) return 'react'
            if (/node_modules\/(@tanstack|axios)\//.test(id)) return 'query'
            return undefined
          },
        },
      },
    },
    test: {
      globals: true,
      environment: 'jsdom',
      setupFiles: ['./src/test/setup.ts'],
      include: ['src/**/*.test.{ts,tsx}'],
      css: false,
    },
  }
})
