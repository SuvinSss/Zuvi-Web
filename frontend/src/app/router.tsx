import { lazy, Suspense } from 'react'
import { createBrowserRouter, Navigate, type RouteObject } from 'react-router-dom'
import { Spinner } from '@/components/ui'
import { AppLayout } from '@/layouts/AppLayout'
import { ProtectedRoute, RequirePermission } from '@/routes/ProtectedRoute'

// Route-level code splitting keeps the first load small.
const LoginPage = lazy(() => import('@/pages/LoginPage'))
const ProductsPage = lazy(() => import('@/pages/ProductsPage'))
const ProductFormPage = lazy(() => import('@/pages/ProductFormPage'))
const ImportPage = lazy(() => import('@/pages/ImportPage'))
const NotFoundPage = lazy(() => import('@/pages/NotFoundPage'))

const page = (node: React.ReactNode) => <Suspense fallback={<Spinner />}>{node}</Suspense>

export const routes: RouteObject[] = [
  { path: '/login', element: page(<LoginPage />) },
  {
    element: <ProtectedRoute />,
    children: [
      {
        element: <AppLayout />,
        children: [
          { index: true, element: <Navigate to="/products" replace /> },
          { path: '/products', element: page(<ProductsPage />) },
          { path: '/products/new', element: page(<RequirePermission permission="add"><ProductFormPage /></RequirePermission>) },
          { path: '/products/import', element: page(<RequirePermission permission="add"><ImportPage /></RequirePermission>) },
          { path: '/products/:id', element: page(<ProductFormPage />) },
          { path: '*', element: page(<NotFoundPage />) },
        ],
      },
    ],
  },
]

export const createRouter = () => createBrowserRouter(routes)
