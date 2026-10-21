export const ORDER_STATUS: Record<string, string> = {
  PLACED: 'Placed', CONFIRMED: 'Confirmed', IN_PROGRESS: 'In progress', COMPLETED: 'Delivered', PARTIALLY_CANCELLED: 'Partly cancelled', CANCELLED: 'Cancelled',
}
export const STORE_ORDER_STATUS: Record<string, string> = {
  PENDING: 'Waiting for store', ACCEPTED: 'Accepted', PREPARING: 'Being prepared', READY: 'Ready', OUT_FOR_DELIVERY: 'Out for delivery',
  READY_FOR_PICKUP: 'Ready for pickup', COMPLETED: 'Completed', CANCELLED: 'Cancelled', REJECTED: 'Rejected by store',
}
export const DELIVERY_STATUS: Record<string, string> = {
  PENDING_ASSIGNMENT: 'Finding a delivery partner', OFFERED: 'Offered to a partner', ACCEPTED: 'Partner heading to the store', AT_STORE: 'Partner at the store',
  IN_TRANSIT: 'On the way to you', ARRIVED: 'Arrived at your address', DELIVERED: 'Delivered', FAILED: 'Delivery attempt failed', CANCELLED: 'Cancelled',
}
export const PAYMENT_STATUS: Record<string, string> = { PENDING: 'To pay on delivery', COLLECTED: 'Paid', CANCELLED: 'Cancelled' }
export const PAYMENT_METHOD: Record<string, string> = { COD: 'Cash on delivery', PAY_AT_PICKUP: 'Pay at pickup' }
export const TICKET_CATEGORY: Record<string, string> = { ORDER: 'Order', DELIVERY: 'Delivery', PAYMENT: 'Payment or refund', PRODUCT: 'Product quality', ACCOUNT: 'Account', TECHNICAL: 'App or technical', OTHER: 'Other' }
export const COMPLAINT_CATEGORY: Record<string, string> = {
  QUALITY: 'Product quality or safety', MISSING_ITEMS: 'Missing or wrong items', LATE: 'Late delivery', BEHAVIOUR: 'Staff or rider behaviour',
  OVERCHARGE: 'Overcharging or billing', NOT_DELIVERED: 'Marked delivered but not received', OTHER: 'Other',
}
export const AGAINST: Record<string, string> = { STORE: 'A store', DELIVERY_PARTNER: 'A delivery partner', PRODUCT: 'A product', PLATFORM: 'The platform' }
export const COMPLAINT_STATUS: Record<string, string> = {
  SUBMITTED: 'Submitted', UNDER_REVIEW: 'Under review', INFO_REQUESTED: 'We need more information', ESCALATED: 'Escalated to a supervisor', RESOLVED: 'Resolved', REJECTED: 'Not upheld', CLOSED: 'Closed',
}
export const TICKET_STATUS: Record<string, string> = { OPEN: 'Open', IN_PROGRESS: 'In progress', WAITING_CUSTOMER: 'Waiting for your reply', RESOLVED: 'Resolved', CLOSED: 'Closed' }
export const label = (map: Record<string, string>, key: string) => map[key] ?? key.replace(/_/g, ' ').toLowerCase().replace(/^./, (c) => c.toUpperCase())
