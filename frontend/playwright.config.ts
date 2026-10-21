import { defineConfig } from '@playwright/test'

// Runs against a real Django (throwaway SQLite, see ../backend/scripts/e2e_seed.py) and the Vite dev server.
// CI preinstalls Chromium; locally set PW_CHROMIUM_PATH if Playwright's own browser is not installed.
const executablePath = process.env.PW_CHROMIUM_PATH || undefined

export default defineConfig({
  testDir: './e2e',
  globalSetup: './e2e/global-setup.ts',
  fullyParallel: false,
  workers: 1,
  timeout: 45_000,
  reporter: [['list']],
  use: {
    baseURL: 'http://127.0.0.1:5173',
    storageState: 'e2e/.auth.json',
    trace: 'retain-on-failure',
    launchOptions: { executablePath },
  },
})
