import { lazy, Suspense, type ReactNode } from 'react'
import { createBrowserRouter, type RouteObject } from 'react-router-dom'
import { Spinner } from '@/components/ui'
import { useAuth } from '@/features/auth/AuthProvider'
import { DashboardLayout } from '@/layouts/DashboardLayout'
import { PublicLayout } from '@/layouts/PublicLayout'
import { RequirePermission, RequireRole } from '@/routes/guards'
import { ADMIN_NAV, DELIVERY_BOTTOM, DELIVERY_NAV, STORE_BOTTOM, STORE_NAV, SUPPORT_NAV } from './navigation'

// Route-level code splitting keeps the first load small.
const L = lazy
const LoginPage = L(() => import('@/pages/LoginPage'))
const RegisterPage = L(() => import('@/pages/auth/RegisterPage'))
const ForgotPasswordPage = L(() => import('@/pages/auth/ForgotPasswordPage'))
const ResetPasswordPage = L(() => import('@/pages/auth/ResetPasswordPage'))
const NotFoundPage = L(() => import('@/pages/NotFoundPage'))
const NotificationsPage = lazy(() => import('@/pages/NotificationsPage'))

const HomePage = L(() => import('@/pages/public/HomePage'))
const ShopPage = L(() => import('@/pages/public/ShopPage'))
const ProductPage = L(() => import('@/pages/public/ProductPage'))
const StoresPage = L(() => import('@/pages/public/StoresPage'))
const StorePage = L(() => import('@/pages/public/StorePage'))
const HelpPage = L(() => import('@/pages/public/HelpPage'))

const CartPage = L(() => import('@/pages/customer/CartPage'))
const CheckoutPage = L(() => import('@/pages/customer/CheckoutPage'))
const OrdersPage = L(() => import('@/pages/customer/OrdersPage'))
const OrderPage = L(() => import('@/pages/customer/OrderPage'))
const AccountPage = L(() => import('@/pages/customer/AccountPage'))
const AddressesPage = L(() => import('@/pages/customer/AddressesPage'))
const MyReviewsPage = L(() => import('@/pages/customer/MyReviewsPage'))
const FeedbackPage = L(() => import('@/pages/customer/FeedbackPage'))
const TicketsList = lazy(() => import('@/pages/support/Lists').then((m) => ({ default: m.TicketsList })))
const ComplaintsList = lazy(() => import('@/pages/support/Lists').then((m) => ({ default: m.ComplaintsList })))
const NewTicketPage = lazy(() => import('@/pages/support/Forms').then((m) => ({ default: m.NewTicketPage })))
const NewComplaintPage = lazy(() => import('@/pages/support/Forms').then((m) => ({ default: m.NewComplaintPage })))
const TicketDetailPage = lazy(() => import('@/pages/support/Details').then((m) => ({ default: m.TicketDetailPage })))
const ComplaintDetailPage = lazy(() => import('@/pages/support/Details').then((m) => ({ default: m.ComplaintDetailPage })))
const SupportHome = L(() => import('@/pages/support/SupportHome'))
const StaffFeedback = L(() => import('@/pages/support/StaffFeedback'))

const StoreDashboard = L(() => import('@/pages/store/StoreDashboard'))
const StoreOrders = L(() => import('@/pages/store/StoreOrders'))
const StoreOrderPage = L(() => import('@/pages/store/StoreOrderPage'))
const StoreProducts = L(() => import('@/pages/store/StoreProducts'))
const StoreDeliveries = L(() => import('@/pages/store/StoreDeliveries'))
const StoreReviews = L(() => import('@/pages/store/StoreReviews'))

const PartnerGate = L(() => import('@/pages/delivery/PartnerGate'))
const DeliveryHome = L(() => import('@/pages/delivery/DeliveryHome'))
const Assignments = L(() => import('@/pages/delivery/Assignments'))
const AssignmentPage = L(() => import('@/pages/delivery/AssignmentPage'))
const DeliveryProfile = L(() => import('@/pages/delivery/DeliveryProfile'))

