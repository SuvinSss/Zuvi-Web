/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The app is served by Django at /app/. In development the Vite server proxies
// /api to Django so the browser sees one origin and the session cookie just works.
export default defineConfig({
  base: "/app/",
  plugins: [react()],
  build: {
    // Django reads index.html from here and WhiteNoise serves the hashed assets.
    outDir: "dist/app",
    emptyOutDir: true,
    sourcemap: false,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": { target: process.env.DJANGO_URL ?? "http://127.0.0.1:8000", changeOrigin: false },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    restoreMocks: true,
  },
});
