import { api } from '@/lib/api'
import type { Page } from '@/types/api'
import type { EvidenceRecord } from '@/components/evidence'
import type { PublicReview } from '@/types/platform'
import type {
  AdminOrderRow, AdminOverview, AdminReview, AdminStore, AdminUser, Attempt, AuditEvent, DeliveryRecord, PartnerRecord,
  StoreMe, StoreOrderDetail, StoreOrderRow, StoreProductRow,
} from '@/types/ops'

const clean = (params?: object) => (params ? Object.fromEntries(Object.entries(params).filter(([, v]) => v !== undefined && v !== '' && v !== null)) : undefined)
const get = async <T>(url: string, params?: object) => (await api.get<T>(url, { params: clean(params) })).data
const post = async <T>(url: string, body?: unknown) => (await api.post<T>(url, body)).data

/* ---------- store ---------- */
export const storeMe = () => get<StoreMe>('/store/me/')
export const listStoreOrders = (q: { status?: string; q?: string; page?: number }) => get<Page<StoreOrderRow>>('/store/orders/', q)
export const getStoreOrder = (id: number) => get<StoreOrderDetail>(`/store/orders/${id}/`)
export const storeOrderAction = (id: number, action: string, reason = '') => post<StoreOrderDetail>(`/store/orders/${id}/action/`, { action, reason })
export const listStoreProducts = (q: { q?: string; status?: string; low_stock?: string; page?: number }) => get<Page<StoreProductRow>>('/store/products/', q)
export const stockMovement = (id: number, body: { movement: string; quantity: string; reason: string; notes?: string }) => post<{ id: number; stock_quantity: string }>(`/store/products/${id}/stock/`, body)
export const listStoreDeliveries = (q: { status?: string; page?: number }) => get<Page<DeliveryRecord>>('/store/deliveries/', q)
export const confirmPickup = (deliveryId: number) => post<EvidenceRecord>(`/store/deliveries/${deliveryId}/confirm-pickup/`)
export const listStoreReviews = (page = 1) => get<Page<PublicReview>>('/store/reviews/', { page })
export const replyToReview = (id: number, body: string) => post<{ body: string }>(`/store/reviews/${id}/reply/`, { body })

/* ---------- delivery partner ---------- */
export const partnerMe = () => get<PartnerRecord>('/delivery/me/')
export const updatePartner = async (body: { vehicle_type?: string; vehicle_number?: string }) => (await api.patch<PartnerRecord>('/delivery/me/', body)).data
export const setOnline = (is_online: boolean, coords?: { latitude: string; longitude: string }) => post<PartnerRecord>('/delivery/me/online/', { is_online, ...coords })
export const listAssignments = (scope: 'active' | 'history', page = 1) => get<Page<DeliveryRecord>>('/delivery/assignments/', { scope, page })
export const getDelivery = (id: number) => get<DeliveryRecord>(`/deliveries/${id}/`)
export const deliveryAction = (id: number, action: 'accept' | 'reject' | 'arrive-store' | 'arrive', body?: unknown) => post<DeliveryRecord>(`/deliveries/${id}/${action}/`, body)
export interface EvidenceInput { latitude: string; longitude: string; accuracy_m?: number | null; notes?: string; recipient_name?: string; otp?: string; photos: File[] }
function evidenceForm(i: EvidenceInput) {
  const f = new FormData()
  f.append('latitude', i.latitude); f.append('longitude', i.longitude)
  if (i.accuracy_m !== undefined && i.accuracy_m !== null) f.append('accuracy_m', String(i.accuracy_m))
  if (i.notes) f.append('notes', i.notes)
  if (i.recipient_name) f.append('recipient_name', i.recipient_name)
  if (i.otp) f.append('otp', i.otp)
  for (const p of i.photos) f.append('photos', p)
  return f
}
export const confirmPickupWithPhotos = (id: number, i: EvidenceInput) => post<DeliveryRecord>(`/deliveries/${id}/pickup/`, evidenceForm(i))
export const completeDelivery = (id: number, i: EvidenceInput) => post<DeliveryRecord>(`/deliveries/${id}/complete/`, evidenceForm(i))
export const failDelivery = (id: number, body: { reason: string; note?: string; latitude?: string; longitude?: string }) => post<DeliveryRecord>(`/deliveries/${id}/fail/`, body)
export const pingLocation = (id: number, body: { latitude: string; longitude: string; accuracy_m?: number | null }) => post<{ recorded_at: string }>(`/deliveries/${id}/location/`, body)
export const partnerRatings = (page = 1) => get<Page<PublicReview> & { rating?: { average: number; count: number } }>('/delivery/ratings/', { page })

