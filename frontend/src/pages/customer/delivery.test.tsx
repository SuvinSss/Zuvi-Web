import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { routes } from '@/app/router'
import { ToastProvider } from '@/components/kit'
import { AddressPicker } from '@/components/location/AddressPicker'
import { adminSession, renderRoutes } from '@/test/utils'

// Leaflet needs a real layout engine; the stand-in exposes the same callbacks.
vi.mock('@/components/location/MapView', () => ({
  KERALA_CENTER: [10, 76],
  MapView: ({ value, onPinChange, onMapClick, label }: { value?: { lat: number; lon: number } | null; onPinChange?: (a: number, b: number) => void; onMapClick?: (a: number, b: number) => void; label?: string }) => (
    <div>
      <span data-testid="pin">{value ? `${value.lat.toFixed(4)},${value.lon.toFixed(4)}` : 'no pin'}</span>
      <button type="button" onClick={() => (onMapClick ?? onPinChange)?.(8.8932, 76.6141)}>{`map: ${label}`}</button>
    </div>
  ),
}))
vi.mock('@/services/auth', () => ({ fetchSession: vi.fn(), login: vi.fn(), logout: vi.fn() }))
vi.mock('@/services/ops', () => ({ adminCounts: vi.fn(), adminSearch: vi.fn() }))
vi.mock('@/services/delivery', () => ({
  searchPlaces: vi.fn(), reversePlace: vi.fn(), serviceableStores: vi.fn(), checkoutQuote: vi.fn(), pricingVersions: vi.fn(),
  createPricingVersion: vi.fn(), simulate: vi.fn(), myEarnings: vi.fn(), storeFinance: vi.fn(), zones: vi.fn(), deliveryOperations: vi.fn(), adminEarnings: vi.fn(),
}))
vi.mock('@/services/platform', async (orig) => ({
  ...(await orig<object>()), unreadCount: vi.fn().mockResolvedValue(0), getCart: vi.fn(), listAddresses: vi.fn(), getCheckoutPreview: vi.fn(), placeOrder: vi.fn(),
  createAddress: vi.fn(), listPublicStores: vi.fn(),
}))

import * as auth from '@/services/auth'
import * as delivery from '@/services/delivery'
import * as platform from '@/services/platform'
import * as ops from '@/services/ops'

const customerSession = { authenticated: true, csrf_token: 't', user: { id: 7, username: 'cust', email: 'c@x.test', name: 'Cust', first_name: 'Anu', role: 'CUSTOMER' as const, is_management: false, permissions: { view: false, add: false, change: false } } }
const addr = (over = {}) => ({ id: 3, label: 'HOME', short_label: 'Home', summary: 'Market Road, Paravur, Kerala', recipient_name: 'Anu', phone_number: '9000000001', line1: 'Rose Villa', line2: 'Market Road', landmark: '', city: 'Paravur', district: 'Kollam', state: 'Kerala', postal_code: '', latitude: '8.893200', longitude: '76.614100', delivery_instructions: '', is_default: true, location_confirmed: true, ...over })
const place = { label: 'Paravur, Kollam, Kerala', latitude: '8.893200', longitude: '76.614100', line1: 'Beach Road', locality: 'Paravur', city: 'Paravur', district: 'Kollam', state: 'Kerala', postal_code: '691301', country: 'India', place_id: 'n1' }
const wrap = (ui: React.ReactElement) => render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><ToastProvider><MemoryRouter>{ui}</MemoryRouter></ToastProvider></QueryClientProvider>)

function geolocation(impl: (ok: PositionCallback, fail: PositionErrorCallback) => void) {
  Object.defineProperty(navigator, 'geolocation', { configurable: true, value: { getCurrentPosition: vi.fn(impl) } })
}

beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(platform.unreadCount).mockResolvedValue(0)
  vi.mocked(delivery.reversePlace).mockResolvedValue({ result: place, available: true })
  vi.mocked(delivery.searchPlaces).mockResolvedValue({ results: [place], available: true })
  vi.mocked(ops.adminCounts).mockResolvedValue({ orders_awaiting_confirmation: 0, deliveries_needing_attention: 0, partners_pending: 0, stores_pending: 0, products_pending: 0, tickets_open: 0, complaints_open: 0, stores_needs_info: 0 })
})

describe('address picker', () => {
  it('asks for location only on tap; denial falls back to search and map without blocking', async () => {
    const getPos = vi.fn((_ok: PositionCallback, fail: PositionErrorCallback) => fail({ code: 1, PERMISSION_DENIED: 1, message: 'denied' } as GeolocationPositionError))
    geolocation(getPos)
    wrap(<AddressPicker onSave={vi.fn()} />)
    expect(getPos).not.toHaveBeenCalled()
    expect(screen.getByText(/not tracked/i)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /use my current location/i }))
    expect(await screen.findByText(/permission is blocked/i)).toBeInTheDocument()
    expect(screen.getByText(/search for your address or tap the map/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/search for your area/i)).toBeInTheDocument()  // manual route still there
  })

  it('warns about poor GPS accuracy and lets the pin be adjusted', async () => {
    geolocation((ok) => ok({ coords: { latitude: 8.9, longitude: 76.6, accuracy: 850 } } as GeolocationPosition))
    wrap(<AddressPicker onSave={vi.fn()} />)
    await userEvent.click(screen.getByRole('button', { name: /use my current location/i }))
    expect(await screen.findByText(/only accurate to about 850 m/i)).toBeInTheDocument()
    await waitFor(() => expect(screen.getByLabelText(/town \/ city/i)).toHaveValue('Paravur'))  // reverse geocoded
  })

  it('search → pick → fill details → must confirm the pin before saving; PIN code optional', async () => {
    const onSave = vi.fn()
    wrap(<AddressPicker onSave={onSave} />)
    await userEvent.type(screen.getByLabelText(/search for your area/i), 'Paravur')
    await userEvent.click(await screen.findByRole('button', { name: /Paravur, Kollam, Kerala/ }))
    await userEvent.type(screen.getByLabelText(/house \/ flat/i), 'Rose Villa')
    await userEvent.type(screen.getByLabelText(/receiver/i), 'Anu')
    await userEvent.type(screen.getByLabelText(/^phone/i), '9000000001')
    await userEvent.clear(screen.getByLabelText(/pin code/i))
    const save = screen.getByRole('button', { name: 'Save address' })
    expect(save).toBeDisabled()
    expect(screen.getByText(/confirm the pin/i)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('checkbox', { name: /pin is at the right place/i }))
    await userEvent.click(save)
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ line1: 'Rose Villa', city: 'Paravur', location_source: 'SEARCH', location_confirmed: true, postal_code: '', latitude: '8.893200' }))
  })

  it('search being unavailable is explained, map pin still works', async () => {
    vi.mocked(delivery.searchPlaces).mockResolvedValue({ results: [], available: false, detail: 'Address search is unavailable right now.' })
    wrap(<AddressPicker onSave={vi.fn()} />)
    await userEvent.type(screen.getByLabelText(/search for your area/i), 'Kollam')
    expect(await screen.findByText(/search is unavailable/i)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /map: tap to place/i }))
    expect(screen.getByLabelText(/house \/ flat/i)).toBeInTheDocument()
  })
})

