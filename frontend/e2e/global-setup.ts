import { chromium, type FullConfig } from '@playwright/test'

// Sign in once and reuse the session: the login endpoint is rate limited (10/min) on purpose.
export default async function globalSetup(config: FullConfig) {
  const browser = await chromium.launch({ executablePath: process.env.PW_CHROMIUM_PATH || undefined })
  const page = await browser.newPage({ baseURL: config.projects[0]?.use.baseURL })
  await page.goto('/login')
  await page.getByLabel('Username').fill(process.env.E2E_USER || 'e2e_admin')
  await page.getByLabel('Password').fill(process.env.E2E_PASS || 'E2e-pass-12345!')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await page.getByRole('heading', { name: 'Products', level: 1 }).waitFor()
  await page.context().storageState({ path: 'e2e/.auth.json' })
  await browser.close()
}
