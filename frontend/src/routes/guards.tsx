import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { ButtonLink, ErrorState, Spinner } from '@/components/ui'
import { useAuth } from '@/features/auth/AuthProvider'
import { homePath } from '@/lib/roles'
import type { Role } from '@/types/api'

export function AccessDenied() {
  const { user } = useAuth()
  return (
    <div className="mx-auto max-w-md px-4 py-20 text-center">
      <h1 className="text-2xl font-semibold text-forest">You don’t have access to this page</h1>
      <p className="mt-2 text-sm text-muted">Your account type can’t open this area. If you think this is a mistake, contact support.</p>
      <ButtonLink to={homePath(user)} className="mt-5">Go to my home</ButtonLink>
    </div>
  )
}

/** Signed-in users with one of `roles` may pass; everyone else is sent to sign in or told they have no access. */
export function RequireRole({ roles }: { roles: Role[] }) {
  const { status, user, retry } = useAuth()
  const location = useLocation()
  if (status === 'loading') return <div className="grid min-h-dvh place-items-center"><Spinner label="Restoring your session…" /></div>
  if (status === 'error') {
    return <div className="grid min-h-dvh place-items-center"><ErrorState message="We could not check your session. The server may be starting up." onRetry={retry} /></div>
  }
  if (status === 'anonymous' || !user) return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />
  if (!roles.includes(user.role)) return <AccessDenied />
  return <Outlet />
}

export function RequirePermission({ permission, children }: { permission: 'add' | 'change'; children: React.ReactNode }) {
  const { user } = useAuth()
  if (!user?.permissions[permission]) {
    return (
      <div className="mx-auto max-w-md py-16 text-center">
        <h1 className="text-xl font-semibold text-forest">You don’t have access to this</h1>
        <p className="mt-2 text-sm text-muted">Ask a Super Admin to grant the product permission you need.</p>
      </div>
    )
  }
  return <>{children}</>
}
