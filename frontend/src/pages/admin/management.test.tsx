import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { routes } from '@/app/router'
import { BulkDialog, Tabs, emptySelection } from '@/components/management'
import { ToastProvider } from '@/components/kit'
import { Button, ButtonLink } from '@/components/ui'
import { adminSession, renderRoutes } from '@/test/utils'

vi.mock('@/services/auth', () => ({ fetchSession: vi.fn(), login: vi.fn(), logout: vi.fn() }))
vi.mock('@/services/ops', () => ({ adminCounts: vi.fn(), adminSearch: vi.fn() }))
vi.mock('@/services/platform', async (orig) => ({ ...(await orig<object>()), unreadCount: vi.fn().mockResolvedValue(0) }))
vi.mock('@/services/management', async (orig) => ({
  ...(await orig<object>()),
  storeMeta: vi.fn(), listStores: vi.fn(), createStore: vi.fn(), bulkPreview: vi.fn(), bulkApply: vi.fn(), approvalCenter: vi.fn(),
  uploadStoreImages: vi.fn(), uploadStoreDocument: vi.fn(),
}))

import * as auth from '@/services/auth'
import * as mgmt from '@/services/management'
import * as ops from '@/services/ops'

const meta = (over = {}) => ({ categories: [{ id: 3, name: 'Grocery' }], types: [{ value: 'PARTNER_STORE', label: 'Partner Store' }], statuses: [], days: ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'], can_add: true, can_change: true, can_approve: true, ...over })
const row = (id: number, over = {}) => ({ id, store_code: `ST${id}`, name: `Store ${id}`, slug: null, status: 'PENDING', is_active: true, store_type: 'PARTNER_STORE', city: 'Kochi', state: 'Kerala', category: 'Grocery', category_id: 3, verification_status: 'UNVERIFIED', ordering_enabled: true, missing_requirements: [], contact_phone: '', created_at: '2026-10-01T00:00:00Z', image: null, rating: { average: 0, count: 0 }, ...over })

beforeEach(() => {
  vi.resetAllMocks()
  localStorage.clear()
  vi.mocked(auth.fetchSession).mockResolvedValue(adminSession as never)
  vi.mocked(ops.adminCounts).mockResolvedValue({ orders_awaiting_confirmation: 0, deliveries_needing_attention: 0, partners_pending: 0, stores_pending: 1, products_pending: 0, tickets_open: 0, complaints_open: 0, stores_needs_info: 0 })
  vi.mocked(mgmt.storeMeta).mockResolvedValue(meta())
})

describe('buttons', () => {
  it('ButtonLink is a real link and never wraps a button', () => {
    render(<MemoryRouter><ButtonLink to="/x" size="lg">Go</ButtonLink><ButtonLink href="/file.csv" variant="outline">Download</ButtonLink></MemoryRouter>)
    const go = screen.getByRole('link', { name: 'Go' })
    expect(go).toHaveAttribute('href', '/x')
    expect(go.querySelector('button')).toBeNull()
    expect(go.className).toMatch(/min-h-12/)
    expect(screen.getByRole('link', { name: 'Download' })).toHaveAttribute('href', '/file.csv')
  })
  it('uses one height scale and gives icon-only buttons a name and tooltip', () => {
    render(<><Button size="sm">S</Button><Button>M</Button><Button size="lg">L</Button><Button iconOnly aria-label="Close panel" /></>)
    expect(screen.getByRole('button', { name: 'S' }).className).toMatch(/min-h-9/)
    expect(screen.getByRole('button', { name: 'M' }).className).toMatch(/min-h-11/)
    expect(screen.getByRole('button', { name: 'L' }).className).toMatch(/min-h-12/)
    expect(screen.getByRole('button', { name: 'Close panel' })).toHaveAttribute('title', 'Close panel')
  })
})

describe('tabs', () => {
  it('moves with arrow keys and marks the selected tab', async () => {
    const onChange = vi.fn()
    render(<Tabs label="Sections" active="a" onChange={onChange} tabs={[{ id: 'a', label: 'A' }, { id: 'b', label: 'B', badge: 2 }]} />)
    expect(screen.getByRole('tab', { name: 'A' })).toHaveAttribute('aria-selected', 'true')
    screen.getByRole('tab', { name: 'A' }).focus()
    await userEvent.keyboard('{ArrowRight}')
    expect(onChange).toHaveBeenCalledWith('b')
  })
})

describe('stores list', () => {
  it('offers Add store as a link-button and a per-row action menu', async () => {
    vi.mocked(mgmt.listStores).mockResolvedValue({ count: 1, next: null, previous: null, results: [row(1)] })
    renderRoutes(routes, ['/admin/stores'])
    expect(await screen.findByRole('link', { name: /add store/i })).toHaveAttribute('href', '/admin/stores/new')
    expect((await screen.findAllByText('Store 1'))[0]).toBeInTheDocument()
    await userEvent.click((await screen.findAllByRole('button', { name: 'Actions for Store 1' }))[0]!)
    const menu = screen.getByRole('menu')
    expect(within(menu).getByRole('menuitem', { name: 'Approve' })).toBeInTheDocument()
    expect(within(menu).getByRole('menuitem', { name: 'Reject' })).toBeInTheDocument()
  })
  it('hides Add store without permission', async () => {
    vi.mocked(mgmt.storeMeta).mockResolvedValue(meta({ can_add: false, can_approve: false }))
    vi.mocked(mgmt.listStores).mockResolvedValue({ count: 1, next: null, previous: null, results: [row(1)] })
    renderRoutes(routes, ['/admin/stores'])
    await screen.findAllByText('Store 1')
    expect(within(screen.getByRole('main')).queryByRole('link', { name: /add store/i })).toBeNull()
    expect(screen.queryByRole('checkbox', { name: /select Store 1/i })).toBeNull()
  })
  it('selecting rows shows the bulk bar and offers select-all across pages', async () => {
    vi.mocked(mgmt.listStores).mockResolvedValue({ count: 45, next: 'x', previous: null, results: [row(1), row(2)] })
    renderRoutes(routes, ['/admin/stores'])
    await screen.findAllByText('Store 1')
    await userEvent.click(screen.getByRole('checkbox', { name: 'Select all stores on this page' }))
    const bar = await screen.findByRole('region', { name: 'Bulk actions' })
    expect(within(bar).getByText('2 selected')).toBeInTheDocument()
    await userEvent.click(within(bar).getByRole('button', { name: 'Select all 45 matching' }))
    expect(within(bar).getByText('All 45 matching selected')).toBeInTheDocument()
  })
})

describe('add store wizard', () => {
  it('cannot be saved without a name and category, and sends draft vs final separately', async () => {
    vi.mocked(mgmt.createStore).mockResolvedValue({ id: 9, store_code: 'ST9', status: 'DRAFT', missing: [], operational_gaps: [] })
    renderRoutes(routes, ['/admin/stores/new'])
    const save = await screen.findByRole('button', { name: 'Save store' })
    expect(save).toBeDisabled()
    await userEvent.type(screen.getByLabelText(/store name/i), 'Green Basket')
    await userEvent.selectOptions(screen.getByLabelText(/^category/i), '3')
    expect(save).toBeEnabled()
    await userEvent.click(screen.getByRole('button', { name: 'Save draft' }))
    await waitFor(() => expect(mgmt.createStore).toHaveBeenCalledTimes(1))
    const body = vi.mocked(mgmt.createStore).mock.calls[0]![0] as unknown as Record<string, unknown>
    expect(body.save_draft).toBe(true)
    expect(body.name).toBe('Green Basket')
    expect(body).not.toHaveProperty('status')
    expect(body).not.toHaveProperty('approved_by')
    expect((body.address as Record<string, unknown>)).not.toHaveProperty('latitude') // empty location is omitted, never invented
  })
  it('shows the server’s field errors next to the fields', async () => {
    const error = Object.assign(new Error('bad'), { isAxiosError: true, response: { status: 400, data: { gstin: ['Enter a valid 15-character GSTIN.'] } } })
    vi.mocked(mgmt.createStore).mockRejectedValue(error)
    renderRoutes(routes, ['/admin/stores/new'])
    await userEvent.type(await screen.findByLabelText(/store name/i), 'X')
    await userEvent.selectOptions(screen.getByLabelText(/^category/i), '3')
    await userEvent.click(screen.getByRole('button', { name: 'Save store' }))
    expect(await screen.findByText(/please fix these before saving/i)).toBeInTheDocument()
  })
})

describe('bulk dialog', () => {
  const wrap = (ui: React.ReactElement) => render(<QueryClientProvider client={new QueryClient()}><ToastProvider>{ui}</ToastProvider></QueryClientProvider>)
  const preview = { module: 'products', action: 'approve', total: 3, needs_reason: false, eligible_count: 2, blocked_count: 1, warning_count: 1,
    eligible: [{ id: 1, label: 'Rice', warnings: ['Generated by import: sku'] }, { id: 2, label: 'Dal' }], blocked: [{ id: 3, label: 'Bare', reasons: ['Product must have at least one valid image.'] }] }

  it('previews first, shows why records are blocked, and reports successful, skipped and failed separately', async () => {
    vi.mocked(mgmt.bulkPreview).mockResolvedValue(preview as never)
    vi.mocked(mgmt.bulkApply).mockResolvedValue({ module: 'products', action: 'approve', counts: { successful: 1, skipped: 1, failed: 0 },
      successful: [{ id: 1, label: 'Rice' }], skipped: [{ id: 2, label: 'Dal', reasons: ['Changed since the preview.'] }], failed: [] } as never)
    const onDone = vi.fn()
    wrap(<BulkDialog module="products" def={{ action: 'approve', label: 'Approve' }} selection={{ ids: new Set([1, 2, 3]), selectAll: false }} filters={{}} total={3} onClose={vi.fn()} onDone={onDone} />)
    expect(await screen.findByText(/can be changed/i)).toBeInTheDocument()
    expect(screen.getByText(/at least one valid image/i)).toBeInTheDocument()
    expect(screen.getByText(/filled in automatically/i)).toBeInTheDocument()
    expect(mgmt.bulkApply).not.toHaveBeenCalled()  // nothing happens until the explicit confirmation
    await userEvent.click(screen.getByRole('button', { name: 'Approve 2 records' }))
    expect(await screen.findByText(/Changed since the preview/)).toBeInTheDocument()
    expect(mgmt.bulkApply).toHaveBeenCalledTimes(1)
    expect(onDone).toHaveBeenCalled()
  })
  it('asks for a reason before it checks anything, and confirms the count when everything matching is selected', async () => {
    vi.mocked(mgmt.bulkPreview).mockResolvedValue({ ...preview, total: 45, eligible_count: 45, blocked_count: 0, needs_reason: true } as never)
    wrap(<BulkDialog module="products" def={{ action: 'reject', label: 'Reject', needsReason: true, danger: true }} selection={{ ids: new Set(), selectAll: true }} filters={{ status: 'PENDING' }} total={45} onClose={vi.fn()} onDone={vi.fn()} />)
    const check = await screen.findByRole('button', { name: /check 45 selected/i })
    expect(check).toBeDisabled()
    expect(mgmt.bulkPreview).not.toHaveBeenCalled()
    await userEvent.type(screen.getByLabelText(/reason/i), 'Wrong category')
    await userEvent.click(check)
    await waitFor(() => expect(mgmt.bulkPreview).toHaveBeenCalledWith('products', expect.objectContaining({ select_all: true, filters: { status: 'PENDING' }, reason: 'Wrong category' })))
    vi.mocked(mgmt.bulkApply).mockResolvedValue({ module: 'products', action: 'reject', counts: { successful: 45, skipped: 0, failed: 0 }, successful: [], skipped: [], failed: [] } as never)
    await userEvent.click(await screen.findByRole('button', { name: /reject 45 records/i }))
    await waitFor(() => expect(mgmt.bulkApply).toHaveBeenCalledWith('products', expect.objectContaining({ expected_count: 45, select_all: true })))
  })
  it('exposes an empty selection helper', () => expect(emptySelection().ids.size).toBe(0))
})

describe('approval center', () => {
  it('lists each queue with its count and a review link', async () => {
    vi.mocked(mgmt.approvalCenter).mockResolvedValue({ total: 3, not_available: ['Promotions'], queues: [
      { key: 'products', title: 'Products awaiting approval', count: 2, link: '/admin/approvals/products', note: null, items: [{ id: 1, label: 'Rice · Mart', generated: ['sku'] }] },
      { key: 'partners', title: 'Delivery partner applications', count: 0, link: '/admin/approvals/partners', note: null, items: [] },
    ] } as never)
    renderRoutes(routes, ['/admin/approvals'])
    expect(await screen.findByRole('heading', { name: 'Approval center' })).toBeInTheDocument()
    expect(await screen.findByRole('link', { name: /review 2/i })).toHaveAttribute('href', '/admin/approvals/products')
    expect(screen.getByText('auto-filled')).toBeInTheDocument()
    expect(screen.getByText('All clear.')).toBeInTheDocument()
    expect(screen.getByText(/Promotions/)).toBeInTheDocument()
  })
})
