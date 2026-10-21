import { useQuery } from '@tanstack/react-query'
import { Bell, Home, LifeBuoy, LogIn, Package, Search, ShoppingBag, Store, User } from 'lucide-react'
import { useId, useState, type FormEvent } from 'react'
import { Link, NavLink, Outlet, useNavigate, useSearchParams } from 'react-router-dom'
import { Logo } from '@/components/Logo'
import { useAuth } from '@/features/auth/AuthProvider'
import { homePath } from '@/lib/roles'
import { getCart, unreadCount } from '@/services/platform'

function SearchBox({ className = '' }: { className?: string }) {
  const id = useId()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const [text, setText] = useState(params.get('q') ?? '')
  const submit = (event: FormEvent) => {
    event.preventDefault()
    navigate(text.trim() ? `/shop?q=${encodeURIComponent(text.trim())}` : '/shop')
  }
  return (
    <form role="search" onSubmit={submit} className={`relative ${className}`}>
      <label htmlFor={id} className="sr-only">Search products</label>
      <Search className="pointer-events-none absolute left-3 top-1/2 size-5 -translate-y-1/2 text-muted" aria-hidden="true" />
      <input id={id} type="search" value={text} onChange={(e) => setText(e.target.value)} placeholder="Search groceries, snacks, household…"
        className="min-h-11 w-full rounded-full border border-line bg-white pl-10 pr-4 text-base placeholder:text-muted/70 focus:border-emerald focus:outline-none focus:ring-2 focus:ring-emerald/30 sm:text-sm" />
    </form>
  )
}

function useCartCount() {
  const { user } = useAuth()
  const isCustomer = user?.role === 'CUSTOMER'
  const query = useQuery({ queryKey: ['cart'], queryFn: getCart, enabled: isCustomer, staleTime: 15_000 })
  return query.data?.item_count ?? 0
}

