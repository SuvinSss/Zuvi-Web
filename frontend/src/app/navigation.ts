import {
  Bell, Bike, ClipboardList, FileSpreadsheet, Gauge, Home, LifeBuoy, MessageSquare, Package, ScrollText, Star, Store, Truck, User, Users, Warehouse,
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
  { items: [{ to: '/admin', label: 'Overview', icon: Gauge, end: true }, { to: '/admin/orders', label: 'Orders', icon: ClipboardList }, { to: '/admin/deliveries', label: 'Deliveries', icon: Truck }] },
  { heading: 'People', items: [{ to: '/admin/users', label: 'Users', icon: Users }, { to: '/admin/stores', label: 'Stores', icon: Store }, { to: '/admin/partners', label: 'Delivery partners', icon: Bike }] },
  { heading: 'Catalogue', items: [{ to: '/admin/products', label: 'Products', icon: Package, end: true }, { to: '/admin/products/import', label: 'Excel import', icon: FileSpreadsheet }] },
  { heading: 'Trust & support', items: [{ to: '/admin/reviews', label: 'Reviews', icon: Star }, { to: '/admin/support/tickets', label: 'Tickets', icon: LifeBuoy }, { to: '/admin/support/complaints', label: 'Complaints', icon: ClipboardList }, { to: '/admin/feedback', label: 'Feedback', icon: MessageSquare }, { to: '/admin/audit', label: 'Audit log', icon: ScrollText }, { to: '/admin/notifications', label: 'Notifications', icon: Bell }] },
]
