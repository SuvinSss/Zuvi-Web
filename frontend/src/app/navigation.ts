import {
  BarChart3, Bell, Bike, ClipboardCheck, ClipboardList, Upload, Building2, PlusCircle, FileSpreadsheet, Gauge, Home, LifeBuoy, MessageSquare, Package, ScrollText, Star, Store, Tags, Truck, User, UserCog, Users, Warehouse,
} from 'lucide-react'
import type { NavGroup, NavItem } from '@/layouts/DashboardLayout'

export const STORE_NAV: NavGroup[] = [
  { items: [{ to: '/store', label: 'Dashboard', icon: Gauge, end: true }, { to: '/store/orders', label: 'Orders', icon: ClipboardList }, { to: '/store/deliveries', label: 'Deliveries', icon: Truck }] },
  { heading: 'Catalogue', items: [{ to: '/store/products', label: 'Products', icon: Package }, { to: '/store/stock', label: 'Stock', icon: Warehouse }] },
  { heading: 'Customers', items: [{ to: '/store/reviews', label: 'Reviews', icon: Star }, { to: '/store/notifications', label: 'Notifications', icon: Bell }] },
]
export const STORE_BOTTOM: NavItem[] = [
  { to: '/store', label: 'Home', icon: Home, end: true }, { to: '/store/orders', label: 'Orders', icon: ClipboardList }, { to: '/store/products', label: 'Products', icon: Package }, { to: '/store/stock', label: 'Stock', icon: Warehouse },
]

export const DELIVERY_NAV: NavGroup[] = [
  { items: [{ to: '/delivery', label: 'Today', icon: Home, end: true }, { to: '/delivery/assignments', label: 'Deliveries', icon: Truck }, { to: '/delivery/profile', label: 'Profile & ratings', icon: User }, { to: '/delivery/notifications', label: 'Notifications', icon: Bell }] },
]
export const DELIVERY_BOTTOM: NavItem[] = [
  { to: '/delivery', label: 'Today', icon: Home, end: true }, { to: '/delivery/assignments', label: 'Deliveries', icon: Truck }, { to: '/delivery/notifications', label: 'Alerts', icon: Bell }, { to: '/delivery/profile', label: 'Profile', icon: User },
]

export const SUPPORT_NAV: NavGroup[] = [
  { items: [{ to: '/support', label: 'Queue', icon: Gauge, end: true }, { to: '/support/tickets', label: 'Tickets', icon: LifeBuoy }, { to: '/support/complaints', label: 'Complaints', icon: ClipboardList }, { to: '/support/feedback', label: 'Feedback', icon: MessageSquare }, { to: '/support/notifications', label: 'Notifications', icon: Bell }] },
]

export const ADMIN_NAV: NavGroup[] = [
  { heading: 'Overview', items: [{ to: '/admin', label: 'Dashboard', icon: Gauge, end: true }, { to: '/admin/reports', label: 'Analytics and reports', icon: BarChart3 }] },
  { heading: 'Commerce', items: [{ to: '/admin/orders', label: 'Orders', icon: ClipboardList }, { to: '/admin/products', label: 'Products', icon: Package, end: true }, { to: '/admin/categories', label: 'Categories', icon: Tags }] },
  { heading: 'Stores', items: [{ to: '/admin/stores', label: 'All stores', icon: Store, end: true }, { to: '/admin/stores/new', label: 'Add store', icon: PlusCircle }, { to: '/admin/approvals/stores', label: 'Pending approvals', icon: Building2 }] },
  { heading: 'People', items: [{ to: '/admin/customers', label: 'Customers', icon: Users }, { to: '/admin/partners', label: 'Delivery partners', icon: Bike }, { to: '/admin/users', label: 'Users and roles', icon: UserCog }] },
  { heading: 'Delivery operations', items: [{ to: '/admin/deliveries', label: 'Deliveries', icon: Truck }] },
  { heading: 'Engagement', items: [{ to: '/admin/reviews', label: 'Reviews and ratings', icon: Star }, { to: '/admin/feedback', label: 'Customer feedback', icon: MessageSquare }, { to: '/admin/support/tickets', label: 'Support tickets', icon: LifeBuoy }, { to: '/admin/support/complaints', label: 'Complaints', icon: ClipboardList }, { to: '/admin/notifications', label: 'Notifications', icon: Bell }] },
  { heading: 'Administration', items: [{ to: '/admin/approvals', label: 'Approval center', icon: ClipboardCheck, end: true }, { to: '/admin/products/import', label: 'Import products', icon: FileSpreadsheet }, { to: '/admin/imports', label: 'Bulk import jobs', icon: Upload }, { to: '/admin/audit', label: 'Audit log', icon: ScrollText }] },
]
