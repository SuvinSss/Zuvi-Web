import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { routes } from '@/app/router'
import { BulkDialog } from '@/components/management'
import { PricingPanel } from '@/components/PricingPanel'
import { ToastProvider } from '@/components/kit'
import { adminSession, renderRoutes } from '@/test/utils'
import type { ProductDetail } from '@/types/api'

vi.mock('@/services/auth', () => ({ fetchSession: vi.fn(), login: vi.fn(), logout: vi.fn() }))
vi.mock('@/services/ops', () => ({ adminCounts: vi.fn(), adminSearch: vi.fn() }))
vi.mock('@/services/platform', async (orig) => ({ ...(await orig<object>()), unreadCount: vi.fn().mockResolvedValue(0) }))
vi.mock('@/services/management', async (orig) => ({
  ...(await orig<object>()),
  pricingPreview: vi.fn(), setPricing: vi.fn(), storeMeta: vi.fn(), createStore: vi.fn(), ownerCandidates: vi.fn(), acceptInvite: vi.fn(),
  bulkPreview: vi.fn(), bulkApply: vi.fn(),
}))

import * as auth from '@/services/auth'
import * as mgmt from '@/services/management'
import * as ops from '@/services/ops'

const product = { id: 7, store_price: '600.00', selling_price: null, final_price: null, discount_type: '', discount_value: '0.00' } as unknown as ProductDetail
const breakdown = (over = {}) => ({ cost: '600.00', selling_price: '800.00', discount_amount: '100.00', final_price: '700.00', profit_per_unit: '100.00', margin_percent: '14.29', markup_percent: '16.67', label: 'Estimated gross profit (before tax, fees and commission)', warnings: [], below_cost: false, ...over })
const wrap = (ui: React.ReactElement) => render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><ToastProvider><MemoryRouter>{ui}</MemoryRouter></ToastProvider></QueryClientProvider>)

beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(auth.fetchSession).mockResolvedValue(adminSession as never)
  vi.mocked(ops.adminCounts).mockResolvedValue({ orders_awaiting_confirmation: 0, deliveries_needing_attention: 0, partners_pending: 0, stores_pending: 0, products_pending: 0, tickets_open: 0, complaints_open: 0, stores_needs_info: 0 })
})