describe('header and stores', () => {
  it('shows "Delivering to" with the default address and marks stores that deliver', async () => {
    vi.mocked(auth.fetchSession).mockResolvedValue(customerSession as never)
    vi.mocked(platform.getCart).mockResolvedValue({ items: [], item_count: 0, subtotal: '0', has_issues: false })
    vi.mocked(platform.listAddresses).mockResolvedValue([addr()] as never)
    vi.mocked(platform.listPublicStores).mockResolvedValue({ count: 2, next: null, previous: null, results: [
      { id: 1, name: 'Far Mart', city: 'Kollam', description: '', image: null, rating: { average: 0, count: 0 } },
      { id: 2, name: 'Near Mart', city: 'Paravur', description: '', image: null, rating: { average: 0, count: 0 } },
    ] } as never)
    vi.mocked(delivery.serviceableStores).mockResolvedValue({ serviceable_count: 1, stores: [
      { id: 2, name: 'Near Mart', serviceable: true, reasons: [], open_now: true, distance_km: '2.40', distance_source: 'estimated', fee: '25.00', eta_minutes: 22 },
      { id: 1, name: 'Far Mart', serviceable: false, reasons: ['Address is 30.1 km away; this store delivers within 8 km.'], open_now: true, distance_km: null, fee: null, eta_minutes: null },
    ] })
    renderRoutes(routes, ['/stores'])
    expect((await screen.findAllByText(/Home · Market Road, Paravur/)).length).toBeGreaterThan(0)
    expect(await screen.findByText(/Delivers to you · 2.4 km \(approx.\) · ₹25 delivery · ~22 min/)).toBeInTheDocument()
    expect(screen.getByText(/delivers within 8 km/)).toBeInTheDocument()
    expect(delivery.serviceableStores).toHaveBeenCalledWith('8.893200', '76.614100')
  })
})

describe('checkout', () => {
  const preview = { store_groups: [{ store: { id: 2, name: 'Near Mart' }, items_subtotal: '200.00', pickup_locations: [], items: [{ id: 1, product_id: 5, product_code: 'P5', name: 'Rice', store: { id: 2, name: 'Near Mart' }, quantity: '2', unit_price: '100', line_total: '200.00', is_available: true, stock_quantity: '9', warnings: [] }] }],
    items_subtotal: '200.00', delivery_charge: '0.00', discount_total: '0.00', grand_total: '200.00', has_blocking_issues: false, blocking_messages: [], addresses: [addr()],
    fulfillment_types: [{ value: 'DELIVERY', label: 'Delivery' }], payment_methods: [{ value: 'COD', label: 'Cash on delivery' }] }
  const quote = (over = {}) => ({ quote_token: 'q-1', expires_at: '', items_subtotal: '200.00', discount_total: '0.00', delivery_total: '37.00', grand_total: '237.00', all_deliverable: true, has_blocking_issues: false, blocking_messages: [],
    stores: [{ store_id: 2, store_name: 'Near Mart', ok: true, error: null, delivery: { distance_km: '3.20', distance_source: 'road' as const, customer_fee_before_discount: '37.00', delivery_discount: '0.00', discount_reason: '', customer_fee: '37.00', delivery_tax: '0.00', customer_total: '37.00', surcharges: { peak: '0.00' }, eta_minutes: 25, notes: [], explanation: 'Delivery fee based on distance' } }], ...over })

  beforeEach(() => {
    vi.mocked(auth.fetchSession).mockResolvedValue(customerSession as never)
    vi.mocked(platform.getCart).mockResolvedValue({ items: [], item_count: 1, subtotal: '200', has_issues: false })
    vi.mocked(platform.listAddresses).mockResolvedValue([addr()] as never)
    vi.mocked(platform.getCheckoutPreview).mockResolvedValue(preview as never)
  })

  it('shows the server-calculated distance fee and sends the quote token', async () => {
    vi.mocked(delivery.checkoutQuote).mockResolvedValue(quote())
    vi.mocked(platform.placeOrder).mockResolvedValue({ id: 99 } as never)
    renderRoutes(routes, ['/checkout'])
    const summary = (await screen.findByRole('heading', { name: 'Order summary' })).closest('div') as HTMLElement
    expect(await within(summary).findByText('₹37.00')).toBeInTheDocument()
    expect(within(summary).getByRole('button', { name: /Delivery fee based on distance · 3.2 km/ })).toBeInTheDocument()
    expect(screen.queryByText(/rider|subsidy|estimated cost/i)).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: /place order · ₹237.00/i }))
    await waitFor(() => expect(platform.placeOrder).toHaveBeenCalledWith(expect.objectContaining({ quote_token: 'q-1', delivery_address_id: 3 }), expect.any(String)))
    const body = vi.mocked(platform.placeOrder).mock.calls[0]![0] as unknown as Record<string, unknown>
    expect(body).not.toHaveProperty('delivery_charge')
    expect(body).not.toHaveProperty('grand_total')
  })

  it('explains a changed total and asks to confirm again', async () => {
    vi.mocked(delivery.checkoutQuote).mockResolvedValueOnce(quote()).mockResolvedValue(quote({ quote_token: 'q-2', delivery_total: '45.00', grand_total: '245.00' }))
    vi.mocked(platform.placeOrder).mockRejectedValue(Object.assign(new Error('409'), { isAxiosError: true, response: { status: 409, data: { quote_token: ['The total changed from ₹237.00 to ₹245.00.'], price_changed: true } } }))
    renderRoutes(routes, ['/checkout'])
    await userEvent.click(await screen.findByRole('button', { name: /place order · ₹237.00/i }))
    expect(await screen.findByText(/The total changed from ₹237.00 to ₹245.00/)).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: /place order · ₹245.00/i })).toBeEnabled()
  })

  it('blocks ordering when no store can deliver to the address', async () => {
    vi.mocked(delivery.checkoutQuote).mockResolvedValue(quote({ all_deliverable: false, has_blocking_issues: true, blocking_messages: ['Near Mart: Address is outside this store\'s delivery zone.'],
      stores: [{ store_id: 2, store_name: 'Near Mart', ok: false, error: 'Address is outside this store\'s delivery zone.', delivery: null }] }))
    renderRoutes(routes, ['/checkout'])
    expect(await screen.findByText(/Can't deliver this order/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /place order/i })).toBeDisabled()
  })
})

