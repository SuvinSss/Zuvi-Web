import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { routes } from '@/app/router'
import { BarList, TrendChart } from '@/components/charts'
import { adminSession, renderRoutes } from '@/test/utils'
import type { DashboardData } from '@/types/ops'

vi.mock('@/services/auth', () => ({ fetchSession: vi.fn(), login: vi.fn(), logout: vi.fn() }))
vi.mock('@/services/ops', () => ({
  adminDashboard: vi.fn(), adminCounts: vi.fn(), adminSearch: vi.fn(), adminCustomers: vi.fn(), adminCustomer: vi.fn(), downloadOrdersCsv: vi.fn(),
}))
vi.mock('@/services/platform', async (orig) => ({ ...(await orig<object>()), unreadCount: vi.fn().mockResolvedValue(3) }))

import * as auth from '@/services/auth'
import * as ops from '@/services/ops'

const kpi = (value: number | string, previous: number | string, change: number | null) => ({ value, previous, change_percent: change })
const data = (over: Partial<DashboardData> = {}): DashboardData => ({
  range: { from: '2026-10-01', to: '2026-10-03', days: 3, previous: { from: '2026-09-28', to: '2026-09-30' } },
  kpis: { orders: kpi(12, 8, 50), delivered: kpi(9, 0, null), revenue: kpi('4500.00', '0.00', null), cancelled: kpi(1, 1, 0), new_customers: kpi(4, 2, 100) },
  live: {
    orders_awaiting_confirmation: 2, orders_being_prepared: 3, orders_awaiting_delivery: 1, orders_in_transit: 1, deliveries_active: 2, deliveries_waiting_for_partner: 1,
    deliveries_needing_attention: 0, customers_total: 40, stores_active: 5, partners_active: 6, partners_online: 2, products_total: 120, products_active: 100, tickets_open: 0, complaints_open: 0,
  },
  series: [{ date: '2026-10-01', orders: 4, delivered: 3, revenue: '1500.00', cancelled: 0, new_customers: 1, failed_deliveries: 0 }, { date: '2026-10-02', orders: 8, delivered: 6, revenue: '3000.00', cancelled: 1, new_customers: 3, failed_deliveries: 0 }, { date: '2026-10-03', orders: 0, delivered: 0, revenue: '0.00', cancelled: 0, new_customers: 0, failed_deliveries: 0 }],
  status_distribution: [{ status: 'COMPLETED', count: 9 }, { status: 'PLACED', count: 2 }],
  top_stores: [{ store_id: 1, name: 'Fresh Mart', orders: 9, revenue: '4500.00' }],
  best_products: [], delivery_performance: { total: 10, delivered: 9, failed: 1, cancelled: 0, retried: 1, success_rate_percent: 90, average_minutes_assignment_to_delivery: 31.5 },
  queues: { recent_orders: [], needs_attention: { orders_unconfirmed_15_min: [], deliveries: [] }, new_customers: [], pending_stores: [], pending_partners: [], pending_complaints: [], recent_reviews: [], recent_feedback: [] },
  notes: { revenue: 'Value of orders delivered in the period.' },
  ...over,
})

beforeEach(() => {
  vi.resetAllMocks()
  localStorage.clear()
  vi.mocked(auth.fetchSession).mockResolvedValue(adminSession as never)
  vi.mocked(ops.adminCounts).mockResolvedValue({ orders_awaiting_confirmation: 2, deliveries_needing_attention: 0, partners_pending: 1, stores_pending: 0, products_pending: 0, tickets_open: 0, complaints_open: 0, stores_needs_info: 0 })
})

