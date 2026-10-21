import { useQuery } from '@tanstack/react-query'
import { RefreshCw } from 'lucide-react'
import { Link } from 'react-router-dom'
import { BarList, TrendChart } from '@/components/charts'
import { QueryBoundary, Section, Status } from '@/components/kit'
import { Button, Card, PageHeader } from '@/components/ui'
import { useAuth } from '@/features/auth/AuthProvider'
import { formatDate, formatMoney } from '@/lib/format'
import { label, ORDER_STATUS } from '@/lib/labels'
import { adminDashboard } from '@/services/ops'
import { KpiCard, PeriodPicker, usePeriod } from './dashboardParts'

const more = (to: string, text = 'View all') => <Link className="inline-flex min-h-11 items-center text-sm font-semibold text-forest underline" to={to}>{text}</Link>
const when = (iso: string) => new Date(iso).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' })

export default function AdminOverview() {
  const { user } = useAuth()
  const period = usePeriod()
  const { from, to, invalid } = period
  const q = useQuery({ queryKey: ['admin-dashboard', from, to], queryFn: () => adminDashboard({ from, to }), enabled: !invalid, refetchInterval: 60_000, placeholderData: (p) => p })
  const d = q.data
  const range = `from=${from}&to=${to}`
  return (
    <>
      <PageHeader
        title={`Welcome back${user?.first_name ? `, ${user.first_name}` : ''}`}
        subtitle={new Date().toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })}
        actions={<Button variant="outline" icon={RefreshCw} loading={q.isFetching} onClick={() => void q.refetch()}>Refresh</Button>}
      />
      <div className="mb-6"><PeriodPicker period={period} /></div>
      <QueryBoundary query={invalid ? { isPending: false, isError: false, refetch: () => undefined, error: null } : q} skeleton="cards">
        {d && (
          <div className="space-y-8">
            <div>
              <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted">Right now</h2>
              <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                <KpiCard label="Awaiting confirmation" value={d.live.orders_awaiting_confirmation} to="/admin/orders?status=PLACED" attention={d.live.orders_awaiting_confirmation > 0} />
                <KpiCard label="Being prepared" value={d.live.orders_being_prepared} hint="Accepted or preparing at the store" />
                <KpiCard label="Awaiting delivery" value={d.live.orders_awaiting_delivery} to="/admin/deliveries?status=PENDING_ASSIGNMENT" hint="Ready, waiting for a partner or pickup" />
                <KpiCard label="In transit" value={d.live.orders_in_transit} to="/admin/deliveries?status=IN_TRANSIT" />
                <KpiCard label="Deliveries needing attention" value={d.live.deliveries_needing_attention} to="/admin/deliveries?needs_attention=1" attention={d.live.deliveries_needing_attention > 0} />
                <KpiCard label="Open tickets" value={d.live.tickets_open} to="/admin/support/tickets" attention={d.live.tickets_open > 0} />
                <KpiCard label="Unresolved complaints" value={d.live.complaints_open} to="/admin/support/complaints" attention={d.live.complaints_open > 0} />
                <KpiCard label="Partners online" value={d.live.partners_online} hint={`${d.live.partners_active} approved`} to="/admin/partners?status=APPROVED" />
              </div>
            </div>

            <div>
              <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted">{formatDate(d.range.from)} – {formatDate(d.range.to)}</h2>
              <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                <KpiCard label="Orders placed" value={d.kpis.orders.value} kpi={d.kpis.orders} to={`/admin/orders?${range}`} />
                <KpiCard label="Delivered" value={d.kpis.delivered.value} kpi={d.kpis.delivered} to={`/admin/orders?status=COMPLETED&${range}`} />
                <KpiCard label="Delivered order value" value={formatMoney(d.kpis.revenue.value)} kpi={d.kpis.revenue} hint="Orders delivered in the period" />
                <KpiCard label="Cancelled" value={d.kpis.cancelled.value} kpi={d.kpis.cancelled} to={`/admin/orders?status=CANCELLED&${range}`} />
                <KpiCard label="New customers" value={d.kpis.new_customers.value} kpi={d.kpis.new_customers} to={`/admin/customers?${range}`} />
                <KpiCard label="Total customers" value={d.live.customers_total} to="/admin/customers" />
                <KpiCard label="Active stores" value={d.live.stores_active} to="/admin/stores?status=ACTIVE" />
                <KpiCard label="Products" value={d.live.products_total} hint={`${d.live.products_active} live`} to="/admin/products" />
              </div>
            </div>

            <div className="grid gap-6 lg:grid-cols-2">
              <Card className="p-4"><Section title="Orders over time"><TrendChart title="Orders placed per day" points={d.series.map((s) => ({ label: s.date, value: s.orders }))} kind="bar" /></Section></Card>
              <Card className="p-4"><Section title="Delivered value over time"><TrendChart title="Delivered order value per day" points={d.series.map((s) => ({ label: s.date, value: Number(s.revenue) }))} format={(n) => formatMoney(n)} /></Section></Card>
              <Card className="p-4"><Section title="Order status" actions={more(`/admin/orders?${range}`)}><BarList rows={d.status_distribution.map((r) => ({ key: r.status, label: label(ORDER_STATUS, r.status), value: r.count }))} /></Section></Card>
              <Card className="p-4"><Section title="Top stores" actions={more('/admin/reports', 'Reports')}>
                <BarList empty="No delivered orders in this period." rows={d.top_stores.map((s) => ({ key: String(s.store_id), label: s.name, value: Number(s.revenue), display: formatMoney(s.revenue), hint: `${s.orders} delivered order${s.orders === 1 ? '' : 's'}` }))} /></Section></Card>
            </div>

            <div className="grid gap-6 lg:grid-cols-2">
              <Section title="Recent orders" actions={more('/admin/orders')}>
                <Card className="divide-y divide-line">
                  {d.queues.recent_orders.length === 0 ? <p className="p-4 text-sm text-muted">No orders yet.</p> : d.queues.recent_orders.map((o) => (
                    <Link key={o.id} to={`/admin/orders/${o.id}`} className="flex min-h-14 items-center justify-between gap-3 px-4 py-2 text-sm hover:bg-pale/50">
                      <span className="min-w-0"><strong>{o.order_number}</strong><br /><span className="text-xs text-muted">{o.customer} · {when(o.placed_at)}</span></span>
                      <span className="flex shrink-0 flex-col items-end gap-1"><Status value={o.status} label={label(ORDER_STATUS, o.status)} /><span className="tabular-nums">{formatMoney(o.grand_total)}</span></span>
                    </Link>
                  ))}
                </Card>
              </Section>
              <Section title="Needs attention">
                <Card className="divide-y divide-line">
                  {d.queues.needs_attention.orders_unconfirmed_15_min.map((o) => <Link key={`o${o.id}`} to={`/admin/orders/${o.id}`} className="block min-h-11 px-4 py-3 text-sm hover:bg-pale/50"><strong>{o.order_number}</strong> has waited over 15 minutes for confirmation <span className="text-muted">(placed {when(o.placed_at)})</span></Link>)}
                  {d.queues.needs_attention.deliveries.map((x) => <Link key={`d${x.id}`} to={`/admin/deliveries/${x.id}`} className="block min-h-11 px-4 py-3 text-sm hover:bg-pale/50">Delivery for <strong>{x.store_order__store_order_number}</strong> needs a decision</Link>)}
                  {d.queues.needs_attention.orders_unconfirmed_15_min.length + d.queues.needs_attention.deliveries.length === 0 && <p className="p-4 text-sm text-muted">Nothing is waiting on you.</p>}
                </Card>
              </Section>
              <Section title="Onboarding requests">
                <Card className="divide-y divide-line">
                  {d.queues.pending_stores.map((s) => <Link key={`s${s.id}`} to="/admin/stores?status=PENDING" className="block min-h-11 px-4 py-3 text-sm hover:bg-pale/50">Store <strong>{s.name}</strong> <span className="text-muted">· {formatDate(s.created_at)}</span></Link>)}
                  {d.queues.pending_partners.map((p) => <Link key={`p${p.id}`} to="/admin/partners?status=PENDING" className="block min-h-11 px-4 py-3 text-sm hover:bg-pale/50">Delivery partner <strong>{p.username}</strong> <span className="text-muted">· {formatDate(p.created_at)}</span></Link>)}
                  {d.queues.pending_stores.length + d.queues.pending_partners.length === 0 && <p className="p-4 text-sm text-muted">No applications are waiting.</p>}
                </Card>
              </Section>
              <Section title="New customers" actions={more('/admin/customers')}>
                <Card className="divide-y divide-line">
                  {d.queues.new_customers.length === 0 ? <p className="p-4 text-sm text-muted">No customers yet.</p> : d.queues.new_customers.map((c) => (
                    <Link key={c.id} to={`/admin/customers/${c.id}`} className="flex min-h-11 items-center justify-between gap-3 px-4 py-3 text-sm hover:bg-pale/50"><strong>{c.username}</strong><span className="text-muted">{formatDate(c.created_at)}</span></Link>
                  ))}
                </Card>
              </Section>
              <Section title="Pending complaints" actions={more('/admin/support/complaints')}>
                <Card className="divide-y divide-line">
                  {d.queues.pending_complaints.length === 0 ? <p className="p-4 text-sm text-muted">No unresolved complaints.</p> : d.queues.pending_complaints.map((c) => (
                    <Link key={c.id} to={`/admin/support/complaints/${c.id}`} className="flex min-h-11 items-center justify-between gap-3 px-4 py-3 text-sm hover:bg-pale/50"><strong>{c.reference}</strong><span className="text-muted">{label({}, c.category)} · {label({}, c.severity)}</span></Link>
                  ))}
                </Card>
              </Section>
              <Section title="Recent feedback and reviews" actions={more('/admin/reviews', 'Reviews')}>
                <Card className="divide-y divide-line">
                  {d.queues.recent_reviews.map((r) => <Link key={`r${r.id}`} to="/admin/reviews" className="block min-h-11 px-4 py-3 text-sm hover:bg-pale/50"><span aria-label={`${r.rating} out of 5`}>{'★'.repeat(r.rating)}{'☆'.repeat(5 - r.rating)}</span> <span className="text-muted">{label({}, r.target_type)} review</span>{r.comment ? <span className="block truncate">{r.comment}</span> : null}</Link>)}
                  {d.queues.recent_feedback.map((f) => <Link key={`f${f.id}`} to="/admin/feedback" className="block min-h-11 px-4 py-3 text-sm hover:bg-pale/50"><strong>{f.reference}</strong> <span className="text-muted">{label({}, f.kind)}</span><span className="block truncate">{f.message}</span></Link>)}
                  {d.queues.recent_reviews.length + d.queues.recent_feedback.length === 0 && <p className="p-4 text-sm text-muted">Nothing yet.</p>}
                </Card>
              </Section>
            </div>
            <p className="text-xs text-muted">{d.notes.revenue}</p>
          </div>
        )}
      </QueryBoundary>
    </>
  )
}
