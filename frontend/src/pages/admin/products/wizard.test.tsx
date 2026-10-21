import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { routes } from '@/app/router'
import { adminSession, renderRoutes } from '@/test/utils'
import { autoSku } from './ProductWizard'

vi.mock('@/services/auth', () => ({ fetchSession: vi.fn(), login: vi.fn(), logout: vi.fn() }))
vi.mock('@/services/ops', () => ({ adminCounts: vi.fn(), adminSearch: vi.fn() }))
vi.mock('@/services/platform', async (orig) => ({ ...(await orig<object>()), unreadCount: vi.fn().mockResolvedValue(0) }))
vi.mock('@/services/products', async (orig) => ({ ...(await orig<object>()), getMeta: vi.fn(), createProduct: vi.fn(), uploadImage: vi.fn() }))
vi.mock('@/services/management', async (orig) => ({ ...(await orig<object>()), pricingPreview: vi.fn(), setPricing: vi.fn(), changeProductStatus: vi.fn() }))

import * as auth from '@/services/auth'
import * as mgmt from '@/services/management'
import * as ops from '@/services/ops'
import * as products from '@/services/products'

const meta = (can = {}) => ({
  stores: [{ id: 1, name: 'Green Mart', store_code: 'ST1' }], categories: [{ id: 2, name: 'Rice', slug: 'rice' }], brands: [], tags: [],
  units: [{ value: 'KG', label: 'Kilogram' }, { value: 'PIECE', label: 'Piece' }], statuses: [], max_images: 8,
  can: { view: true, add: true, change: true, pricing: true, approve: true, stock: true, ...can },
})
const breakdown = { cost: '600.00', selling_price: '800.00', discount_amount: '0.00', final_price: '800.00', profit_per_unit: '200.00', margin_percent: '25.00', markup_percent: '33.33', label: 'Estimated gross profit (before tax, fees and commission)', warnings: [], below_cost: false }

beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(auth.fetchSession).mockResolvedValue(adminSession as never)
  vi.mocked(ops.adminCounts).mockResolvedValue({ orders_awaiting_confirmation: 0, deliveries_needing_attention: 0, partners_pending: 0, stores_pending: 0, products_pending: 0, tickets_open: 0, complaints_open: 0, stores_needs_info: 0 })
  vi.mocked(mgmt.pricingPreview).mockResolvedValue({ breakdown })
})

async function fillBasics() {
  await userEvent.type(await screen.findByLabelText(/product name/i), 'Basmati Rice')
  await userEvent.selectOptions(screen.getByLabelText(/^store/i), '1')
  await userEvent.selectOptions(screen.getByLabelText(/^category/i), '2')
}
const next = () => userEvent.click(screen.getByRole('button', { name: 'Next' }))

describe('product wizard', () => {
  it('generates a readable SKU', () => expect(autoSku('Basmati Rice 1kg!')).toBe('AUTO-BASMATI-RICE-1KG'))

  it('walks five steps and saves a draft with opening stock, then sets the price', async () => {
    vi.mocked(products.getMeta).mockResolvedValue(meta() as never)
    vi.mocked(products.createProduct).mockResolvedValue({ id: 41 } as never)
    vi.mocked(mgmt.setPricing).mockResolvedValue({} as never)
    renderRoutes(routes, ['/admin/products/new'])
    await fillBasics()
    await next()
    await userEvent.type(screen.getByLabelText(/stock on hand/i), '12')
    await next()
    await userEvent.type(screen.getByLabelText(/store price/i), '600')
    await userEvent.type(screen.getByLabelText(/^selling price/i), '800')
    expect(await screen.findByText('25.00%')).toBeInTheDocument()
    expect(screen.getByText('33.33%')).toBeInTheDocument()
    await next(); await next()
    expect(screen.getByText(/can be saved and submitted, but not approved yet/i)).toBeInTheDocument()  // no photo
    expect(screen.getByRole('button', { name: 'Save and approve' })).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: 'Save draft' }))
    await waitFor(() => expect(products.createProduct).toHaveBeenCalled())
    const body = vi.mocked(products.createProduct).mock.calls[0]![0] as unknown as Record<string, unknown>
    expect(body).toMatchObject({ sku: 'AUTO-BASMATI-RICE', store: 1, category: 2, store_price: '600', opening_stock: '12', save_as_draft: true })
    expect(body).not.toHaveProperty('status')
    await waitFor(() => expect(mgmt.setPricing).toHaveBeenCalledWith(41, expect.objectContaining({ selling_price: '800' })))
    expect(mgmt.changeProductStatus).not.toHaveBeenCalled()
  })

  it('submit sends the product for approval through the status endpoint', async () => {
    vi.mocked(products.getMeta).mockResolvedValue(meta({ approve: false }) as never)
    vi.mocked(products.createProduct).mockResolvedValue({ id: 42 } as never)
    vi.mocked(mgmt.changeProductStatus).mockResolvedValue({} as never)
    renderRoutes(routes, ['/admin/products/new'])
    await fillBasics()
    await next(); await next()
    await userEvent.type(screen.getByLabelText(/store price/i), '50')
    await next(); await next()
    expect(screen.queryByRole('button', { name: 'Save and approve' })).toBeNull()  // no approve right
    await userEvent.click(screen.getByRole('button', { name: 'Submit for approval' }))
    await waitFor(() => expect(mgmt.changeProductStatus).toHaveBeenCalledWith(42, 'PENDING', expect.any(String)))
  })

  it('without pricing or stock rights those inputs are explained, not shown', async () => {
    vi.mocked(products.getMeta).mockResolvedValue(meta({ pricing: false, stock: false }) as never)
    renderRoutes(routes, ['/admin/products/new'])
    await fillBasics()
    await next()
    expect(screen.queryByLabelText(/stock on hand/i)).toBeNull()
    expect(screen.getByText(/can’t record stock/i)).toBeInTheDocument()
    await next()
    expect(screen.queryByLabelText(/^selling price/i)).toBeNull()
    expect(screen.getByText(/set by someone with pricing rights/i)).toBeInTheDocument()
  })

  it('if a later step fails, the product is not created twice', async () => {
    vi.mocked(products.getMeta).mockResolvedValue(meta() as never)
    vi.mocked(products.createProduct).mockResolvedValue({ id: 43 } as never)
    vi.mocked(mgmt.setPricing).mockRejectedValue(Object.assign(new Error('x'), { isAxiosError: true, response: { status: 400, data: { detail: 'Price refused.' } } }))
    renderRoutes(routes, ['/admin/products/new'])
    await fillBasics()
    await next(); await next()
    await userEvent.type(screen.getByLabelText(/store price/i), '600')
    await userEvent.type(screen.getByLabelText(/^selling price/i), '800')
    await next(); await next()
    await userEvent.click(screen.getByRole('button', { name: 'Save draft' }))
    expect(await screen.findByText(/one step did not finish/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open the product' })).toHaveAttribute('href', '/admin/products/43')
    expect(products.createProduct).toHaveBeenCalledTimes(1)
  })
})
