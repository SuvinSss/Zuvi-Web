/** Response shapes of the platform API (read from the Django serializers, not guessed). */
export interface Rating { average: number; count: number }

export interface PublicProduct {
  id: number
  product_code: string
  slug: string
  name: string
  description: string
  unit: string
  unit_value: string
  price: string
  in_stock: boolean
  category: { id: number; name: string }
  brand: string | null
  store: { id: number; name: string }
  image: string | null
  thumbnail: string | null
  rating: Rating
}
export interface PublicProductDetail extends PublicProduct {
  images: { url: string | null; thumbnail: string | null; alt: string; is_primary: boolean }[]
}
export interface PublicStore { id: number; name: string; description: string; city: string; image: string | null; rating: Rating; location?: { latitude: number; longitude: number; address: string } | null }
export interface Category { id: number; name: string }

export interface PublicReview {
  id: number
  rating: number
  title: string
  comment: string
  reviewer: string
  reply: { body: string; created_at: string } | null
  created_at: string
  edited_at: string | null
}
export type ReviewPage = import('./api').Page<PublicReview> & { rating: Rating }
export interface MyReview {
  id: number
  target_type: 'STORE' | 'PRODUCT' | 'DELIVERY_PARTNER'
  store: number | null
  product: number | null
  partner: number | null
  store_order: number
  store_order_number: string
  rating: number
  title: string
  comment: string
  status: string
  moderation_reason: string
  reply: { body: string; created_at: string } | null
  created_at: string
  edited_at: string | null
}

export interface Address {
  id: number
  label: 'HOME' | 'WORK' | 'OTHER' | string
  recipient_name: string
  phone_number: string
  line1: string
  line2: string
  landmark: string
  city: string
  district: string
  state: string
  postal_code: string
  latitude: string
  longitude: string
  delivery_instructions: string
  is_default: boolean
  custom_label?: string
  place_id?: string
  location_source?: '' | 'GPS' | 'SEARCH' | 'PIN' | 'MANUAL'
  location_accuracy_m?: number | null
  location_confirmed?: boolean
  short_label?: string
  summary?: string
}
export type AddressInput = Omit<Address, 'id' | 'is_default' | 'short_label' | 'summary' | 'location_confirmed'> & { is_default?: boolean; location_confirmed?: boolean }

export interface CartLine {
  id: number
  product_id: number
  product_code: string
  name: string
  store: { id: number; name: string }
  quantity: string
  unit_price: string | null
  line_total: string | null
  is_available: boolean
  stock_quantity: string
  warnings: string[]
}
export interface Cart { items: CartLine[]; item_count: number; subtotal: string; has_issues: boolean }

export interface CheckoutPreview {
  store_groups: { store: { id: number; name: string }; items_subtotal: string; items: CartLine[]; pickup_locations: { id: number; name: string }[] }[]
  items_subtotal: string
  delivery_charge: string
  discount_total: string
  grand_total: string
  has_blocking_issues: boolean
  blocking_messages: string[]
  addresses: Address[]
  fulfillment_types: { value: string; label: string }[]
  payment_methods: { value: string; label: string }[]
}
export interface CheckoutInput {
  fulfillment_type: string
  payment_method: string
  delivery_address_id?: number | null
  pickup_locations?: Record<string, number>
  customer_notes?: string
  quote_token?: string | null
}

export interface OrderSummary {
  id: number
  order_number: string
  status: string
  fulfillment_type: string
  payment_method: string
  payment_status: string
  grand_total: string
  item_count: string
  placed_at: string
}
export interface TimelineEntry { status: string; at: string }
export interface OrderItem { product_name: string; sku: string; unit: string; quantity: string; unit_price: string; line_total: string; product_id: number | null }
export interface OrderDetail extends OrderSummary {
  items_subtotal: string
  delivery_charge: string
  discount_total: string
  customer_notes: string
  delivered_at: string | null
  cancellation_reason: string
  can_cancel: boolean
  delivery_address: { recipient_name: string; phone_number: string; line1: string; line2: string; landmark: string; city: string; state: string; postal_code: string } | null
  timeline: TimelineEntry[]
  store_orders: { id: number; store_order_number: string; store: { id: number; name: string }; status: string; store_total: string; delivery_charge?: string; delivery?: import('./delivery').CustomerDelivery | null; items: OrderItem[]; timeline: TimelineEntry[] }[]
}

export interface TrackingDelivery {
  delivery_id: number
  status: string
  status_label: string
  attempt_number: number
  partner: { id: number; first_name: string; vehicle_type: string } | null
  location: { latitude?: number; longitude?: number; accuracy_m?: number | null; recorded_at: string | null; age_seconds: number | null; is_stale: boolean } | null
  eta: string | null
  dropoff: { latitude: number; longitude: number } | null
  pickup?: { latitude: number; longitude: number } | null
  timeline: { status: string; at: string; note: string }[]
  store_order_number: string
  store_name: string
  otp?: string
}
export interface OrderTracking { order_id: number; order_number: string; order_status: string; deliveries: TrackingDelivery[] }

export interface Notification { id: number; kind: string; title: string; body: string; data: Record<string, unknown>; is_read: boolean; read_at: string | null; created_at: string }

export interface FeedbackItem {
  id: number
  reference: string
  kind: string
  subject_type: string
  store: number | null
  store_name: string | null
  order: number | null
  message: string
  status: string
  author_name: string
  ticket?: number | null
  ticket_reference: string | null
  replies: { id: number; body: string; is_internal: boolean; created_at: string; from_support: boolean }[]
  created_at: string
  updated_at: string
}

export interface Person { id?: number; name: string; role?: string }
/** SLA state per clock: ok | due_soon | breached | met | missed | none */
export type Sla = Record<string, string>
export interface TicketRow {
  id: number
  reference: string
  subject: string
  category: string
  priority: string
  status: string
  escalated: boolean
  requester: Person | null
  assigned_to: Person | null
  order: number | null
  order_number: string | null
  sla: Sla | null
  created_at: string
  updated_at: string
}
export interface Attachment { id: number; original_name: string; content_type: string; size: number; created_at: string; is_internal: boolean; url: string }
export interface TicketDetail extends TicketRow {
  description: string
  messages: { id: number; author: Person; body: string; is_internal: boolean; created_at: string }[]
  events: { kind: string; detail: string; created_at: string }[]
  attachments: Attachment[]
  first_responded_at: string | null
  resolved_at: string | null
  closed_at: string | null
}
export interface ComplaintRow {
  id: number
  reference: string
  against_type: string
  category: string
  severity: string
  status: string
  complainant: Person | null
  assigned_to: Person | null
  order: number | null
  order_number: string | null
  store: number | null
  store_name: string | null
  partner: number | null
  product: number | null
  sla: Sla | null
  created_at: string
  updated_at: string
}
export interface ComplaintDetail extends ComplaintRow {
  description: string
  desired_resolution: string
  resolution: string
  escalation_reason?: string
  timeline: { id: number; kind: string; body: string; from_status: string; to_status: string; is_internal: boolean; created_at: string; actor: Person | null }[]
  attachments: Attachment[]
  acknowledged_at: string | null
  resolved_at: string | null
  closed_at: string | null
}