describe('admin delivery pricing', () => {
  const version = { id: 1, version: 1, zone: null, zone_name: 'Default', effective_from: '2026-10-21T00:00:00Z', created_at: '', created_by: null, reason: 'Initial', is_illustrative: true,
    fuel_cost_per_km: '2.88', energy_price_verified_at: null, energy_price_source: 'Illustrative', fuel_type: 'PETROL', energy_price: '115.00', efficiency_km_per_unit: '40.00', maintenance_per_km: '1.50',
    rider_pay_per_order: '25.00', rider_pay_per_km: '0.00', rider_fixed_daily_pay: '0.00', rider_expected_orders_per_day: '20.00', rider_pay_per_failed_attempt: '15.00', operational_multiplier: '1.6000',
    overhead_per_order: '8.00', overhead_per_km: '0.00', failure_cost_rate: '0.1000', special_handling_cost: '0.00', road_fallback_factor: '1.3500', allow_estimated_distance: true, max_service_km: '15.00',
    pricing_mode: 'BASE_PLUS_DISTANCE', base_fee: '25.00', included_km: '2.00', per_km_rate: '6.00', distance_bands: [{ up_to_km: 2, fee: 25 }], customer_recovery_ratio: '0.6500', max_platform_subsidy_per_order: '30.00',
    min_fee: '20.00', max_fee: '79.00', allow_above_max_fee: false, rounding: 'NEAREST_RUPEE', free_delivery_threshold: null, free_delivery_funded_by: 'PLATFORM', delivery_discount_amount: '0.00',
    delivery_discount_min_order: '0.00', delivery_discount_funded_by: 'PLATFORM', peak_surcharge: '0.00', peak_windows: [], heavy_surcharge: '0.00', delivery_tax_rate: '0.0000', tax_treatment_confirmed: false, notes: '' }
  const choices = { fuel_type: [['PETROL', 'Petrol']], pricing_mode: [['BASE_PLUS_DISTANCE', 'Base + km'], ['BANDS', 'Bands']], rounding: [['NEAREST_RUPEE', 'Nearest rupee']], funder: [['PLATFORM', 'Zuuvi'], ['STORE', 'Store']] }

  beforeEach(() => {
    vi.mocked(auth.fetchSession).mockResolvedValue(adminSession as never)
    vi.mocked(delivery.pricingVersions).mockResolvedValue({ active: version, scheduled: [], history: [version], can_edit: true, choices } as never)
  })

  it('labels example numbers, needs a reason, and converts percentages', async () => {
    vi.mocked(delivery.createPricingVersion).mockResolvedValue({ ...version, id: 2, version: 2 } as never)
    renderRoutes(routes, ['/admin/delivery-pricing'])
    expect(await screen.findByText(/planning assumptions, not verified business costs/i)).toBeInTheDocument()
    expect(screen.getByText(/not fetched live/i)).toBeInTheDocument()
    const fuel = screen.getByLabelText(/price per litre/i)
    await userEvent.clear(fuel); await userEvent.type(fuel, '113.74')
    const failure = screen.getByLabelText(/failed-delivery allowance/i)
    expect(failure).toHaveValue('10')
    const save = screen.getByRole('button', { name: 'Save new version' })
    expect(save).toBeDisabled()
    await userEvent.type(screen.getByLabelText(/reason for the change/i), 'Verified Paravur pump price')
    await userEvent.click(save)
    await waitFor(() => expect(delivery.createPricingVersion).toHaveBeenCalled())
    const body = vi.mocked(delivery.createPricingVersion).mock.calls[0]![0]
    expect(body.settings.energy_price).toBe('113.74')
    expect(body.settings.failure_cost_rate).toBe('0.1')
    expect(body.settings.distance_bands).toEqual([{ up_to_km: 2, fee: 25 }])
    expect(body.reason).toBe('Verified Paravur pump price')
  })

  it('simulator uses the server and shows cost, fee, rider pay and subsidy separately', async () => {
    vi.mocked(delivery.simulate).mockResolvedValue({ based_on: 'Default v1', overridden: ['energy_price'], batch: null, result: {
      distance_km: '5.00', distance_source: 'manual', pricing_mode: 'BANDS', cost: { operational_km: '10.0000', fuel_cost_per_km: '2.8750', fuel_cost: '28.75', maintenance_cost: '15.00', rider_compensation: '25.00', overhead: '8.00', failure_allowance: '7.68' },
      rider_breakdown: {}, distance_tariff: '55.00', recovery_target: null, surcharges: {}, raw_fee: '55.00', capped_by_max_fee: '0.00', customer_fee_before_discount: '55.00', delivery_discount: '0.00', discount_funded_by: null,
      discount_reason: '', customer_fee: '55.00', delivery_tax_rate: '0', delivery_tax: '0.00', customer_total: '55.00', partner_payout: '25.00', platform_funded_promotion: '0.00', store_funded_promotion: '0.00',
      estimated_cost: '84.43', platform_subsidy: '29.43', delivery_contribution: '0.00', notes: ['Simulated inputs; estimated results.'] } })
    renderRoutes(routes, ['/admin/delivery-pricing'])
    await userEvent.click(await screen.findByRole('tab', { name: 'Simulator' }))
    await userEvent.click(screen.getByRole('button', { name: 'Calculate' }))
    expect(await screen.findByText('₹84.43')).toBeInTheDocument()
    expect(screen.getByText('₹29.43')).toBeInTheDocument()
    expect(screen.getByText(/Zuuvi subsidy/)).toBeInTheDocument()
    expect(delivery.simulate).toHaveBeenCalledWith(expect.objectContaining({ distance_km: '5', overrides: expect.objectContaining({ energy_price: '115.00', failure_cost_rate: '0.1' }) }))
  })
})