export function PublicLayout() {
  const { user, status } = useAuth()
  const cartCount = useCartCount()
  const isCustomer = user?.role === 'CUSTOMER'
  const unread = useQuery({ queryKey: ['notifications', 'unread'], queryFn: unreadCount, enabled: isCustomer, staleTime: 30_000 })
  const link = 'rounded-control px-3 py-2 text-sm font-medium text-ink hover:bg-pale'
  const active = ({ isActive }: { isActive: boolean }) => `${link} ${isActive ? 'bg-pale text-forest' : ''}`

  const tabs = [
    { to: '/', label: 'Home', icon: Home, end: true },
    { to: '/shop', label: 'Shop', icon: Package },
    { to: '/stores', label: 'Stores', icon: Store },
    ...(isCustomer
      ? [{ to: '/cart', label: 'Cart', icon: ShoppingBag, badge: cartCount }, { to: '/account', label: 'Account', icon: User }]
      : [{ to: '/help', label: 'Help', icon: LifeBuoy }, { to: '/login', label: 'Sign in', icon: LogIn }]),
  ]

  return (
    <div className="flex min-h-dvh flex-col">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded-control focus:bg-white focus:px-4 focus:py-2 focus:shadow-pop">Skip to content</a>
      <header className="sticky top-0 z-30 border-b border-line bg-white/95 pt-[env(safe-area-inset-top)] backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center gap-3 px-4 py-2 sm:px-6">
          <Link to="/" aria-label="Zuvi home"><Logo variant="light" className="w-24 sm:w-28" /></Link>
          <SearchBox className="hidden flex-1 md:block" />
          <nav aria-label="Main" className="ml-auto hidden items-center gap-1 lg:flex">
            <NavLink to="/shop" className={active}>Shop</NavLink>
            <NavLink to="/stores" className={active}>Stores</NavLink>
            <NavLink to="/help" className={active}>Help</NavLink>
          </nav>
          <div className="ml-auto flex items-center gap-1 md:ml-0">
            {isCustomer && (
              <>
                <Link to="/account/notifications" aria-label={unread.data ? `Notifications, ${unread.data} unread` : 'Notifications'} className="relative hidden size-11 place-items-center rounded-control hover:bg-pale sm:grid">
                  <Bell className="size-5" aria-hidden="true" />
                  {unread.data ? <span className="absolute right-1.5 top-1.5 grid min-w-4 place-items-center rounded-full bg-danger px-1 text-[0.65rem] font-bold leading-4 text-white">{unread.data}</span> : null}
                </Link>
                <Link to="/cart" aria-label={`Cart, ${cartCount} item${cartCount === 1 ? '' : 's'}`} className="relative hidden size-11 place-items-center rounded-control hover:bg-pale lg:grid">
                  <ShoppingBag className="size-5" aria-hidden="true" />
                  {cartCount > 0 && <span className="absolute right-1 top-1 grid min-w-4 place-items-center rounded-full bg-forest px-1 text-[0.65rem] font-bold leading-4 text-white">{cartCount}</span>}
                </Link>
                <Link to="/account" className="hidden min-h-11 items-center gap-2 rounded-control px-3 text-sm font-medium hover:bg-pale lg:flex"><User className="size-5" aria-hidden="true" />{user?.first_name || 'Account'}</Link>
              </>
            )}
            {!isCustomer && status !== 'loading' && (
              user ? (
                <Link to={homePath(user)} className="inline-flex min-h-11 items-center rounded-control bg-forest px-4 text-sm font-semibold text-white hover:bg-deep">My dashboard</Link>
              ) : (
                <>
                  <Link to="/login" className="hidden min-h-11 items-center rounded-control px-3 text-sm font-semibold text-forest hover:bg-pale sm:inline-flex">Sign in</Link>
                  <Link to="/register" className="inline-flex min-h-11 items-center rounded-control bg-forest px-4 text-sm font-semibold text-white hover:bg-deep">Join</Link>
                </>
              )
            )}
          </div>
        </div>
        <div className="px-4 pb-2 md:hidden"><SearchBox /></div>
      </header>

      <main id="main" tabIndex={-1} className="mx-auto w-full min-w-0 max-w-6xl flex-1 px-4 py-6 pb-24 sm:px-6 lg:pb-10"><Outlet /></main>

      <footer className="border-t border-line bg-white pb-20 lg:pb-0">
        <div className="mx-auto grid max-w-6xl gap-6 px-4 py-8 text-sm sm:grid-cols-3 sm:px-6">
          <div><Logo variant="light" className="w-24" /><p className="mt-2 max-w-xs text-muted">Groceries and essentials from local stores, delivered by local delivery partners.</p></div>
          <nav aria-label="Footer" className="flex flex-col gap-1.5">
            <p className="font-semibold text-forest">Shop</p>
            <Link to="/shop" className="inline-flex min-h-11 items-center text-muted hover:text-forest">All products</Link>
            <Link to="/stores" className="inline-flex min-h-11 items-center text-muted hover:text-forest">Stores</Link>
            <Link to="/register-partner" className="inline-flex min-h-11 items-center text-muted hover:text-forest">Deliver with us</Link>
          </nav>
          <nav aria-label="Support" className="flex flex-col gap-1.5">
            <p className="font-semibold text-forest">Help</p>
            <Link to="/help" className="inline-flex min-h-11 items-center text-muted hover:text-forest">Help &amp; support</Link>
            <Link to="/account/support" className="inline-flex min-h-11 items-center text-muted hover:text-forest">My tickets &amp; complaints</Link>
            <Link to="/account/feedback" className="inline-flex min-h-11 items-center text-muted hover:text-forest">Send feedback</Link>
          </nav>
        </div>
      </footer>

      <nav aria-label="Quick navigation" className="fixed inset-x-0 bottom-0 z-30 grid border-t border-line bg-white pb-[env(safe-area-inset-bottom)] shadow-pop lg:hidden" style={{ gridTemplateColumns: `repeat(${tabs.length}, minmax(0, 1fr))` }}>
        {tabs.map(({ to, label, icon: Icon, end, ...rest }) => (
          <NavLink key={to} to={to} end={end} className={({ isActive }) => `relative flex min-h-14 flex-col items-center justify-center gap-0.5 text-xs font-medium ${isActive ? 'text-forest' : 'text-muted'}`}>
            {({ isActive }) => (
              <>
                <Icon className={`size-6 ${isActive ? 'text-emerald' : ''}`} aria-hidden="true" />
                {label}
                {'badge' in rest && rest.badge ? <span className="absolute right-[calc(50%-1.6rem)] top-1 grid min-w-4 place-items-center rounded-full bg-forest px-1 text-[0.65rem] font-bold leading-4 text-white">{rest.badge}</span> : null}
              </>
            )}
          </NavLink>
        ))}
      </nav>
    </div>
  )
}
