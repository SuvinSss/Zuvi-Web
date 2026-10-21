import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { Button, ErrorState, Spinner } from '@/components/ui'
import { useAuth } from '@/features/auth/AuthProvider'

export function ProtectedRoute() {
  const { status, retry } = useAuth()
  const location = useLocation()
  if (status === 'loading') return <div className="grid min-h-dvh place-items-center"><Spinner label="Restoring your session…" /></div>
  if (status === 'error') {
    return (
      <div className="grid min-h-dvh place-items-center">
        <ErrorState message="We could not check your session. The server may be starting up." onRetry={retry} />
      </div>
    )
  }
  if (status === 'anonymous') return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />
  return <Outlet />
}

export function RequirePermission({ permission, children }: { permission: 'add' | 'change'; children: React.ReactNode }) {
  const { user } = useAuth()
  if (!user?.permissions[permission]) {
    return (
      <div className="mx-auto max-w-md py-16 text-center">
        <h1 className="text-xl font-semibold text-forest">You don’t have access to this</h1>
        <p className="mt-2 text-sm text-muted">Ask a Super Admin to grant the product permission you need.</p>
        <Button variant="secondary" className="mt-4" onClick={() => history.back()}>Go back</Button>
      </div>
    )
  }
  return <>{children}</>
}
