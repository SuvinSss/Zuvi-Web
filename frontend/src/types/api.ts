export type ProductStatus = 'DRAFT' | 'PENDING' | 'APPROVED' | 'REJECTED' | 'INACTIVE'

export interface SessionUser {
  id: number
  username: string
  email: string
  name: string
  role: string
  permissions: { view: boolean; add: boolean; change: boolean }
}

export interface Session {
  authenticated: boolean
  user: SessionUser | null
  csrf_token?: string
}

export interface FallbackHint {
  category: string
  category_slug: string
  brand: string
}

export interface CardImage {
  source: 'uploaded' | 'fallback'
  alt_text: string
  thumbnail_url: string | null
  display_url: string | null
  width?: number | null
  height?: number | null
  fallback?: FallbackHint
}

export interface ProductListItem {
  id: number
  product_code: string
  name: string
  sku: string
  slug: string
  store: { id: number; name: string; store_code: string }
  category: { id: number; name: string }
  brand: { id: number; name: string } | null
  status: ProductStatus
  is_active: boolean
  unit: string
  unit_value: string
  store_price: string
  selling_price: string | null
  final_price: string | null
  stock_quantity: string
  image: CardImage
  updated_at: string
}

export interface ProductImageRecord {
  id: number
  alt_text: string
  sort_order: number
  is_primary: boolean
  thumbnail_url: string | null
  display_url: string | null
  original_url: string | null
  width: number | null
  height: number | null
  file_size: number | null
}

export interface ProductDetail extends ProductListItem {
  description: string
  tags: { id: number; name: string }[]
  low_stock_threshold: string
  manufacturing_date: string | null
  expiry_date: string | null
  is_featured: boolean
  rejection_reason: string
  images: ProductImageRecord[]
  created_at: string
}

export interface Page<T> {
  count: number
  next: string | null
  previous: string | null
  results: T[]
}

export interface Meta {
  stores: { id: number; name: string; store_code: string }[]
  categories: { id: number; name: string; slug: string }[]
  brands: { id: number; name: string }[]
  tags: { id: number; name: string }[]
  units: { value: string; label: string }[]
  statuses: { value: ProductStatus; label: string }[]
  max_images: number
  can: { view: boolean; add: boolean; change: boolean }
}

export interface ProductWritePayload {
  store?: number
  name: string
  sku: string
  category: number
  brand: number | null
  tags: number[]
  description: string
  unit: string
  unit_value: string
  low_stock_threshold: string
  manufacturing_date: string | null
  expiry_date: string | null
  store_price: string
  is_active: boolean
  is_featured?: boolean
  save_as_draft?: boolean
}

export type ImportMode = 'create' | 'skip' | 'update'

export interface ImportRow {
  row: number
  status: 'valid' | 'invalid' | 'skip'
  action: 'create' | 'update' | 'skip' | null
  store_code: string
  sku: string
  name: string
  duplicate: boolean
  image: 'none' | 'zip' | 'url'
  errors: { column: string; message: string }[]
}

export interface ImportError {
  row: number
  column: string
  message: string
  sku: string
}

export interface ImportSummary {
  created: number
  updated: number
  skipped: number
  failed: number
  images_processed: number
  fallback_images: number
  outcome: 'complete' | 'partial' | 'rolled_back'
}

export interface ImportBatch {
  id: string
  status: 'PREVIEWED' | 'COMMITTED' | 'FAILED'
  mode: ImportMode
  all_or_nothing: boolean
  allow_image_urls: boolean
  source_name: string
  already_imported: boolean
  counts: { total: number; valid: number; invalid: number; duplicates: number; create?: number; update?: number; skip?: number }
  summary: Partial<ImportSummary>
  errors: ImportError[]
  rows?: ImportRow[]
  ignored_columns?: string[]
}
