import { useQuery } from '@tanstack/react-query'
import { Bell, ChevronDown, LogOut, Search, UserCircle } from 'lucide-react'
import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '@/features/auth/AuthProvider'
import { useDebounced } from '@/hooks/useDebounced'
import { ADMIN_NAV } from '@/app/navigation'
import { roleLabel } from '@/lib/roles'
import { adminCounts, adminSearch } from '@/services/ops'
import { unreadCount } from '@/services/platform'
import { DashboardLayout, type NavGroup } from './DashboardLayout'

/** Real pending counts (from the API) are attached to the navigation entries they belong to. */
const BADGES: Record<string, keyof Awaited<ReturnType<typeof adminCounts>>> = {
  '/admin/orders': 'orders_awaiting_confirmation', '/admin/deliveries': 'deliveries_needing_attention', '/admin/partners': 'partners_pending',
  '/admin/stores': 'stores_pending', '/admin/products': 'products_pending', '/admin/support/tickets': 'tickets_open', '/admin/support/complaints': 'complaints_open',
}

function GlobalSearch() {
  const id = useId()
  const navigate = useNavigate()
  const [text, setText] = useState('')
  const [open, setOpen] = useState(false)
  const term = useDebounced(text.trim(), 250)
  const q = useQuery({ queryKey: ['admin-search', term], queryFn: () => adminSearch(term), enabled: term.length >= 2, staleTime: 15_000 })
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const away = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', away)
    return () => document.removeEventListener('mousedown', away)
  }, [])
  const hits = q.data?.results ?? []
  return (
    <div ref={box} className="relative min-w-0 flex-1 sm:max-w-md">
      <label htmlFor={id} className="sr-only">Search orders, customers, stores, products and tickets</label>
      <Search className="pointer-events-none absolute left-3 top-1/2 size-5 -translate-y-1/2 text-muted" aria-hidden="true" />
      <input id={id} type="search" value={text} autoComplete="off" placeholder="Search orders, customers, stores, products…" aria-expanded={open && term.length >= 2} aria-controls={`${id}-list`}
        onChange={(e) => { setText(e.target.value); setOpen(true) }} onFocus={() => setOpen(true)} onKeyDown={(e) => { if (e.key === 'Escape') setOpen(false) }}
        className="min-h-11 w-full rounded-full border border-line bg-white pl-10 pr-4 text-base placeholder:text-muted/70 focus:border-emerald focus:outline-none focus:ring-2 focus:ring-emerald/30 sm:text-sm" />
      {open && term.length >= 2 && (
        <div id={`${id}-list`} className="absolute left-0 right-0 top-12 z-40 max-h-96 overflow-auto rounded-card border border-line bg-white shadow-pop">
          {q.isPending ? <p className="p-4 text-sm text-muted">Searching…</p> : q.isError ? <p role="alert" className="p-4 text-sm text-danger">Search is unavailable. Try again.</p> : hits.length === 0 ? <p className="p-4 text-sm text-muted">Nothing found for “{term}”.</p> : (
            <ul>
              {hits.map((h) => (
                <li key={`${h.type}-${h.path}-${h.label}`}>
                  <button type="button" onClick={() => { setOpen(false); setText(''); navigate(h.path) }} className="flex min-h-11 w-full items-center justify-between gap-3 px-4 py-2 text-left text-sm hover:bg-pale">
                    <span className="min-w-0"><strong className="block truncate">{h.label}</strong><span className="block truncate text-xs text-muted">{h.detail}</span></span>
                    <span className="shrink-0 rounded-full bg-canvas px-2 py-0.5 text-xs text-muted">{h.type}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}

function ProfileMenu() {
  const { user, signOut } = useAuth()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const away = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false) }
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', away)
    document.addEventListener('keydown', esc)
    return () => { document.removeEventListener('mousedown', away); document.removeEventListener('keydown', esc) }
  }, [open])
  return (
    <div ref={box} className="relative">
      <button type="button" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((v) => !v)} className="inline-flex min-h-11 items-center gap-1 rounded-control px-2 text-sm font-medium hover:bg-pale">
        <UserCircle className="size-6 text-forest" aria-hidden="true" /><span className="hidden max-w-[10rem] truncate md:inline">{user?.first_name || user?.username}</span><ChevronDown className="size-4" aria-hidden="true" />
      </button>
      {open && (
        <div role="menu" className="absolute right-0 top-12 z-40 w-60 rounded-card border border-line bg-white p-2 shadow-pop">
          <p className="px-3 py-2 text-sm"><strong className="block truncate">{user?.name}</strong><span className="text-xs text-muted">{user ? roleLabel[user.role] : ''}</span></p>
          <Link role="menuitem" to="/admin/notifications" onClick={() => setOpen(false)} className="flex min-h-11 items-center rounded-control px-3 text-sm hover:bg-pale">Notifications</Link>
          <button type="button" role="menuitem" onClick={() => void signOut().then(() => navigate('/login'))} className="flex min-h-11 w-full items-center gap-2 rounded-control px-3 text-sm text-danger hover:bg-danger-bg"><LogOut className="size-4" aria-hidden="true" />Sign out</button>
        </div>
      )}
    </div>
  )
}

function TopBar() {
  const unread = useQuery({ queryKey: ['notifications', 'unread'], queryFn: unreadCount, refetchInterval: 60_000, staleTime: 30_000 })
  return (
    <div className="sticky top-0 z-20 flex items-center gap-2 border-b border-line bg-white/95 px-4 py-2 backdrop-blur sm:px-6 lg:px-10">
      <GlobalSearch />
      <div className="ml-auto flex items-center">
        <Link to="/admin/notifications" aria-label={unread.data ? `Notifications, ${unread.data} unread` : 'Notifications'} className="relative grid size-11 place-items-center rounded-control hover:bg-pale">
          <Bell className="size-5" aria-hidden="true" />
          {unread.data ? <span className="absolute right-1.5 top-1.5 grid min-w-4 place-items-center rounded-full bg-danger px-1 text-[0.65rem] font-bold leading-4 text-white">{unread.data > 99 ? '99+' : unread.data}</span> : null}
        </Link>
        <ProfileMenu />
      </div>
    </div>
  )
}

export function AdminLayout() {
  const counts = useQuery({ queryKey: ['admin-counts'], queryFn: adminCounts, refetchInterval: 60_000, staleTime: 30_000 })
  const groups: NavGroup[] = useMemo(() => ADMIN_NAV.map((g) => ({
    ...g, items: g.items.map((i) => { const key = BADGES[i.to]; const n = key ? counts.data?.[key] : undefined; return n ? { ...i, badge: n } : i }),
  })), [counts.data])
  return <DashboardLayout base="/admin" areaLabel="Administration" groups={groups} topBar={<TopBar />} foldable />
}
