import { api } from '@/lib/api'
import type { Page } from '@/types/api'
import type {
  Address, AddressInput, Cart, Category, CheckoutInput, CheckoutPreview, ComplaintDetail, ComplaintRow, FeedbackItem, MyReview,
  Notification, OrderDetail, OrderSummary, OrderTracking, PublicProduct, PublicProductDetail, PublicStore, ReviewPage, TicketDetail, TicketRow,
} from '@/types/platform'

const clean = (params: object) => Object.fromEntries(Object.entries(params).filter(([, v]) => v !== undefined && v !== '' && v !== null))
const get = async <T>(url: string, params?: object, signal?: AbortSignal) => (await api.get<T>(url, { params: params ? clean(params) : undefined, signal })).data
const post = async <T>(url: string, body?: unknown) => (await api.post<T>(url, body)).data

/* ---------- public catalogue ---------- */
export interface ProductSearch { q?: string; category?: string; store?: string; ordering?: string; min_price?: string; max_price?: string; page?: number; page_size?: number }
export const listPublicProducts = (query: ProductSearch, signal?: AbortSignal) => get<Page<PublicProduct>>('/public/products/', query, signal)
export const getPublicProduct = (code: string) => get<PublicProductDetail>(`/public/products/by-code/${encodeURIComponent(code)}/`)
export const listCategories = () => get<Category[]>('/public/categories/')
export const listPublicStores = (query: { q?: string; page?: number }) => get<Page<PublicStore>>('/public/stores/', query)
export const getPublicStore = (id: number) => get<PublicStore>(`/public/stores/${id}/`)
export const listStoreReviews = (id: number, page = 1) => get<ReviewPage>(`/public/stores/${id}/reviews/`, { page })
export const listProductReviews = (id: number, page = 1) => get<ReviewPage>(`/public/products/${id}/reviews/`, { page })

/* ---------- customer ---------- */
export const listAddresses = () => get<Address[]>('/customer/addresses/')
export const createAddress = (input: AddressInput) => post<Address>('/customer/addresses/', input)
export const updateAddress = async (id: number, input: AddressInput) => (await api.put<Address>(`/customer/addresses/${id}/`, input)).data
export const deleteAddress = async (id: number) => { await api.delete(`/customer/addresses/${id}/`) }
export const setDefaultAddress = (id: number) => post<Address>(`/customer/addresses/${id}/default/`)

export const getCart = () => get<Cart>('/cart/')
export const addToCart = (productId: number, quantity: string) => post<Cart>('/cart/items/', { product_id: productId, quantity })
export const setCartQuantity = async (itemId: number, quantity: string) => (await api.patch<Cart>(`/cart/items/${itemId}/`, { quantity })).data
export const removeCartItem = async (itemId: number) => (await api.delete<Cart>(`/cart/items/${itemId}/`)).data
export const clearCart = async () => { await api.delete('/cart/') }

export const getCheckoutPreview = () => get<CheckoutPreview>('/checkout/preview/')
export async function placeOrder(input: CheckoutInput, idempotencyKey: string): Promise<OrderDetail> {
  const { data } = await api.post<OrderDetail>('/checkout/', input, { headers: { 'Idempotency-Key': idempotencyKey } })
  return data
}
export const listOrders = (query: { status?: string; page?: number }) => get<Page<OrderSummary>>('/orders/', query)
export const getOrder = (id: number) => get<OrderDetail>(`/orders/${id}/`)
export const cancelOrder = (id: number, reason: string) => post<OrderDetail>(`/orders/${id}/cancel/`, { reason })
export const getTracking = (id: number) => get<OrderTracking>(`/orders/${id}/tracking/`)

/* ---------- reviews ---------- */
export const listMyReviews = (page = 1) => get<Page<MyReview>>('/reviews/mine/', { page })
export interface ReviewInput { store_order: number; target_type: 'STORE' | 'PRODUCT' | 'DELIVERY_PARTNER'; product?: number; rating: number; title?: string; comment?: string }
export const createReview = (input: ReviewInput) => post<MyReview>('/reviews/', input)
export const updateReview = async (id: number, input: { rating?: number; title?: string; comment?: string }) => (await api.patch<MyReview>(`/reviews/${id}/`, input)).data
export const withdrawReview = async (id: number) => (await api.delete<MyReview>(`/reviews/${id}/`)).data
export const reportReview = async (id: number, reason: string, note: string) => { await api.post(`/reviews/${id}/report/`, { reason, note }) }

