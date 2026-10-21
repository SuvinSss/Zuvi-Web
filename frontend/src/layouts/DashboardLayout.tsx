import { Bell, LogOut, Menu, X, type LucideIcon } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { useCallback, useEffect, useState } from 'react'
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { Logo } from '@/components/Logo'
import { useAuth } from '@/features/auth/AuthProvider'
import { roleLabel } from '@/lib/roles'
import { unreadCount } from '@/services/platform'

export interface NavItem { to: string; label: string; icon: LucideIcon; end?: boolean; badge?: number }
export interface NavGroup { heading?: string; items: NavItem[] }

const linkClass = ({ isActive }: { isActive: boolean }) =>
  `flex min-h-11 items-center gap-3 rounded-control px-3 text-sm font-medium transition-colors ${isActive ? 'bg-white/14 text-white' : 'text-white/75 hover:bg-white/8 hover:text-white'}`

function NavList({ groups, onNavigate }: { groups: NavGroup[]; onNavigate?: () => void }) {
  return (
    <nav aria-label="Main" className="flex flex-col gap-4">
      {groups.map((group, index) => (
        <div key={group.heading ?? index} className="flex flex-col gap-1">
          {group.heading && <p className="px-3 pb-1 text-xs font-semibold uppercase tracking-wider text-white/45">{group.heading}</p>}
          {group.items.map(({ to, label, icon: Icon, end, badge }) => (
            <NavLink key={to} to={to} end={end} onClick={onNavigate} className={linkClass}>
              <Icon className="size-5 shrink-0" aria-hidden="true" />
              <span className="min-w-0 flex-1 truncate">{label}</span>
              {badge ? <span className="rounded-full bg-fresh px-2 py-0.5 text-xs font-semibold text-night" aria-label={`${badge} waiting`}>{badge}</span> : null}
            </NavLink>
          ))}
        </div>
      ))}
    </nav>
  )
}

function Account({ onNavigate }: { onNavigate?: () => void }) {
  const { user, signOut } = useAuth()
  const navigate = useNavigate()
  return (
    <div className="mt-auto border-t border-white/10 pt-4">
      <p className="truncate text-sm font-medium text-white">{user?.name}</p>
      <p className="mb-3 truncate text-xs text-white/60">{user ? roleLabel[user.role] : ''}{user?.store ? ` · ${user.store.name}` : ''}</p>
      <button
        type="button"
        onClick={() => { onNavigate?.(); void signOut().then(() => navigate('/login')) }}
        className="flex min-h-11 w-full items-center gap-3 rounded-control px-3 text-sm font-medium text-white/75 hover:bg-white/8 hover:text-white"
      >
        <LogOut className="size-5" aria-hidden="true" />
        Sign out
      </button>
    </div>
  )
}

/** Shell for staff areas (store, delivery, support, admin). `base` is the area's path, e.g. "/store". */
export function DashboardLayout({ base, areaLabel, groups, bottom }: { base: string; areaLabel: string; groups: NavGroup[]; bottom?: NavItem[] }) {
  const location = useLocation()
  const [openAt, setOpenAt] = useState<string | null>(null)
  const open = openAt === location.pathname
  const setOpen = useCallback((value: boolean) => setOpenAt(value ? location.pathname : null), [location.pathname])
  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => event.key === 'Escape' && setOpen(false)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, setOpen])
  const unread = useQuery({ queryKey: ['notifications', 'unread'], queryFn: unreadCount, refetchInterval: 60_000, staleTime: 30_000 })

  const bell = (
    <Link to={`${base}/notifications`} aria-label={unread.data ? `Notifications, ${unread.data} unread` : 'Notifications'} className="relative grid size-11 place-items-center rounded-control text-white hover:bg-white/10">
      <Bell className="size-5" aria-hidden="true" />
      {unread.data ? <span className="absolute right-1.5 top-1.5 grid min-w-4 place-items-center rounded-full bg-fresh px-1 text-[0.65rem] font-bold leading-4 text-night">{unread.data > 99 ? '99+' : unread.data}</span> : null}
    </Link>
  )

  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[16rem_1fr]">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded-control focus:bg-white focus:px-4 focus:py-2 focus:shadow-pop">Skip to content</a>

      <aside className="sticky top-0 hidden h-dvh flex-col gap-6 overflow-y-auto bg-night p-5 lg:flex">
        <div className="flex items-center justify-between">
          <Logo variant="dark" className="w-32" />
          {bell}
        </div>
        <p className="-mt-3 px-1 text-xs font-semibold uppercase tracking-wider text-white/45">{areaLabel}</p>
        <NavList groups={groups} />
        <Account />
      </aside>

      <header className="sticky top-0 z-30 flex items-center justify-between bg-night px-3 py-1.5 pt-[max(0.375rem,env(safe-area-inset-top))] lg:hidden">
        <div className="flex items-center gap-3 pl-1">
          <Logo variant="dark" className="w-24" />
          <span className="text-xs font-semibold uppercase tracking-wider text-white/55">{areaLabel}</span>
        </div>
        <div className="flex items-center">
          {bell}
          <button type="button" aria-label={open ? 'Close menu' : 'Open menu'} aria-expanded={open} aria-controls="mobile-nav" onClick={() => setOpen(!open)} className="grid size-11 place-items-center rounded-control text-white hover:bg-white/10">
            {open ? <X className="size-6" aria-hidden="true" /> : <Menu className="size-6" aria-hidden="true" />}
          </button>
        </div>
      </header>
      {open && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <button type="button" aria-label="Close menu" className="absolute inset-0 bg-black/40" onClick={() => setOpen(false)} />
          <div id="mobile-nav" className="rise absolute inset-y-0 right-0 flex w-[min(20rem,88vw)] flex-col gap-4 overflow-y-auto bg-night p-5 pt-6">
            <button type="button" aria-label="Close menu" onClick={() => setOpen(false)} className="absolute right-3 top-3 grid size-11 place-items-center rounded-control text-white hover:bg-white/10"><X className="size-6" aria-hidden="true" /></button>
            <Logo variant="dark" className="w-28" />
            <NavList groups={groups} onNavigate={() => setOpen(false)} />
            <Account onNavigate={() => setOpen(false)} />
          </div>
        </div>
      )}

      <main id="main" tabIndex={-1} className={`mx-auto w-full min-w-0 max-w-6xl px-4 py-6 sm:px-6 lg:px-10 lg:py-10 ${bottom ? 'pb-24 lg:pb-10' : ''}`}>
        <Outlet />
      </main>

      {bottom && (
        <nav aria-label="Quick navigation" className="fixed inset-x-0 bottom-0 z-30 grid border-t border-line bg-white pb-[env(safe-area-inset-bottom)] shadow-pop lg:hidden" style={{ gridTemplateColumns: `repeat(${bottom.length}, minmax(0, 1fr))` }}>
          {bottom.map(({ to, label, icon: Icon, end, badge }) => (
            <NavLink key={to} to={to} end={end} className={({ isActive }) => `relative flex min-h-14 flex-col items-center justify-center gap-0.5 text-xs font-medium ${isActive ? 'text-forest' : 'text-muted'}`}>
              {({ isActive }) => (
                <>
                  <Icon className={`size-6 ${isActive ? 'text-emerald' : ''}`} aria-hidden="true" />
                  {label}
                  {badge ? <span className="absolute right-[calc(50%-1.5rem)] top-1 grid min-w-4 place-items-center rounded-full bg-danger px-1 text-[0.65rem] font-bold leading-4 text-white">{badge}</span> : null}
                </>
              )}
            </NavLink>
          ))}
        </nav>
      )}
    </div>
  )
}