describe('pricing panel', () => {
  it('explains margin and markup separately and labels profit as estimated gross profit', async () => {
    vi.mocked(mgmt.pricingPreview).mockResolvedValue({ breakdown: breakdown() })
    wrap(<PricingPanel product={product} />)
    await userEvent.type(screen.getByLabelText(/selling price before discount/i), '800')
    expect(await screen.findByText('14.29%')).toBeInTheDocument()
    expect(screen.getByText('16.67%')).toBeInTheDocument()
    expect(screen.getByText(/Profit ÷ final price/)).toBeInTheDocument()
    expect(screen.getByText(/Profit ÷ store price/)).toBeInTheDocument()
    expect(screen.getByText(/Estimated gross profit/)).toBeInTheDocument()
    expect(mgmt.setPricing).not.toHaveBeenCalled()  // previewing never saves
  })

  it('a target margin only suggests a price; the person must choose to use it', async () => {
    vi.mocked(mgmt.pricingPreview).mockImplementation(async (b) => (b.target_margin ? { suggested_selling_price: '1000.00' } : { breakdown: breakdown() }))
    wrap(<PricingPanel product={product} />)
    await userEvent.click(screen.getByRole('radio', { name: /target margin/i }))
    await userEvent.type(screen.getByLabelText('Target margin (%)'), '40')
    expect(await screen.findByText(/Suggested selling price/)).toBeInTheDocument()
    expect(screen.getByLabelText(/selling price before discount/i)).toHaveValue('')  // untouched
    await userEvent.click(screen.getByRole('button', { name: 'Use this price' }))
    expect(screen.getByLabelText(/selling price before discount/i)).toHaveValue('1000.00')
  })

  it('refuses to save a loss-making price and sends only server-derivable inputs', async () => {
    vi.mocked(mgmt.pricingPreview).mockResolvedValue({ breakdown: breakdown({ final_price: '500.00', profit_per_unit: '-100.00', below_cost: true, warnings: ['The final price is below the store price, so every sale would lose money.'] }) })
    wrap(<PricingPanel product={product} />)
    await userEvent.type(screen.getByLabelText(/selling price before discount/i), '500')
    expect(await screen.findByText(/every sale would lose money/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save price' })).toBeDisabled()
  })

  it('saves selling price and discount only', async () => {
    vi.mocked(mgmt.pricingPreview).mockResolvedValue({ breakdown: breakdown() })
    vi.mocked(mgmt.setPricing).mockResolvedValue(product)
    wrap(<PricingPanel product={product} />)
    await userEvent.type(screen.getByLabelText(/selling price before discount/i), '800')
    await userEvent.selectOptions(screen.getByLabelText('Discount'), 'FIXED')
    await userEvent.type(screen.getByLabelText(/Discount \(₹\)/), '100')
    await screen.findByText('14.29%')
    await userEvent.click(screen.getByRole('button', { name: 'Save price' }))
    await waitFor(() => expect(mgmt.setPricing).toHaveBeenCalledTimes(1))
    const body = vi.mocked(mgmt.setPricing).mock.calls[0]![1]
    expect(body).toMatchObject({ selling_price: '800', discount_type: 'FIXED', discount_value: '100' })
    expect(body).not.toHaveProperty('final_price')
  })
})

describe('bulk pricing', () => {
  it('asks for the margin before checking anything', async () => {
    vi.mocked(mgmt.bulkPreview).mockResolvedValue({ module: 'products', action: 'set_pricing', total: 2, needs_reason: false, eligible_count: 2, blocked_count: 0, eligible: [], blocked: [], warning_count: 0 })
    const def = { action: 'set_pricing', label: 'Set margin', fields: [{ key: 'margin_type', label: 'Margin type', options: [{ value: 'PERCENTAGE', label: 'Percentage' }] }, { key: 'margin', label: 'Margin' }] }
    wrap(<BulkDialog module="products" def={def} selection={{ ids: new Set([1, 2]), selectAll: false }} filters={{}} total={2} onClose={vi.fn()} onDone={vi.fn()} />)
    const check = await screen.findByRole('button', { name: /check 2 selected/i })
    expect(check).toBeDisabled()
    expect(mgmt.bulkPreview).not.toHaveBeenCalled()
    await userEvent.selectOptions(screen.getByLabelText(/margin type/i), 'PERCENTAGE')
    await userEvent.type(screen.getByLabelText(/^margin/i, { selector: 'input' }), '20')
    await userEvent.click(check)
    await waitFor(() => expect(mgmt.bulkPreview).toHaveBeenCalledWith('products', expect.objectContaining({ params: { margin_type: 'PERCENTAGE', margin: '20' } })))
  })
})

describe('store owner onboarding', () => {
  beforeEach(() => {
    vi.mocked(mgmt.storeMeta).mockResolvedValue({ categories: [{ id: 3, name: 'Grocery' }], types: [{ value: 'PARTNER_STORE', label: 'Partner Store' }], statuses: [], days: [], can_add: true, can_change: true, can_approve: true } as never)
  })
  it('defaults to a setup link: no password is sent, and the link is shown once with honest e-mail status', async () => {
    vi.mocked(mgmt.createStore).mockResolvedValue({ id: 9, store_code: 'ST9', status: 'ACTIVE', missing: [], operational_gaps: [], owner_setup: { link: '/setup-account?token=abc', email_sent: false, expires_in_days: 3, email: 'o@x.test' } })
    renderRoutes(routes, ['/admin/stores/new'])
    await userEvent.type(await screen.findByLabelText(/store name/i), 'Green Basket')
    await userEvent.selectOptions(screen.getByLabelText(/^category/i), '3')
    for (let i = 0; i < 4; i++) await userEvent.click(screen.getByRole('button', { name: /^next/i }))
    expect(screen.getByRole('radio', { name: /setup link/i })).toBeChecked()
    expect(screen.queryByLabelText(/temporary password/i)).toBeNull()
    await userEvent.type(screen.getByLabelText('Username'), 'greenowner')
    await userEvent.type(screen.getByLabelText('Email'), 'o@x.test')
    await userEvent.click(screen.getByRole('button', { name: 'Save store' }))
    await waitFor(() => expect(mgmt.createStore).toHaveBeenCalled())
    const body = vi.mocked(mgmt.createStore).mock.calls[0]![0] as unknown as { owner: Record<string, unknown> }
    expect(body.owner.username).toBe('greenowner')
    expect(body.owner).not.toHaveProperty('password')
    expect(await screen.findByText(/No e-mail was sent/)).toBeInTheDocument()
    expect(screen.getByLabelText(/one-time setup link/i)).toHaveValue(`${window.location.origin}/setup-account?token=abc`)
  })
})

describe('setup account page', () => {
  it('checks the two passwords match, then confirms', async () => {
    vi.mocked(mgmt.acceptInvite).mockResolvedValue(undefined)
    renderRoutes(routes, ['/setup-account?token=tok123'])
    await userEvent.type(await screen.findByLabelText(/^new password/i), 'Fresh-Owner-Pass-77!')
    await userEvent.type(screen.getByLabelText(/confirm password/i), 'different')
    await userEvent.click(screen.getByRole('button', { name: 'Save password' }))
    expect(mgmt.acceptInvite).not.toHaveBeenCalled()
    await userEvent.clear(screen.getByLabelText(/confirm password/i))
    await userEvent.type(screen.getByLabelText(/confirm password/i), 'Fresh-Owner-Pass-77!')
    await userEvent.click(screen.getByRole('button', { name: 'Save password' }))
    await waitFor(() => expect(mgmt.acceptInvite).toHaveBeenCalledWith('tok123', 'Fresh-Owner-Pass-77!'))
    expect(await screen.findByText(/Password saved/)).toBeInTheDocument()
  })
  it('explains an incomplete link', async () => {
    renderRoutes(routes, ['/setup-account'])
    expect(await screen.findByText(/setup link is incomplete/i)).toBeInTheDocument()
  })
})