const AdminOverview = L(() => import('@/pages/admin/AdminOverview'))
const AdminUsers = L(() => import('@/pages/admin/AdminUsers'))
const AdminStores = L(() => import('@/pages/admin/AdminStores'))
const AdminPartners = L(() => import('@/pages/admin/AdminPartners'))
const AdminReviews = L(() => import('@/pages/admin/AdminReviews'))
const AdminAudit = L(() => import('@/pages/admin/AdminAudit'))
const AdminOrdersList = lazy(() => import('@/pages/admin/AdminOrders').then((m) => ({ default: m.AdminOrdersList })))
const AdminOrderPage = lazy(() => import('@/pages/admin/AdminOrders').then((m) => ({ default: m.AdminOrderPage })))
const AdminDeliveriesList = lazy(() => import('@/pages/admin/AdminDeliveries').then((m) => ({ default: m.AdminDeliveriesList })))
const AdminDeliveryPage = lazy(() => import('@/pages/admin/AdminDeliveries').then((m) => ({ default: m.AdminDeliveryPage })))
const ProductsPage = L(() => import('@/pages/ProductsPage'))
const ProductFormPage = lazy(() => import('@/pages/ProductFormPage'))
const ImportPage = L(() => import('@/pages/ImportPage'))

const page = (node: ReactNode) => <Suspense fallback={<Spinner />}>{node}</Suspense>
const R = (Component: React.ComponentType) => page(<Component />)

