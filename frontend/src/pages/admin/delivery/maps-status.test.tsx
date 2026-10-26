import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ToastProvider } from '@/components/kit'
import { PinConfirmation } from '@/pages/admin/stores/PinConfirmation'
import MapsStatusPage from './MapsStatusPage'
import type { StoreDetail } from '@/types/management'

vi.mock('@/services/delivery', async (orig) => ({ ...(await orig<object>()), mapsStatus: vi.fn(), runMapsHealthCheck: vi.fn(), confirmStorePin: vi.fn() }))
import * as delivery from '@/services/delivery'

const wrap = (ui: React.ReactElement) => render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}><ToastProvider><MemoryRouter>{ui}</MemoryRouter></ToastProvider></QueryClientProvider>)

const status = (over = {}) => ({
  configuration: { server_key_present: true, geocoder: 'google', router: 'google', travel_mode: 'TWO_WHEELER', timeout_seconds: 5, store_pin_confirmation_required: false },
  checks: { PLACES: { latest: null, last_success_at: null }, GEOCODING: { latest: null, last_success_at: null }, ROUTES: { latest: null, last_success_at: null } },
  ...over,
})

beforeEach(() => vi.resetAllMocks())

describe('Google Maps status page', () => {
  it('shows configuration presence and "never checked" without claiming anything works', async () => {
    vi.mocked(delivery.mapsStatus).mockResolvedValue(status() as never)
    wrap(<MapsStatusPage />)
    expect(await screen.findByText('Present')).toBeInTheDocument()
    expect(screen.getAllByText('Never checked.')).toHaveLength(3)
    expect(screen.queryByText('Working')).not.toBeInTheDocument()
  })

  it('warns when Google is not switched on', async () => {
    vi.mocked(delivery.mapsStatus).mockResolvedValue(status({ configuration: { ...status().configuration, server_key_present: false, geocoder: 'none', router: 'none' } }) as never)
    wrap(<MapsStatusPage />)
    expect(await screen.findByText(/Google is not fully switched on/)).toBeInTheDocument()
    expect(screen.getByText('Missing')).toBeInTheDocument()
  })

  it('runs a health check and shows a rejected key in plain language', async () => {
    vi.mocked(delivery.mapsStatus).mockResolvedValueOnce(status() as never)
    vi.mocked(delivery.runMapsHealthCheck).mockResolvedValue({} as never)
    const failed = { ok: false, error_code: 'KEY_REJECTED', message: 'Google rejected the key. Check the key, its API restrictions and that this API is enabled.', latency_ms: null, checked_at: '2026-10-26T10:00:00Z' }
    vi.mocked(delivery.mapsStatus).mockResolvedValue(status({ checks: { PLACES: { latest: null, last_success_at: null }, GEOCODING: { latest: failed, last_success_at: null }, ROUTES: { latest: { ...failed, ok: true, error_code: '', message: 'Responded normally.', latency_ms: 120 }, last_success_at: '2026-10-26T10:00:00Z' } } }) as never)
    wrap(<MapsStatusPage />)
    await userEvent.click(await screen.findByRole('button', { name: /run health check/i }))
    expect(await screen.findByText(/Google rejected the key/)).toBeInTheDocument()
    expect(screen.getByText('Failed: key rejected')).toBeInTheDocument()
    expect(screen.getByText('Working')).toBeInTheDocument()
    expect(delivery.runMapsHealthCheck).toHaveBeenCalledTimes(1)
  })

  it('shows a retryable error if the status cannot load', async () => {
    vi.mocked(delivery.mapsStatus).mockRejectedValue(new Error('boom'))
    wrap(<MapsStatusPage />)
    expect(await screen.findByText('Could not load this')).toBeInTheDocument()
  })
})

const store = (over: Partial<StoreDetail> = {}) => ({
  id: 4, address: { latitude: '9.931233', longitude: '76.267303' },
  location: { confirmed: false, confirmed_at: null, confirmed_by: null, problems: [] }, ...over,
}) as unknown as StoreDetail

describe('store pin confirmation', () => {
  it('lets a manager confirm an unconfirmed pin', async () => {
    vi.mocked(delivery.confirmStorePin).mockResolvedValue({})
    wrap(<PinConfirmation store={store()} canChange />)
    await userEvent.click(screen.getByRole('button', { name: /confirm this pin/i }))
    await waitFor(() => expect(delivery.confirmStorePin).toHaveBeenCalledWith(4))
  })

  it('hides the button without permission, and shows who confirmed once done', () => {
    const { unmount } = wrap(<PinConfirmation store={store()} canChange={false} />)
    expect(screen.getByText(/Pin not confirmed yet/)).toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
    unmount()
    wrap(<PinConfirmation store={store({ location: { confirmed: true, confirmed_at: '2026-10-26T10:00:00Z', confirmed_by: 'admin', problems: [] } })} canChange />)
    expect(screen.getByText(/confirmed by admin/i)).toBeInTheDocument()
  })

  it('shows nothing when there is no pin yet', () => {
    wrap(<PinConfirmation store={store({ address: { latitude: '0', longitude: '0' } as never })} canChange />)
    expect(screen.queryByText(/Pin not confirmed/)).not.toBeInTheDocument()
  })
})

describe('website map provider', () => {
  it('says plainly when this build has no web key and is using OpenStreetMap', async () => {
    vi.mocked(delivery.mapsStatus).mockResolvedValue(status() as never)
    wrap(<MapsStatusPage />)
    expect(await screen.findByTestId('website-map')).toHaveTextContent(/OpenStreetMap/)
    expect(screen.getByText(/VITE_GOOGLE_MAPS_BROWSER_KEY/)).toBeInTheDocument()
  })
})
