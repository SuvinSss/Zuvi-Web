import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, ClipboardList, Package, Star } from 'lucide-react'
import { Link } from 'react-router-dom'
import { QueryBoundary, Section, Stat } from '@/components/kit'
import { Alert, PageHeader } from '@/components/ui'
import { label, STORE_ORDER_STATUS } from '@/lib/labels'
import { storeMe } from '@/services/ops'

export default function StoreDashboard() {
  const q = useQuery({ queryKey: ['store-me'], queryFn: storeMe })
  const d = q.data
  return (
    <>
      <PageHeader title={d ? d.store.name : 'Store dashboard'} subtitle={d ? `Store code ${d.store.code}` : undefined} />
      <QueryBoundary query={q} skeleton="detail">
        {d && (
          <div className="space-y-6">
            {d.store.status !== 'ACTIVE' && <Alert tone="warn" title={`Your store is ${d.store.status.toLowerCase()}`}>Customers cannot order from your store until it is active. Contact Zuuvi support if you have questions.</Alert>}
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <Stat label="Waiting for you" value={d.orders_by_status.PENDING ?? 0} to={<Link className="mt-1 inline-flex min-h-11 items-center inline-flex min-h-11 items-center text-sm font-semibold text-forest underline" to="/store/orders?status=PENDING">Review orders</Link>} />
              <Stat label="Being prepared" value={(d.orders_by_status.ACCEPTED ?? 0) + (d.orders_by_status.PREPARING ?? 0)} />
              <Stat label="Low stock" value={d.low_stock_products} to={<Link className="mt-1 inline-flex min-h-11 items-center inline-flex min-h-11 items-center text-sm font-semibold text-forest underline" to="/store/stock?low_stock=1">View products</Link>} />
              <Stat label="Rating" value={d.rating?.count ? `${Number(d.rating.average).toFixed(1)} ★` : '—'} hint={d.rating?.count ? `${d.rating.count} reviews` : 'No reviews yet'} />
            </div>
            <Section title="Orders by status">
              {Object.keys(d.orders_by_status).length === 0 ? <p className="text-sm text-muted">No orders yet.</p> : (
                <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                  {Object.entries(d.orders_by_status).map(([s, n]) => <li key={s}><Link to={`/store/orders?status=${s}`} className="flex min-h-12 items-center justify-between rounded-card border border-line bg-white px-4 shadow-card hover:bg-pale"><span>{label(STORE_ORDER_STATUS, s)}</span><strong className="tabular-nums">{n}</strong></Link></li>)}
                </ul>
              )}
            </Section>
            <div className="grid gap-3 sm:grid-cols-3">
              {[['/store/orders', ClipboardList, 'Manage orders'], ['/store/products', Package, 'Manage products'], ['/store/reviews', Star, 'Customer reviews']].map(([to, I, text]) => {
                const Icon = I as typeof Star
                return <Link key={to as string} to={to as string} className="flex min-h-14 items-center gap-3 rounded-card border border-line bg-white p-4 font-semibold text-forest shadow-card hover:bg-pale"><Icon className="size-5" aria-hidden="true" />{text as string}</Link>
              })}
            </div>
            {d.low_stock_products > 0 && <p className="flex items-center gap-2 text-sm text-warn"><AlertTriangle className="size-4" aria-hidden="true" />{d.low_stock_products} product(s) are at or below their low-stock level.</p>}
          </div>
        )}
      </QueryBoundary>
    </>
  )
}