describe('admin dashboard', () => {
  it('shows real numbers, links cards to filtered lists, and refetches for a new period', async () => {
    vi.mocked(ops.adminDashboard).mockResolvedValue(data())
    renderRoutes(routes, ['/admin'])
    expect(await screen.findByRole('heading', { name: /welcome back/i })).toBeInTheDocument()
    const orders = (await screen.findByText('Orders placed')).closest('a')!
    expect(within(orders).getByText('12')).toBeInTheDocument()
    expect(within(orders).getByText('+50%')).toBeInTheDocument()
    expect(orders.getAttribute('href')).toMatch(/^\/admin\/orders\?from=\d{4}-\d{2}-\d{2}&to=\d{4}-\d{2}-\d{2}$/)
    expect(screen.getByText('Awaiting confirmation').closest('a')).toHaveAttribute('href', '/admin/orders?status=PLACED')
    // no earlier data: the UI says so instead of inventing 0% or infinity
    expect(screen.getAllByText('No earlier data to compare').length).toBeGreaterThan(0)
    const callsBefore = vi.mocked(ops.adminDashboard).mock.calls.length
    await userEvent.click(screen.getByRole('button', { name: '7 days' }))
    await waitFor(() => expect(vi.mocked(ops.adminDashboard).mock.calls.length).toBeGreaterThan(callsBefore))
    const last = vi.mocked(ops.adminDashboard).mock.calls.at(-1)![0]
    const days = (new Date(last.to!).getTime() - new Date(last.from!).getTime()) / 86_400_000
    expect(days).toBe(6)
  })

  it('shows an error with retry instead of fake numbers', async () => {
    vi.mocked(ops.adminDashboard).mockRejectedValue(new Error('boom'))
    renderRoutes(routes, ['/admin'])
    expect(await screen.findByRole('button', { name: /try again|retry/i })).toBeInTheDocument()
    expect(screen.queryByText('Orders placed')).not.toBeInTheDocument()
  })

  it('shows pending counts on the sidebar and remembers a collapsed sidebar', async () => {
    vi.mocked(ops.adminDashboard).mockResolvedValue(data())
    renderRoutes(routes, ['/admin'])
    expect(await screen.findByLabelText('2 waiting')).toBeInTheDocument() // orders awaiting confirmation
    await userEvent.click(await screen.findByRole('button', { name: 'Collapse sidebar' }))
    expect(localStorage.getItem('zuuvi.nav.collapsed')).toBe('1')
    expect(await screen.findByRole('button', { name: 'Expand sidebar' })).toBeInTheDocument()
  })

  it('global search lists matches and needs at least two characters', async () => {
    vi.mocked(ops.adminDashboard).mockResolvedValue(data())
    vi.mocked(ops.adminSearch).mockResolvedValue({ query: 'ZU', results: [{ type: 'Order', label: 'ZU-1001', detail: 'PLACED', path: '/admin/orders/5' }] })
    renderRoutes(routes, ['/admin'])
    const box = await screen.findByRole('searchbox', { name: /search orders/i })
    await userEvent.type(box, 'Z')
    expect(ops.adminSearch).not.toHaveBeenCalled()
    await userEvent.type(box, 'U')
    expect(await screen.findByText('ZU-1001')).toBeInTheDocument()
  })
})

describe('charts', () => {
  it('renders an empty message rather than a flat chart when there is no activity', () => {
    render(<TrendChart title="Orders per day" points={[{ label: '2026-10-01', value: 0 }, { label: '2026-10-02', value: 0 }]} />)
    expect(screen.getByText('No activity in this period.')).toBeInTheDocument()
  })

  it('exposes the numbers as a table for assistive technology', () => {
    render(<TrendChart title="Orders per day" kind="bar" points={[{ label: '2026-10-01', value: 4 }, { label: '2026-10-02', value: 8 }]} />)
    expect(screen.getByRole('img', { name: /Orders per day. Total 12/ })).toBeInTheDocument()
    expect(screen.getByRole('table', { name: 'Orders per day' })).toBeInTheDocument()
  })

  it('ranks bars and handles no data', () => {
    const { rerender } = render(<BarList rows={[]} empty="Nothing here." />)
    expect(screen.getByText('Nothing here.')).toBeInTheDocument()
    rerender(<BarList rows={[{ key: 'a', label: 'A', value: 5 }, { key: 'b', label: 'B', value: 10 }]} />)
    expect(screen.getAllByRole('listitem')).toHaveLength(2)
  })
})

describe('customers list', () => {
  it('lists customers and shows an empty state with a reset action when filters match nothing', async () => {
    vi.mocked(ops.adminCustomers).mockResolvedValue({ count: 0, next: null, previous: null, results: [] } as never)
    renderRoutes(routes, ['/admin/customers?q=nobody'])
    expect(await screen.findByText('No customers match these filters')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Reset filters' })).toBeInTheDocument()
  })
})
