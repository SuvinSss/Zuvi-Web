import { api } from '@/lib/api'
import type { Page, PriceBreakdown, ProductDetail } from '@/types/api'
import type {
  ApprovalCenter, OwnerCandidate, OwnerSetup, BulkModule, BulkPreview, BulkRequest, BulkResult, CreateOutcome, ImportJob, SmartImportRow, StaffRow, StoreDetail,
  StoreDoc, StoreMeta, StoreRow, StoreWrite,
} from '@/types/management'

const clean = (params?: object) => (params ? Object.fromEntries(Object.entries(params).filter(([, v]) => v !== undefined && v !== '' && v !== null)) : undefined)
const get = async <T>(url: string, params?: object) => (await api.get<T>(url, { params: clean(params) })).data
const post = async <T>(url: string, body?: unknown) => (await api.post<T>(url, body)).data
const patch = async <T>(url: string, body?: unknown) => (await api.patch<T>(url, body)).data

export interface StoreQuery { q?: string; status?: string; category?: string; city?: string; store_type?: string; verification?: string; ordering?: string; page?: number }
export const storeMeta = () => get<StoreMeta>('/admin/stores/meta/')
export const listStores = (q: StoreQuery) => get<Page<StoreRow>>('/admin/stores/', q)
export const getStore = (id: number | string) => get<StoreDetail>(`/admin/stores/${id}/`)
export const createStore = (body: StoreWrite) => post<CreateOutcome>('/admin/stores/', body)
export const updateStore = (id: number, body: Partial<StoreWrite>) => patch<StoreDetail>(`/admin/stores/${id}/`, body)
export const storeStaff = (id: number) => get<StaffRow[]>(`/admin/stores/${id}/staff/`)
export const addStoreStaff = (id: number, body: object) => post<{ id: number; owner_setup?: OwnerSetup | null }>(`/admin/stores/${id}/staff/`, body)
export const storeDocuments = (id: number) => get<StoreDoc[]>(`/admin/stores/${id}/documents/`)
export const uploadStoreDocument = (id: number, kind: string, file: File, title = '') => {
  const form = new FormData()
  form.append('kind', kind); form.append('file', file); form.append('title', title)
  return post<{ id: number }>(`/admin/stores/${id}/documents/`, form)
}
export const uploadStoreImages = (id: number, files: { image?: File | null; banner?: File | null }) => {
  const form = new FormData()
  if (files.image) form.append('image', files.image)
  if (files.banner) form.append('banner', files.banner)
  return post<{ image: string | null; banner: string | null }>(`/admin/stores/${id}/images/`, form)
}
export const verifyStore = (id: number, verification_status: 'VERIFIED' | 'REJECTED') => post(`/admin/stores/${id}/verify/`, { verification_status })
export const storesExportUrl = (q: StoreQuery) => {
  const base = (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, '')
  const params = new URLSearchParams(Object.entries(clean({ ...q, page: undefined }) ?? {}).map(([k, v]) => [k, String(v)]))
  return `${base}/admin/stores/export/?${params}`
}

export const approvalCenter = () => get<ApprovalCenter>('/admin/approvals/')
export const bulkPreview = (module: BulkModule, body: BulkRequest) => post<BulkPreview>(`/admin/bulk/${module}/preview/`, body)
export const bulkApply = (module: BulkModule, body: BulkRequest) => post<BulkResult>(`/admin/bulk/${module}/apply/`, { ...body, confirm: true })

export const importJobs = (q: { status?: string; page?: number }) => get<Page<ImportJob>>('/products/import/', q)
export const importDetail = (id: string, status?: string) => get<ImportJob & { rows?: SmartImportRow[]; ignored_columns?: string[] }>(`/products/import/${id}/`, { status })
export const correctImportRow = (id: string, row: number, values: Record<string, string>) =>
  patch<{ row: SmartImportRow; counts: ImportJob['counts'] }>(`/products/import/${id}/rows/${row}/`, { values })
export const retryImport = (id: string) => post<ImportJob>(`/products/import/${id}/retry/`)

export interface PricingInput { selling_price?: string; margin_type?: string; margin?: string; discount_type?: string; discount_value?: string; reason?: string }
export const pricingPreview = (body: PricingInput & { product?: number; cost?: string; target_margin?: string }) =>
  post<{ breakdown?: PriceBreakdown; suggested_selling_price?: string }>('/products/pricing/preview/', body)
export const setPricing = (id: number, body: PricingInput) => post<ProductDetail>(`/products/${id}/pricing/`, body)
export const ownerCandidates = (q: string) => get<OwnerCandidate[]>('/admin/stores/owner-candidates/', { q })
export const resendInvite = (storeId: number, user: number) => post<{ owner_setup: OwnerSetup }>(`/admin/stores/${storeId}/invite/`, { user })
export const acceptInvite = async (token: string, newPassword: string) => { await api.post('/auth/invite/accept/', { token, new_password: newPassword }) }
