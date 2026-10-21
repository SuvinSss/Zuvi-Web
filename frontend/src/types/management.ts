/** Shapes for store management, imports and the approval/bulk APIs (read from the Django views). */
export interface StoreRow {
  id: number; store_code: string; name: string; slug: string | null; status: string; is_active: boolean; store_type: string
  city: string; state: string; category: string | null; category_id: number | null; verification_status: string
  ordering_enabled: boolean; missing_requirements: string[]; contact_phone: string; created_at: string; image: string | null
  rating: { average: number; count: number }
}
export interface Slot { open: string; close: string }
export type Hours = Record<string, Slot[]>
export interface StoreAddress {
  line1: string; line2: string; landmark: string; city: string; district: string; state: string; postal_code: string; country: string
  latitude: string; longitude: string
}
export interface StoreDetail extends StoreRow {
  description: string; business_name: string; gstin: string; email: string; alternative_phone: string; banner: string | null
  commission_percentage: string; accepts_orders: boolean; offers_delivery: boolean; offers_pickup: boolean
  min_order_amount: string | null; service_radius_km: string | null; opening_hours: Hours; closures: { date: string; reason: string }[]
  creation_source: string; approved_by: string | null; approved_at: string | null; verified_by: string | null; verified_at: string | null
  created_by: string | null; address: StoreAddress; operational_gaps: string[]; next_statuses: string[]
  counts: { products: number; products_by_status: Record<string, number>; orders: number; staff: number; documents: number }
  history: { old: string; new: string; reason: string; by: string; at: string }[]
}
export interface StoreMeta {
  categories: { id: number; name: string }[]; types: { value: string; label: string }[]; statuses: { value: string; label: string }[]
  days: string[]; can_add: boolean; can_change: boolean; can_approve: boolean
}
export interface StaffRow { id: number; username: string; name: string; email: string; is_primary: boolean; is_active: boolean; designation: string; can_manage_inventory: boolean; can_manage_orders: boolean }
export interface StoreDoc { id: number; kind: string; title: string; url: string; uploaded_at: string; uploaded_by: string | null }
export interface StoreWrite {
  name: string; store_type: string; category: number | ''; contact_phone: string; alternative_phone: string; email: string; description: string
  business_name: string; gstin: string; commission_percentage: string; accepts_orders: boolean; offers_delivery: boolean; offers_pickup: boolean
  min_order_amount: string; service_radius_km: string; opening_hours: Hours; closures: { date: string; reason: string }[]
  address: StoreAddress
  owner?: { username: string; email: string; first_name: string; last_name: string; phone_number: string; password: string; designation: string }
  save_draft?: boolean
}
export interface CreateOutcome { id: number; store_code: string; status: string; missing: string[]; operational_gaps: string[] }

export interface ApprovalQueue { key: string; title: string; count: number; link: string; note: string | null; items: { id: number; label: string; [k: string]: unknown }[] }
export interface ApprovalCenter { queues: ApprovalQueue[]; total: number; not_available: string[] }

export type BulkModule = 'products' | 'stores' | 'partners' | 'reviews'
export interface BulkRequest { action: string; ids?: number[]; select_all?: boolean; filters?: Record<string, string>; reason?: string; confirm?: boolean; expected_count?: number }
export interface BulkEntry { id: number; label: string; reasons?: string[]; warnings?: string[] }
export interface BulkPreview { module: string; action: string; total: number; needs_reason: boolean; eligible_count: number; blocked_count: number; eligible: BulkEntry[]; blocked: BulkEntry[]; warning_count: number }
export interface BulkResult { module: string; action: string; successful: BulkEntry[]; skipped: BulkEntry[]; failed: BulkEntry[]; counts: { successful: number; skipped: number; failed: number } }

export interface ImportColumn { key: string; required: boolean; description: string; example: string; aliases: string[] }
export interface MappingProposal { source: string; key: string | null; how: string | null }
export interface NeedsMapping { needs_mapping: true; detail: string; headers: string[]; proposal: MappingProposal[]; missing_required: string[]; columns: ImportColumn[] }
export interface SmartImportRow {
  row: number; status: 'valid' | 'incomplete' | 'invalid' | 'skip'; action: string | null; store_code: string; sku: string; name: string
  duplicate: boolean; image: string; values: Record<string, string>; generated: string[]; normalized: Record<string, [string, string]>
  errors: { column: string; message: string }[]
}
export interface ImportJob {
  id: string; status: 'PREVIEWED' | 'COMMITTED' | 'FAILED'; source_name: string; created_by: string | null; created_at: string; committed_at: string | null
  attempts: number; retryable: boolean; counts: { total: number; valid: number; invalid: number; duplicates: number; incomplete?: number }
  summary: { created?: number; updated?: number; skipped?: number; failed?: number; outcome?: string }
}
