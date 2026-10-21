export interface Place {
  label: string; latitude: string; longitude: string; line1: string; locality: string; city: string; district: string
  state: string; postal_code: string; country: string; place_id: string
}
export interface CustomerDelivery {
  distance_km: string; distance_source: 'road' | 'estimated' | 'manual'; customer_fee_before_discount: string; delivery_discount: string
  discount_reason: string; customer_fee: string; delivery_tax: string; customer_total: string; surcharges: Record<string, string>
  eta_minutes: number | null; notes: string[]; explanation: string
}
export interface CheckoutQuote {
  quote_token: string; expires_at: string; items_subtotal: string; discount_total: string; delivery_total: string; grand_total: string
  all_deliverable: boolean; has_blocking_issues: boolean; blocking_messages: string[]
  stores: { store_id: number; store_name: string; ok: boolean; error: string | null; delivery: CustomerDelivery | null }[]
}
export interface ServiceableStore { id: number; name: string; serviceable: boolean; reasons: string[]; open_now: boolean; distance_km: string | null; distance_source?: string; fee: string | null; eta_minutes: number | null }

export interface PricingBreakdown {
  distance_km: string; distance_source: string; pricing_mode: string
  cost: Record<string, string>; rider_breakdown: Record<string, string>; distance_tariff: string; recovery_target: string | null
  surcharges: Record<string, string>; raw_fee: string; capped_by_max_fee: string; customer_fee_before_discount: string
  delivery_discount: string; discount_funded_by: string | null; discount_reason: string; customer_fee: string; delivery_tax_rate: string
  delivery_tax: string; customer_total: string; partner_payout: string; platform_funded_promotion: string; store_funded_promotion: string
  estimated_cost: string; platform_subsidy: string; delivery_contribution: string; notes: string[]
}
export type PricingSettings = Record<string, string | number | boolean | null | { up_to_km: number | string; fee: number | string }[] | { days: number[]; start: string; end: string }[]>
export interface PricingVersion extends Record<string, unknown> {
  id: number; version: number; zone: number | null; zone_name: string; effective_from: string; created_at: string; created_by: string | null
  reason: string; is_illustrative: boolean; fuel_cost_per_km: string; energy_price_verified_at: string | null; energy_price_source: string
}
export interface PricingVersions {
  active: PricingVersion | null; scheduled: PricingVersion[]; history: PricingVersion[]; can_edit: boolean
  choices: { fuel_type: [string, string][]; pricing_mode: [string, string][]; rounding: [string, string][]; funder: [string, string][] }
}
export interface Zone { id: number; name: string; state: string; district: string; locality: string; polygon: [number, number][]; service_area_surcharge: string; is_active: boolean; store_count: number }
export interface Earning { id: number; kind: string; kind_label: string; amount: string; status: 'PAID' | 'UNPAID'; paid_at: string | null; created_at: string; attempt_number: number; store_order: string | null; breakdown: Record<string, unknown>; note: string; partner?: string; payout_reference?: string }
export interface Operations {
  period_days: number
  stores_with_location_problems: { id: number; name: string; store_code: string; problems: string[] }[]
  orders_with_invalid_destination: { order_number: string; placed_at: string }[]
  partners: { approved: number; online: number }
  deliveries: { active: number; waiting_for_partner: number; needs_attention: number; failed_attempts: number; failure_reasons: { failure_reason: string; n: number }[] }
  economics: Record<string, string | number>
  needs_review: { store_order: string; why: string; customer_fee: string; estimated_cost: string }[]
}
export interface StoreFinance {
  commission_percentage: string; totals: Record<string, string>; note: string; location_problems: string[]
  orders: { store_order: string; status: string; created_at: string; items: string; commission: string; store_funded_promotion: string; settlement: string; delivery_fee_paid_by_customer: string }[]
}
