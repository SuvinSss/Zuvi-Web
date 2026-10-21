/** Shapes for the store, delivery and admin APIs (read from the Django views, not guessed). */
export interface StoreMe {
  store: { id: number; name: string; code: string; status: string }
  membership: { can_manage_orders: boolean; can_manage_inventory: boolean; is_primary: boolean }
  orders_by_status: Record<string, number>
  low_stock_products: number
  rating: { average?: number; count?: number } | null
}
export interface StoreOrderRow {
  id: number; store_order_number: string; order_number: string; status: string; fulfillment_type: string; payment_method: string
  store_total: string; created_at: string; actions: string[]; recipient_first_name: string
}
export interface StoreOrderDetail extends StoreOrderRow {
  customer_notes: string
  items: { id: number; product_id: number | null; product_name: string; sku: string; unit: string; quantity: string; unit_price: string; line_total: string }[]
  timeline: { status: string; at: string; reason: string }[]
  delivery: { id: number; status: string; partner_name: string | null } | null
}
export interface StoreProductRow {
  id: number; product_code: string; sku: string; name: string; category: string; status: string; is_active: boolean; unit: string
  stock_quantity: string; low_stock_threshold: string; store_price: string; final_price: string | null; expiry_date: string | null
}

export interface DeliveryRecord {
  id: number; status: string; attempt_number: number; order_number: string; store_order_number: string; store_name: string
  partner: { id: number; name: string; phone: string; vehicle_type: string } | null
  customer: { name: string; phone: string; instructions: string } | null
  pickup: { latitude: number | null; longitude: number | null; name: string }
  dropoff: { latitude: number | null; longitude: number | null; city: string; postal_code: string; line1?: string; line2?: string; landmark?: string }
  needs_attention: boolean; rejection_count: number; offer_expires_at: string | null
  assigned_at: string | null; picked_up_at: string | null; delivered_at: string | null; created_at: string
}
export interface PartnerRecord {
  id: number; username: string; full_name: string; status: string; is_approved: boolean; vehicle_type: string; vehicle_number: string
  is_online: boolean; last_latitude: string | null; last_longitude: string | null; last_location_at: string | null; status_reason: string; created_at: string
}
export interface Attempt { number: number; outcome: string; failure_reason: string; failure_note: string; started_at: string; ended_at: string | null }

export interface AdminUser { id: number; username: string; email: string; first_name: string; last_name: string; phone_number: string; role: string; is_active: boolean; last_login: string | null; date_joined: string }
export interface AdminStore { id: number; name: string; store_code?: string; code?: string; status: string; city?: string; category?: string; rating?: unknown; [k: string]: unknown }
export interface AdminOrderRow {
  id: number; order_number: string; status: string; fulfillment_type: string; payment_method: string; payment_status: string
  grand_total: string; item_count: string; placed_at: string; customer: string
}
export interface AdminReview {
  id: number; target_type: string; store: number | null; product: number | null; store_order_number: string; rating: number; title: string; comment: string
  status: string; moderation_reason: string; reviewer: string; report_count: number; created_at: string
}
export interface AuditEvent { id: number; actor: string | null; action: string; object_type: string; object_id: string; summary: string; metadata: Record<string, unknown>; created_at: string }
export interface AdminOverview {
  window_days: number
  orders: { by_status: Record<string, number>; total: number; delivered_value: string }
  deliveries: { by_status: Record<string, number>; needs_attention: number; partners_online: number; partners_pending: number }
  support: { open_tickets: number; open_complaints: number }
  stores: { active: number; pending: number; average_rating: number }
}

/* ---------- admin dashboard ---------- */
export interface Kpi { value: number | string; previous: number | string; change_percent: number | null }
export interface SeriesPoint { date: string; orders: number; delivered: number; revenue: string; cancelled: number; new_customers: number; failed_deliveries: number }
export interface DashboardData {
  range: { from: string; to: string; days: number; previous: { from: string; to: string } }
  kpis: { orders: Kpi; delivered: Kpi; revenue: Kpi; cancelled: Kpi; new_customers: Kpi }
  live: {
    orders_awaiting_confirmation: number; orders_being_prepared: number; orders_awaiting_delivery: number; orders_in_transit: number
    deliveries_active: number; deliveries_waiting_for_partner: number; deliveries_needing_attention: number
    customers_total: number; stores_active: number; partners_active: number; partners_online: number
    products_total: number; products_active: number; tickets_open: number; complaints_open: number
  }
  series: SeriesPoint[]
  status_distribution: { status: string; count: number }[]
  top_stores: { store_id: number; name: string; orders: number; revenue: string }[]
  best_products: { product_id: number | null; name: string; quantity: string; revenue: string }[]
  delivery_performance: { total: number; delivered: number; failed: number; cancelled: number; retried: number; success_rate_percent: number | null; average_minutes_assignment_to_delivery: number | null }
  queues: {
    recent_orders: (AdminOrderRow & { customer: string })[]
    needs_attention: { orders_unconfirmed_15_min: { id: number; order_number: string; placed_at: string }[]; deliveries: { id: number; status: string; store_order__store_order_number: string }[] }
    new_customers: { id: number; customer_code: string; created_at: string; username: string }[]
    pending_stores: { id: number; name: string; created_at: string }[]
    pending_partners: { id: number; created_at: string; username: string }[]
    pending_complaints: { id: number; reference: string; category: string; severity: string; created_at: string }[]
    recent_reviews: { id: number; rating: number; target_type: string; comment: string; status: string; created_at: string }[]
    recent_feedback: { id: number; reference: string; kind: string; message: string; status: string; created_at: string }[]
  }
  notes: { revenue: string }
}
export interface AdminCounts {
  orders_awaiting_confirmation: number; deliveries_needing_attention: number; partners_pending: number; stores_pending: number
  products_pending: number; tickets_open: number; complaints_open: number
}
export interface SearchHit { type: string; label: string; detail: string; path: string }
export interface AdminCustomerRow {
  id: number; customer_code: string; username: string; name: string; email: string; phone_number: string; is_active: boolean
  user_id: number; created_at: string; order_count: number; delivered_value: string; last_order_at: string | null
}
export interface AdminCustomerDetail extends AdminCustomerRow {
  orders_by_status: Record<string, number>; recent_orders: AdminOrderRow[]; tickets: number; complaints: number; reviews: number; registration_source: string
}
export interface AdminCategoryRow { id: number; name: string; slug: string; is_active: boolean; product_count: number; parent_name: string | null }
