import { expect, test, type Page } from '@playwright/test'
import { deflateSync } from 'node:zlib'

const USER = process.env.E2E_USER || 'e2e_admin'
const PASS = process.env.E2E_PASS || 'E2e-pass-12345!'

// A valid, tiny, non-trivial PNG built in memory (no fixtures on disk).
function png(seed: number): Buffer {
  const w = 64, h = 48
  const raw = Buffer.alloc((w * 3 + 1) * h)
  for (let y = 0; y < h; y++) {
    raw[y * (w * 3 + 1)] = 0
    for (let x = 0; x < w; x++) {
      const o = y * (w * 3 + 1) + 1 + x * 3
      raw[o] = (x * 4 + seed * 40) % 256; raw[o + 1] = (y * 5 + seed * 70) % 256; raw[o + 2] = (seed * 90) % 256
    }
  }
  const crcTable = Array.from({ length: 256 }, (_, n) => { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; return c >>> 0 })
  const crc = (b: Buffer) => { let c = 0xffffffff; for (const v of b) c = crcTable[(c ^ v) & 255]! ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0 }
  const chunk = (type: string, data: Buffer) => {
    const body = Buffer.concat([Buffer.from(type), data])
    const len = Buffer.alloc(4); len.writeUInt32BE(data.length)
    const sum = Buffer.alloc(4); sum.writeUInt32BE(crc(body))
    return Buffer.concat([len, body, sum])
  }
  const ihdr = Buffer.alloc(13); ihdr.writeUInt32BE(w, 0); ihdr.writeUInt32BE(h, 4); ihdr[8] = 8; ihdr[9] = 2
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', ihdr), chunk('IDAT', deflateSync(raw)), chunk('IEND', Buffer.alloc(0))])
}

async function open(page: Page, path = '/products') {
  await page.goto(path)
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
}

async function signIn(page: Page) {
  await page.goto('/login')
  await page.getByLabel('Username').fill(USER)
  await page.getByLabel('Password').fill(PASS)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { name: 'Products', level: 1 })).toBeVisible()
}

async function getJson<T>(page: Page, url: string): Promise<T> {
  return (await page.evaluate(async (u) => (await fetch(u, { credentials: 'include' })).json(), url)) as T
}

const anonymous = { cookies: [], origins: [] }

test.describe('anonymous', () => {
test.use({ storageState: anonymous })
test('rejects wrong credentials without signing in', async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel('Username').fill(USER)
  await page.getByLabel('Password').fill('wrong-password')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('alert')).toBeVisible()
  await expect(page).toHaveURL(/\/login/)
})

test('protected routes redirect to login, and the session survives a reload', async ({ page }) => {
  await page.goto('/products')
  await expect(page).toHaveURL(/\/login/)
  await signIn(page)
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Products', level: 1 })).toBeVisible()
  const cookies = await page.context().cookies()
  const session = cookies.find((c) => c.name === 'sessionid')
  expect(session?.httpOnly).toBe(true)
})

test('sign out ends the session', async ({ page }) => {
  await signIn(page)
  await page.getByRole('button', { name: 'Sign out' }).first().click()
  await expect(page).toHaveURL(/\/login/)
  await page.goto('/products')
  await expect(page).toHaveURL(/\/login/)
})
})

test('create a product and upload a photo', async ({ page }) => {
  await open(page)
  await page.locator('#main').getByRole('link', { name: 'New product' }).first().click()
  // Client-side validation first
  await page.getByRole('button', { name: 'Create product' }).click()
  await expect(page.getByText('Enter a product name.')).toBeVisible()
  await expect(page.getByText('Enter a SKU.')).toBeVisible()

  const sku = `E2E-${Date.now()}`
  await page.locator('select[name="store"]').selectOption({ index: 1 })
  await page.locator('input[name="name"]').fill('E2E Apples')
  await page.locator('input[name="sku"]').fill(sku)
  await page.locator('input[name="store_price"]').fill('42.50')
  await page.locator('select[name="category"]').selectOption({ label: 'E2E Fruit' })
  await page.getByRole('button', { name: 'Create product' }).click()
  await expect(page.getByText('Choose a photo')).toBeVisible()

  await page.getByLabel('Choose a photo').setInputFiles({ name: 'apple.png', mimeType: 'image/png', buffer: png(1) })
  await page.getByRole('button', { name: 'Upload photo' }).click()
  const img = page.locator('img[src*="/media/"]').first()
  await expect(img).toBeVisible()
  await expect(img).toHaveJSProperty('complete', true)
  expect(await img.evaluate((el) => (el as unknown as { naturalWidth: number }).naturalWidth)).toBeGreaterThan(0)

  await page.goto('/products')
  await page.getByLabel('Search products').fill(sku)
  await expect(page.getByText('E2E Apples').first()).toBeVisible()

})

test('bulk import: preview shows row errors, nothing saved until confirmed', async ({ page }) => {
  await open(page, '/products/import')
  const sku = `IMP-${Date.now()}`
  const meta = await getJson<{ stores: { store_code: string }[] }>(page, '/api/v1/products/meta/')
  const code = meta.stores[0].store_code as string
  const csv = [
    'store_code,sku,name,category,store_price',
    `${code},${sku},Imported Mango,E2E Fruit,30`,
    `${code},${sku}-BAD,Bad Row,No Such Category,abc`,
  ].join('\n')
  await page.getByLabel('Product spreadsheet').setInputFiles({ name: 'p.csv', mimeType: 'text/csv', buffer: Buffer.from(csv) })
  await page.getByLabel(/Import valid rows only/).check()
  await page.getByRole('button', { name: 'Check file' }).click()
  await expect(page.getByText('With errors').first()).toBeVisible()
  await expect(page.getByText(/category/i).first()).toBeVisible()

  // Nothing saved yet
  const before = await getJson<{ count: number }>(page, `/api/v1/products/?q=${sku}`)
  expect(before.count).toBe(0)

  await page.getByRole('button', { name: /^Import 1 product/ }).click()
  await page.getByRole('button', { name: 'Yes, import now' }).click()
  await expect(page.getByRole('heading', { name: /Import finished — some rows were left out/ })).toBeVisible()
  await expect(page.getByText("Category 'No Such Category' was not found.")).toBeVisible()
  const after = await getJson<{ count: number }>(page, `/api/v1/products/?q=${sku}`)
  expect(after.count).toBe(1)
})

for (const [name, size] of [['mobile', { width: 375, height: 740 }], ['tablet', { width: 768, height: 1024 }], ['desktop', { width: 1440, height: 900 }]] as const) {
  test(`no horizontal overflow on ${name}`, async ({ page }) => {
    await page.setViewportSize(size)
    for (const path of ['/products', '/products/new', '/products/import']) {
      await page.goto(path)
      await page.waitForLoadState('networkidle')
      const overflow = await page.evaluate(() => (globalThis as unknown as { document: { documentElement: { scrollWidth: number; clientWidth: number } } }).document.documentElement.scrollWidth - (globalThis as unknown as { document: { documentElement: { clientWidth: number } } }).document.documentElement.clientWidth)
      expect(overflow, `${path} at ${size.width}px`).toBeLessThanOrEqual(0)
    }
  })
}
