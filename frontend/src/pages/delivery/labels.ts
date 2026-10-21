export const PARTNER_STATUS: Record<string, string> = { PENDING: 'Pending approval', APPROVED: 'Approved', REJECTED: 'Rejected', SUSPENDED: 'Suspended' }
export const PARTNER_DELIVERY_STATUS: Record<string, string> = {
  PENDING_ASSIGNMENT: 'Unassigned', OFFERED: 'New offer', ACCEPTED: 'Go to the store', AT_STORE: 'At the store', IN_TRANSIT: 'Deliver to customer',
  ARRIVED: 'At the customer', DELIVERED: 'Delivered', FAILED: 'Failed', CANCELLED: 'Cancelled',
}
export const FAIL_REASONS: [string, string][] = [
  ['CUSTOMER_UNAVAILABLE', 'Customer unavailable'], ['WRONG_ADDRESS', 'Wrong or unreachable address'], ['CUSTOMER_REFUSED', 'Customer refused the order'],
  ['UNSAFE_LOCATION', 'Unsafe location'], ['VEHICLE_PROBLEM', 'Vehicle problem'], ['OTHER', 'Other (add a note)'],
]
