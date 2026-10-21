import { screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { renderWithClient } from '@/test/utils'
import { OrderTrackingPanel } from './tracking'

vi.mock('@/services/platform', () => ({ getTracking: vi.fn() }))
import * as platform from '@/services/platform'

const base = { delivery_id: 1, status: 'IN_TRANSIT', status_label: 'On the way', attempt_number: 1, partner: { id: 2, first_name: 'Ravi', vehicle_type: 'SCOOTER' }, eta: null, dropoff: null, timeline: [], store_order_number: 'S1', store_name: 'Fresh Mart' }
beforeEach(() => vi.resetAllMocks())

describe('order tracking', () => {
  it('flags a stale location and never shows an invented ETA', async () => {
    vi.mocked(platform.getTracking).mockResolvedValue({ order_id: 1, order_number: 'ZV1', order_status: 'IN_PROGRESS', deliveries: [{ ...base, location: { latitude: 12.9, longitude: 77.6, recorded_at: '2026-01-01T00:00:00Z', age_seconds: 600, is_stale: true } }] })
    renderWithClient(<OrderTrackingPanel orderId={1} active />)
    expect(await screen.findByText(/has not updated recently/i)).toBeInTheDocument()
    expect(screen.getByText(/estimates are not available/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /open in maps/i })).toHaveAttribute('href', expect.stringContaining('12.9'))
  })

  it('says live location is missing instead of faking a position', async () => {
    vi.mocked(platform.getTracking).mockResolvedValue({ order_id: 1, order_number: 'ZV1', order_status: 'IN_PROGRESS', deliveries: [{ ...base, location: null }] })
    renderWithClient(<OrderTrackingPanel orderId={1} active />)
    expect(await screen.findByText(/live location has not been shared yet/i)).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /open in maps/i })).not.toBeInTheDocument()
  })

  it('shows the delivery code only when the API provides it', async () => {
    vi.mocked(platform.getTracking).mockResolvedValue({ order_id: 1, order_number: 'ZV1', order_status: 'IN_PROGRESS', deliveries: [{ ...base, location: null, otp: '482913' }] })
    renderWithClient(<OrderTrackingPanel orderId={1} active />)
    expect(await screen.findByText('482913')).toBeInTheDocument()
  })
})
