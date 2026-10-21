import { ExternalLink, LogOut, Menu, PackagePlus, Package, FileSpreadsheet, X } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { Logo } from '@/components/Logo'
import { useAuth } from '@/features/auth/AuthProvider'

const NAV = [
  { to: '/products', label: 'Products', icon: Package, end: true },
  { to: '/products/new', label: 'New product', icon: PackagePlus, end: true },
  { to: '/products/import', label: 'Import from Excel', icon: FileSpreadsheet, end: true },
]

function NavItems({ onNavigate }: { onNavigate?: () => void }) {
  const { user } = useAuth()
  return (
    <nav aria-label="Main" className="flex flex-col gap-1">
      {NAV.filter((item) => item.to === '/products' || user?.permissions.add).map(({ to, label, icon: Icon, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          onClick={onNavigate}
          className={({ isActive }) =>
            `flex min-h-11 items-center gap-3 rounded-control px-3 text-sm font-medium transition-colors ${
              isActive ? 'bg-white/12 text-white' : 'text-white/75 hover:bg-white/8 hover:text-white'
            }`
          }
        >
          <Icon className="size-5" aria-hidden="true" />
          {label}
        </NavLink>
      ))}
      <a
        href="/management/dashboard/"
        className="mt-2 flex min-h-11 items-center gap-3 rounded-control px-3 text-sm font-medium text-white/75 transition-colors hover:bg-white/8 hover:text-white"
      >
        <ExternalLink className="size-5" aria-hidden="true" />
        Orders, stores &amp; inventory
      </a>
    </nav>
  )
}

function SidebarFooter() {
  const { user, signOut } = useAuth()
  const navigate = useNavigate()
  return (
    <div className="mt-auto border-t border-white/10 pt-4">
      <p className="truncate text-sm font-medium text-white">{user?.name}</p>
      <p className="mb-3 truncate text-xs text-white/60">{user?.role.replace('_', ' ').toLowerCase()}</p>
      <button
        type="button"
        onClick={() => void signOut().then(() => navigate('/login'))}
        className="flex min-h-11 w-full items-center gap-3 rounded-control px-3 text-sm font-medium text-white/75 hover:bg-white/8 hover:text-white"
      >
        <LogOut className="size-5" aria-hidden="true" />
        Sign out
      </button>
    </div>
  )
}

export function AppLayout() {
  const location = useLocation()
  // The drawer is open only for the route it was opened on, so navigating closes it.
  const [openAt, setOpenAt] = useState<string | null>(null)
  const open = openAt === location.pathname
  const setOpen = useCallback((value: boolean) => setOpenAt(value ? location.pathname : null), [location.pathname])
  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => event.key === 'Escape' && setOpen(false)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, setOpen])

  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[16rem_1fr]">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded-control focus:bg-white focus:px-4 focus:py-2 focus:shadow-pop">
        Skip to content
      </a>

      {/* Desktop sidebar */}
      <aside className="sticky top-0 hidden h-dvh flex-col gap-6 bg-night p-5 lg:flex">
        <Logo variant="dark" className="w-40" />
        <NavItems />
        <SidebarFooter />
      </aside>

      {/* Mobile / tablet top bar + drawer */}
      <header className="sticky top-0 z-30 flex items-center justify-between bg-night px-4 py-2 lg:hidden">
        <Logo variant="dark" className="w-28" />
        <button
          type="button"
          aria-label={open ? 'Close menu' : 'Open menu'}
          aria-expanded={open}
          aria-controls="mobile-nav"
          onClick={() => setOpen(!open)}
          className="grid size-11 place-items-center rounded-control text-white hover:bg-white/10"
        >
          {open ? <X className="size-6" aria-hidden="true" /> : <Menu className="size-6" aria-hidden="true" />}
        </button>
      </header>
      {open && (
        <div className="fixed inset-0 z-20 lg:hidden">
          <button type="button" aria-label="Close menu" className="absolute inset-0 bg-black/40" onClick={() => setOpen(false)} />
          <div id="mobile-nav" className="rise absolute inset-y-0 right-0 flex w-[min(20rem,85vw)] flex-col gap-4 overflow-y-auto bg-night p-5 pt-20">
            <NavItems onNavigate={() => setOpen(false)} />
            <SidebarFooter />
          </div>
        </div>
      )}

      <main id="main" tabIndex={-1} className="mx-auto w-full min-w-0 max-w-6xl px-4 py-6 sm:px-6 lg:px-10 lg:py-10">
        <Outlet />
      </main>
    </div>
  )
}