/* ---------- feedback ---------- */
export const listFeedback = (query: { page?: number; status?: string }) => get<Page<FeedbackItem>>('/feedback/', query)
export const getFeedback = (id: number) => get<FeedbackItem>(`/feedback/${id}/`)
export interface FeedbackInput { kind: string; subject_type: string; store?: number | null; order?: number | null; message: string }
export const submitFeedback = (input: FeedbackInput) => post<FeedbackItem>('/feedback/', input)
export const replyFeedback = (id: number, body: string, is_internal = false) => post<FeedbackItem>(`/feedback/${id}/replies/`, { body, is_internal })
export const setFeedbackStatus = (id: number, status: string) => post<FeedbackItem>(`/feedback/${id}/status/`, { status })
export const escalateFeedback = (id: number) => post<FeedbackItem>(`/feedback/${id}/escalate/`)

/* ---------- support ---------- */
export interface TicketQuery { page?: number; status?: string; priority?: string; category?: string; q?: string; unassigned?: string; mine?: string; escalated?: string }
export const listTickets = (query: TicketQuery) => get<Page<TicketRow>>('/support/tickets/', query)
export const getTicket = (id: number) => get<TicketDetail>(`/support/tickets/${id}/`)
function multipart(fields: Record<string, string | undefined>, files: File[]) {
  const form = new FormData()
  for (const [k, v] of Object.entries(fields)) if (v !== undefined && v !== '') form.append(k, v)
  for (const f of files) form.append('attachments', f)
  return form
}
export const createTicket = (input: { category: string; subject: string; description: string; order?: number | null }, files: File[] = []) =>
  post<TicketDetail>('/support/tickets/', multipart({ category: input.category, subject: input.subject, description: input.description, order: input.order ? String(input.order) : undefined }, files))
export const addTicketMessage = (id: number, body: string, internal = false, files: File[] = []) =>
  post<TicketDetail>(`/support/tickets/${id}/messages/`, multipart({ body, is_internal: internal ? 'true' : 'false' }, files))
export const setTicketStatus = (id: number, status: string, note = '') => post<TicketDetail>(`/support/tickets/${id}/status/`, { status, note })
export const setTicketPriority = (id: number, priority: string) => post<TicketDetail>(`/support/tickets/${id}/priority/`, { priority })
export const assignTicket = (id: number, assignee?: number) => post<TicketDetail>(`/support/tickets/${id}/assign/`, assignee ? { assignee } : {})
export const escalateTicket = (id: number, reason: string) => post<TicketDetail>(`/support/tickets/${id}/escalate/`, { reason })

export interface ComplaintQuery { page?: number; status?: string; severity?: string; category?: string; against_type?: string; q?: string; unassigned?: string; mine?: string }
export const listComplaints = (query: ComplaintQuery) => get<Page<ComplaintRow>>('/support/complaints/', query)
export const getComplaint = (id: number) => get<ComplaintDetail>(`/support/complaints/${id}/`)
export interface ComplaintInput { against_type: string; category: string; description: string; desired_resolution?: string; order?: number | null; store?: number | null; partner?: number | null; product?: number | null }
export const createComplaint = (input: ComplaintInput, files: File[] = []) =>
  post<ComplaintDetail>('/support/complaints/', multipart({
    against_type: input.against_type, category: input.category, description: input.description, desired_resolution: input.desired_resolution,
    order: input.order ? String(input.order) : undefined, store: input.store ? String(input.store) : undefined,
    partner: input.partner ? String(input.partner) : undefined, product: input.product ? String(input.product) : undefined,
  }, files))
export const commentComplaint = (id: number, body: string, internal = false, files: File[] = []) =>
  post<ComplaintDetail>(`/support/complaints/${id}/comments/`, multipart({ body, is_internal: internal ? 'true' : 'false' }, files))
export const complaintAction = (id: number, action: 'assign' | 'request-info' | 'escalate' | 'take-over' | 'resolve' | 'reject' | 'close' | 'reopen', body: Record<string, unknown> = {}) =>
  post<ComplaintDetail>(`/support/complaints/${id}/${action}/`, body)
export const listAgents = () => get<{ id: number; name: string; role: string; open_tickets: number; open_complaints: number }[]>('/support/agents/')
export const supportSummary = () => get<{
  tickets: { by_status: Record<string, number>; unassigned: number; escalated: number; first_response_breached: number; resolution_breached: number }
  complaints: { by_status: Record<string, number>; unassigned: number; escalated: number; acknowledgement_breached: number; resolution_breached: number }
}>('/support/summary/')

/* ---------- notifications ---------- */
export const listNotifications = (query: { page?: number; unread?: string }) => get<Page<Notification>>('/notifications/', query)
export const unreadCount = async () => (await get<{ unread: number }>('/notifications/unread-count/')).unread
export const markNotificationRead = (id: number) => post<Notification>(`/notifications/${id}/read/`)
export const markAllNotificationsRead = () => post<{ updated: number }>('/notifications/read-all/')
