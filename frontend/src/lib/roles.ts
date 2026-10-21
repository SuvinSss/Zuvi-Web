import type { Role, SessionUser } from '@/types/api'

export const STAFF_ROLES: Role[] = ['SUPER_ADMIN', 'ADMIN']
export const SUPPORT_ROLES: Role[] = ['SUPPORT_AGENT', 'SUPPORT_SUPERVISOR']

/** Where each role lands after signing in. */
export function homePath(user: Pick<SessionUser, 'role'> | null | undefined): string {
  switch (user?.role) {
    case 'SUPER_ADMIN':
    case 'ADMIN': return '/admin'
    case 'STORE_USER': return '/store'
    case 'DELIVERY_AGENT': return '/delivery'
    case 'SUPPORT_AGENT':
    case 'SUPPORT_SUPERVISOR': return '/support'
    default: return '/'
  }
}

export const roleLabel: Record<Role, string> = {
  SUPER_ADMIN: 'Super admin', ADMIN: 'Admin', STORE_USER: 'Store', CUSTOMER: 'Customer',
  DELIVERY_AGENT: 'Delivery partner', SUPPORT_AGENT: 'Support agent', SUPPORT_SUPERVISOR: 'Support supervisor',
}