/* ---------- admin ---------- */
export const adminOverview = () => get<AdminOverview>('/admin/overview/')
export const adminUsers = (q: { role?: string; active?: string; q?: string; page?: number }) => get<Page<AdminUser>>('/admin/users/', q)
export const setUserActive = (id: number, active: boolean, reason: string) => post<AdminUser>(`/admin/users/${id}/${active ? 'reactivate' : 'suspend'}/`, { reason })
export const adminStores = (q: { status?: string; q?: string; page?: number }) => get<Page<AdminStore>>('/admin/stores/', q)
export const setStoreStatus = (id: number, status: string, reason = '') => post<{ id: number; status: string }>(`/admin/stores/${id}/status/`, { status, reason })
export const adminOrders = (q: { status?: string; payment_status?: string; fulfillment_type?: string; q?: string; from?: string; to?: string; page?: number }) => get<Page<AdminOrderRow>>('/admin/orders/', q)
export const adminOrder = (id: number) => get<Record<string, unknown> & { id: number }>(`/admin/orders/${id}/`)
export const adminOrderStatus = (id: number, status: string, reason = '') => post(`/admin/orders/${id}/status/`, { status, reason })
export const adminOrderCancel = (id: number, reason: string) => post(`/admin/orders/${id}/cancel/`, { reason })
export const adminDeliveries = (q: { status?: string; needs_attention?: string; q?: string; page?: number }) => get<Page<DeliveryRecord>>('/admin/deliveries/', q)
export const adminDelivery = (id: number) => get<DeliveryRecord>(`/admin/deliveries/${id}/`)
export const adminAttempts = (id: number) => get<Attempt[]>(`/admin/deliveries/${id}/attempts/`)
export const adminAssign = (id: number, partner_id: number, reason = '') => post<DeliveryRecord>(`/admin/deliveries/${id}/assign/`, { partner_id, reason })
export const adminRetry = (id: number) => post<DeliveryRecord>(`/admin/deliveries/${id}/retry/`)
export const adminCancelDelivery = (id: number, reason: string) => post<DeliveryRecord>(`/admin/deliveries/${id}/cancel/`, { reason })
export const adminPartners = (q: { status?: string; page?: number }) => get<Page<PartnerRecord>>('/admin/delivery-partners/', q)
export const partnerDecision = (id: number, action: 'approve' | 'reject' | 'suspend', reason = '') => post<PartnerRecord>(`/admin/delivery-partners/${id}/${action}/`, { reason })
export const adminReviews = (q: { status?: string; target_type?: string; reported?: string; page?: number }) => get<Page<AdminReview>>('/admin/reviews/', q)
export const moderateReview = (id: number, action: 'hide' | 'reject' | 'restore', reason = '') => post<AdminReview>(`/admin/reviews/${id}/${action}/`, { reason })
export const auditEvents = (q: { action?: string; object_type?: string; actor?: string; page?: number }) => get<Page<AuditEvent>>('/admin/audit-events/', q)
export const adminFeedbackList = (q: { status?: string; page?: number }) => get<Page<import('@/types/platform').FeedbackItem>>('/feedback/', q)
