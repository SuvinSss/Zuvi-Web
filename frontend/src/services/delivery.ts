import { api } from '@/lib/api'
import type { CheckoutQuote, Earning, Operations, Place, PricingBreakdown, PricingSettings, PricingVersion, PricingVersions, ServiceableStore, StoreFinance, Zone } from '@/types/delivery'

const get = async <T>(url: string, params?: object) => (await api.get<T>(url, { params })).data
const post = async <T>(url: string, body?: unknown) => (await api.post<T>(url, body)).data

export interface GeoConfig { geocoder: string; router: string; search_available: boolean; road_distance: boolean; map: 'google' | 'osm'; attribution: string; suggestions_need_details: boolean }
export const geoConfig = () => get<GeoConfig>('/geo/config/')
export const searchPlaces = (q: string, session?: string, near?: { lat: string; lon: string } | null) =>
  get<{ results: Place[]; available: boolean; detail?: string; attribution?: string }>('/geo/search/', { q, ...(session ? { session } : {}), ...(near ? { lat: near.lat, lon: near.lon } : {}) })
export const placeDetails = (id: string, session?: string) => get<{ result: Place | null; available: boolean; detail?: string }>('/geo/place/', { id, ...(session ? { session } : {}) })
export const reversePlace = (lat: string, lon: string) => get<{ result: Place | null; available: boolean; detail?: string }>('/geo/reverse/', { lat, lon })
export const serviceableStores = (lat: string, lon: string) => get<{ stores: ServiceableStore[]; serviceable_count: number }>('/delivery/stores/', { lat, lon })
export const checkoutQuote = (body: { fulfillment_type: string; delivery_address_id: number | null }) => post<CheckoutQuote>('/checkout/quote/', body)

export const pricingVersions = (zone?: number | null) => get<PricingVersions>('/admin/delivery-pricing/', zone ? { zone } : undefined)
export const createPricingVersion = (body: { settings: PricingSettings; reason: string; effective_from?: string | null; zone?: number | null }) => post<PricingVersion>('/admin/delivery-pricing/', body)
export interface SimulateInput { distance_km?: string; store?: number; lat?: string; lon?: string; items_subtotal?: string; is_peak?: boolean; heavy?: boolean; zone?: number | null; overrides?: PricingSettings; batch?: { route_km: string; stops: { key: string; distance_km: string }[] } }
export const simulate = (body: SimulateInput) => post<{ result: PricingBreakdown; batch: { route_km: string; shared_route_cost: string; allocations: { key: string; share: string; estimated_cost: string }[]; batched_total: string; isolated_total: string } | null; based_on: string; overridden: string[] }>('/admin/delivery-pricing/simulate/', body)
export const zones = () => get<Zone[]>('/admin/delivery-zones/')
export const createZone = (body: Partial<Zone>) => post<Zone>('/admin/delivery-zones/', body)
export const updateZone = async (id: number, body: Partial<Zone>) => (await api.patch<Zone>(`/admin/delivery-zones/${id}/`, body)).data
export const deliveryOperations = (days = 30) => get<Operations>('/admin/delivery-operations/', { days })
export const adminEarnings = (status?: string) => get<Earning[]>('/admin/partner-earnings/', status ? { status } : undefined)
export const markEarningsPaid = (ids: number[], payout_reference: string) => post<{ updated: number }>('/admin/partner-earnings/', { ids, payout_reference })

export interface MapsCheck { ok: boolean; error_code: string; message: string; latency_ms: number | null; checked_at: string }
export type MapsService = 'PLACES' | 'GEOCODING' | 'ROUTES'
export interface MapsStatus {
  configuration: { server_key_present: boolean; geocoder: string; router: string; travel_mode: string; timeout_seconds: number; store_pin_confirmation_required: boolean }
  checks: Record<MapsService, { latest: MapsCheck | null; last_success_at: string | null }>
}
export const mapsStatus = () => get<MapsStatus>('/admin/maps/status/')
export const runMapsHealthCheck = () => post<Record<MapsService, MapsCheck>>('/admin/maps/health-check/')
export const confirmStorePin = async (storeId: number) => (await api.patch(`/admin/stores/${storeId}/`, { address: { confirm_location: true } })).data

export const myEarnings = () => get<{ summary: Record<string, string>; results: Earning[] }>('/delivery/earnings/')
export const storeFinance = () => get<StoreFinance>('/store/finance/')
