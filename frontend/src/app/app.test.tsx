import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { routes } from './router'
import { adminSession, renderRoutes } from '@/test/utils'

vi.mock('@/services/auth', () => ({ fetchSession: vi.fn(), login: vi.fn(), logout: vi.fn() }))
vi.mock('@/services/products', () => ({ listProducts: vi.fn(), getMeta: vi.fn(), getProduct: vi.fn() }))

import * as auth from '@/services/auth'
import * as products from '@/services/products'

const emptyPage = { count: 0, next: null, previous: null, results: [] }
const meta = { stores: [], categories: [], brands: [], tags: [], units: [], statuses: [], limits: { max_images: 8 } }

beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(products.getMeta).mockResolvedValue(meta as never)
})

describe('session & routing', () => {
  it('sends anonymous visitors to the login page', async () => {
    vi.mocked(auth.fetchSession).mockResolvedValue({ authenticated: false, user: null })
    renderRoutes(routes, ['/admin/products'])
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
  })

  it('restores the session on load (page refresh) and shows products', async () => {
    vi.mocked(auth.fetchSession).mockResolvedValue(adminSession)
    vi.mocked(products.listProducts).mockResolvedValue(emptyPage)
    renderRoutes(routes, ['/admin/products'])
    expect(await screen.findByRole('heading', { name: 'Products' })).toBeInTheDocument()
    expect(auth.fetchSession).toHaveBeenCalledTimes(1)
  })

  it('shows a retry state when the session check fails', async () => {
    vi.mocked(auth.fetchSession).mockRejectedValue(new Error('down'))
    renderRoutes(routes, ['/admin/products'])
    expect(await screen.findByText(/could not check your session/i, {}, { timeout: 4000 })).toBeInTheDocument()
  })

  it('blocks add-product for users without the add permission', async () => {
    vi.mocked(auth.fetchSession).mockResolvedValue({ ...adminSession, user: { ...adminSession.user, permissions: { view: true, add: false, change: false } } })
    renderRoutes(routes, ['/admin/products/new'])
    expect(await screen.findByText(/don’t have access/i)).toBeInTheDocument()
  })

  it('signs an administrator in and lands on the admin overview', async () => {
    vi.mocked(auth.fetchSession).mockResolvedValue({ authenticated: false, user: null })
    vi.mocked(auth.login).mockResolvedValue(adminSession)
    vi.mocked(products.listProducts).mockResolvedValue(emptyPage)
    renderRoutes(routes, ['/login'])
    await userEvent.type(await screen.findByLabelText('Username'), 'admin')
    await userEvent.type(screen.getByLabelText('Password'), 'secret')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    await waitFor(() => expect(auth.login).toHaveBeenCalledWith('admin', 'secret'))
    expect(await screen.findByRole('heading', { name: 'Overview' })).toBeInTheDocument()
  })

  it('validates the login form before calling the server', async () => {
    vi.mocked(auth.fetchSession).mockResolvedValue({ authenticated: false, user: null })
    renderRoutes(routes, ['/login'])
    await userEvent.click(await screen.findByRole('button', { name: 'Sign in' }))
    expect(auth.login).not.toHaveBeenCalled()
  })
})

describe('products list states', () => {
  beforeEach(() => vi.mocked(auth.fetchSession).mockResolvedValue(adminSession))

  it('shows an empty state', async () => {
    vi.mocked(products.listProducts).mockResolvedValue(emptyPage)
    renderRoutes(routes, ['/admin/products'])
    expect(await screen.findByText('No products yet')).toBeInTheDocument()
  })

  it('shows an error state with retry', async () => {
    vi.mocked(products.listProducts).mockRejectedValue(new Error('500'))
    renderRoutes(routes, ['/admin/products'])
    expect(await screen.findByText('The product list could not be loaded.')).toBeInTheDocument()
  })

  it('renders products with a placeholder when there is no photo', async () => {
    vi.mocked(products.listProducts).mockResolvedValue({
      count: 1, next: null, previous: null,
      results: [{
        id: 5, product_code: 'P-5', name: 'Basmati rice', sku: 'RICE1', slug: 'rice', store: { id: 1, name: 'Store', store_code: 'S1' },
        category: { id: 1, name: 'Grains' }, brand: null, status: 'DRAFT', is_active: true, unit: 'kg', unit_value: '1.000',
        store_price: '90.00', selling_price: null, final_price: null, stock_quantity: '4.000', updated_at: '2026-01-01T00:00:00Z',
        image: { source: 'fallback', alt_text: '', thumbnail_url: null, display_url: null, fallback: { category: 'Grains', category_slug: 'grains', brand: '' } },
      }],
    } as never)
    renderRoutes(routes, ['/admin/products'])
    expect(await screen.findAllByText('Basmati rice')).not.toHaveLength(0)
    expect(document.querySelector('img[src=""]')).toBeNull()
  })
})