const SUPPORT_BASE = '/support'
export const routes: RouteObject[] = [
  { path: '/login', element: page(<LoginPage />) },
  { path: '/register', element: page(<RegisterPage />) },
  { path: '/register-partner', element: page(<RegisterPage partner />) },
  { path: '/forgot-password', element: page(<ForgotPasswordPage />) },
  { path: '/reset-password', element: page(<ResetPasswordPage />) },
  {
    element: <PublicLayout />,
    children: [
      { index: true, element: R(HomePage) },
      { path: 'shop', element: R(ShopPage) },
      { path: 'shop/:code', element: R(ProductPage) },
      { path: 'stores', element: R(StoresPage) },
      { path: 'stores/:id', element: R(StorePage) },
      { path: 'help', element: R(HelpPage) },
      {
        element: <RequireRole roles={['CUSTOMER']} />,
        children: [
          { path: 'cart', element: R(CartPage) },
          { path: 'checkout', element: R(CheckoutPage) },
          { path: 'account', element: R(AccountPage) },
          { path: 'account/orders', element: R(OrdersPage) },
          { path: 'account/orders/:id', element: R(OrderPage) },
          { path: 'account/addresses', element: R(AddressesPage) },
          { path: 'account/reviews', element: R(MyReviewsPage) },
          { path: 'account/feedback', element: R(FeedbackPage) },
          { path: 'account/notifications', element: page(<NotificationsPage area="/account" />) },
          { path: 'account/support', element: page(<TicketsList base="/account/support" staff={false} />) },
          { path: 'account/support/new-ticket', element: page(<NewTicketPage base="/account/support" />) },
          { path: 'account/support/new-complaint', element: page(<NewComplaintPage base="/account/support" />) },
          { path: 'account/support/tickets/:id', element: page(<TicketDetailPage base="/account/support" staff={false} />) },
          { path: 'account/support/complaints', element: page(<ComplaintsList base="/account/support" staff={false} />) },
          { path: 'account/support/complaints/:id', element: page(<ComplaintDetailPage base="/account/support" staff={false} />) },
        ],
      },
    ],
  },
  {
    path: 'store',
    element: <RequireRole roles={['STORE_USER']} />,
    children: [{
      element: <DashboardLayout base="/store" areaLabel="Store" groups={STORE_NAV} bottom={STORE_BOTTOM} />,
      children: [
        { index: true, element: R(StoreDashboard) },
        { path: 'orders', element: R(StoreOrders) },
        { path: 'orders/:id', element: R(StoreOrderPage) },
        { path: 'products', element: page(<StoreProducts mode="products" />) },
        { path: 'products/new', element: page(<ProductFormPage scope="store" />) },
        { path: 'products/:id', element: page(<ProductFormPage scope="store" />) },
        { path: 'stock', element: page(<StoreProducts mode="stock" />) },
        { path: 'deliveries', element: R(StoreDeliveries) },
        { path: 'reviews', element: R(StoreReviews) },
        { path: 'notifications', element: page(<NotificationsPage area="/store" />) },
        { path: '*', element: R(NotFoundPage) },
      ],
    }],
  },
  {
    path: 'delivery',
    element: <RequireRole roles={['DELIVERY_AGENT']} />,
    children: [{
      element: <DashboardLayout base="/delivery" areaLabel="Delivery" groups={DELIVERY_NAV} bottom={DELIVERY_BOTTOM} />,
      children: [
        { path: 'profile', element: R(DeliveryProfile) },
        { path: 'notifications', element: page(<NotificationsPage area="/delivery" />) },
        {
          element: R(PartnerGate),
          children: [
            { index: true, element: R(DeliveryHome) },
            { path: 'assignments', element: R(Assignments) },
            { path: 'assignments/:id', element: R(AssignmentPage) },
          ],
        },
        { path: '*', element: R(NotFoundPage) },
      ],
    }],
  },
  {
    path: 'support',
    element: <RequireRole roles={['SUPPORT_AGENT', 'SUPPORT_SUPERVISOR']} />,
    children: [{
      element: <DashboardLayout base={SUPPORT_BASE} areaLabel="Support" groups={SUPPORT_NAV} />,
      children: [
        { index: true, element: page(<SupportHome base={SUPPORT_BASE} />) },
        { path: 'tickets', element: page(<TicketsList base={SUPPORT_BASE} staff />) },
        { path: 'tickets/:id', element: page(<SupervisorAware kind="ticket" base={SUPPORT_BASE} />) },
        { path: 'complaints', element: page(<ComplaintsList base={SUPPORT_BASE} staff />) },
        { path: 'complaints/:id', element: page(<SupervisorAware kind="complaint" base={SUPPORT_BASE} />) },
        { path: 'feedback', element: R(StaffFeedback) },
        { path: 'notifications', element: page(<NotificationsPage area="/support" />) },
        { path: '*', element: R(NotFoundPage) },
      ],
    }],
  },
  {
    path: 'admin',
    element: <RequireRole roles={['ADMIN', 'SUPER_ADMIN']} />,
    children: [{
      element: <DashboardLayout base="/admin" areaLabel="Administration" groups={ADMIN_NAV} />,
      children: [
        { index: true, element: R(AdminOverview) },
        { path: 'orders', element: R(AdminOrdersList) },
        { path: 'orders/:id', element: R(AdminOrderPage) },
        { path: 'deliveries', element: R(AdminDeliveriesList) },
        { path: 'deliveries/:id', element: R(AdminDeliveryPage) },
        { path: 'users', element: R(AdminUsers) },
        { path: 'stores', element: R(AdminStores) },
        { path: 'partners', element: R(AdminPartners) },
        { path: 'products', element: R(ProductsPage) },
        { path: 'products/new', element: page(<RequirePermission permission="add"><ProductFormPage scope="admin" /></RequirePermission>) },
        { path: 'products/import', element: page(<RequirePermission permission="add"><ImportPage /></RequirePermission>) },
        { path: 'products/:id', element: page(<ProductFormPage scope="admin" />) },
        { path: 'reviews', element: R(AdminReviews) },
        { path: 'support/tickets', element: page(<TicketsList base="/admin/support" staff />) },
        { path: 'support/tickets/:id', element: page(<TicketDetailPage base="/admin/support" staff supervisor />) },
        { path: 'support/complaints', element: page(<ComplaintsList base="/admin/support" staff />) },
        { path: 'support/complaints/:id', element: page(<ComplaintDetailPage base="/admin/support" staff supervisor />) },
        { path: 'feedback', element: R(StaffFeedback) },
        { path: 'audit', element: R(AdminAudit) },
        { path: 'notifications', element: page(<NotificationsPage area="/admin" />) },
        { path: '*', element: R(NotFoundPage) },
      ],
    }],
  },
  { path: '*', element: <NotFoundShell /> },
]

function NotFoundShell() {
  return <div className="mx-auto max-w-md px-4 py-20"><Suspense fallback={<Spinner />}><NotFoundPage /></Suspense></div>
}

function SupervisorAware({ kind, base }: { kind: 'ticket' | 'complaint'; base: string }) {
  const { user } = useAuth()
  const supervisor = user?.role === 'SUPPORT_SUPERVISOR'
  return kind === 'ticket' ? <TicketDetailPage base={base} staff supervisor={supervisor} /> : <ComplaintDetailPage base={base} staff supervisor={supervisor} />
}

export const createRouter = () => createBrowserRouter(routes)
