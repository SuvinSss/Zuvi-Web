import { screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { routes } from './router'
import { adminSession, renderRoutes } from '@/test/utils'

vi.mock('@/services/auth', () => ({ fetchSession: vi.fn(), login: vi.fn(), logout: vi.fn() }))
vi.mock('@/services/ops', () => ({ storeMe: vi.fn(), partnerMe: vi.fn(), listAssignments: vi.fn() }))
vi.mock('@/services/platform', async (orig) => ({ ...(await orig<object>()), unreadCount: vi.fn().mockResolvedValue(0), listPublicProducts: vi.fn(), listCategories: vi.fn().mockResolvedValue([]), getCart: vi.fn().mockResolvedValue({ items: [], item_count: 0, subtotal: '0', has_issues: false }) }))

import * as auth from '@/services/auth'
import * as ops from '@/services/ops'

const user = (role: string, extra: object = {}) => ({ ...adminSession, user: { ...adminSession.user, role, is_management: false, permissions: { view: false, add: false, change: false }, ...extra } })

beforeEach(() => vi.resetAllMocks())

describe('role-based access', () => {
  it('sends anonymous visitors from the customer area to sign in', async () => {
    vi.mocked(auth.fetchSession).mockResolvedValue({ authenticated: false, user: null })
    renderRoutes(routes, ['/account/orders'])
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
  })

  it.each([['/admin'], ['/store'], ['/delivery'], ['/support']])('does not let a customer open %s', async (path) => {
    vi.mocked(auth.fetchSession).mockResolvedValue(user('CUSTOMER') as never)
    renderRoutes(routes, [path])
    expect(await screen.findByText(/don’t have access to this page/i)).toBeInTheDocument()
  })

  it('does not let a store user open the admin area', async () => {
    vi.mocked(auth.fetchSession).mockResolvedValue(user('STORE_USER') as never)
    renderRoutes(routes, ['/admin/users'])
    expect(await screen.findByText(/don’t have access to this page/i)).toBeInTheDocument()
  })

  it('shows a pending delivery partner their status instead of work screens', async () => {
    vi.mocked(auth.fetchSession).mockResolvedValue(user('DELIVERY_AGENT') as never)
    vi.mocked(ops.partnerMe).mockResolvedValue({ status: 'PENDING', status_reason: '' } as never)
    renderRoutes(routes, ['/delivery'])
    expect(await screen.findByText(/application is being reviewed/i)).toBeInTheDocument()
    expect(ops.listAssignments).not.toHaveBeenCalled()
  })

  it('shows the store dashboard to a store user', async () => {
    vi.mocked(auth.fetchSession).mockResolvedValue(user('STORE_USER', { store: { id: 1, name: 'Fresh Mart', code: 'ST1', can_manage_orders: true, can_manage_inventory: true } }) as never)
    vi.mocked(ops.storeMe).mockResolvedValue({ store: { id: 1, name: 'Fresh Mart', code: 'ST1', status: 'ACTIVE' }, membership: {}, orders_by_status: { PENDING: 3 }, low_stock_products: 2, rating: null } as never)
    renderRoutes(routes, ['/store'])
    expect(await screen.findByRole('heading', { name: 'Fresh Mart' })).toBeInTheDocument()
    expect(screen.getByText('Waiting for you')).toBeInTheDocument()
  })

  it('warns when a store is not active', async () => {
    vi.mocked(auth.fetchSession).mockResolvedValue(user('STORE_USER') as never)
    vi.mocked(ops.storeMe).mockResolvedValue({ store: { id: 1, name: 'Fresh Mart', code: 'ST1', status: 'SUSPENDED' }, membership: {}, orders_by_status: {}, low_stock_products: 0, rating: null } as never)
    renderRoutes(routes, ['/store'])
    expect(await screen.findByText(/your store is suspended/i)).toBeInTheDocument()
  })

  it('shows a not-found page for unknown addresses', async () => {
    vi.mocked(auth.fetchSession).mockResolvedValue({ authenticated: false, user: null })
    renderRoutes(routes, ['/definitely/not/here'])
    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
  })
})
