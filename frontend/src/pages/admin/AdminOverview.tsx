import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { QueryBoundary, Section, Stat } from '@/components/kit'
import { PageHeader } from '@/components/ui'
import { formatMoney } from '@/lib/format'
import { DELIVERY_STATUS, label, ORDER_STATUS } from '@/lib/labels'
import { adminOverview } from '@/services/ops'

const link = (to: string, text: string) => <Link className="mt-1 inline-block text-sm font-semibold text-forest underline" to={to}>{text}</Link>

export default function AdminOverview() {
  const q = useQuery({ queryKey: ['admin-overview'], queryFn: adminOverview, refetchInterval: 60_000 })
  const d = q.data
  return (
    <>
      <PageHeader title="Overview" subtitle={d ? `Last ${d.window_days} days` : undefined} />
      <QueryBoundary query={q} skeleton="detail">
        {d && (
          <div className="space-y-8">
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <Stat label="Orders" value={d.orders.total} to={link('/admin/orders', 'View orders')} />
              <Stat label="Delivered value" value={formatMoney(d.orders.delivered_value)} hint="Completed orders only" />
              <Stat label="Deliveries needing attention" value={d.deliveries.needs_attention} to={link('/admin/deliveries?needs_attention=1', 'Review')} />
              <Stat label="Partners online" value={d.deliveries.partners_online} />
              <Stat label="Partner applications" value={d.deliveries.partners_pending} to={link('/admin/partners?status=PENDING', 'Review')} />
              <Stat label="Stores awaiting approval" value={d.stores.pending} to={link('/admin/stores?status=PENDING', 'Review')} />
              <Stat label="Open tickets" value={d.support.open_tickets} to={link('/admin/support/tickets', 'Open queue')} />
              <Stat label="Open complaints" value={d.support.open_complaints} to={link('/admin/support/complaints', 'Open queue')} />
            </div>
            <div className="grid gap-6 md:grid-cols-2">
              <Section title="Orders by status"><Breakdown data={d.orders.by_status} map={ORDER_STATUS} /></Section>
              <Section title="Deliveries by status"><Breakdown data={d.deliveries.by_status} map={DELIVERY_STATUS} /></Section>
            </div>
            <p className="text-sm text-muted">{d.stores.active} active stores · average store rating {d.stores.average_rating || '—'}</p>
          </div>
        )}
      </QueryBoundary>
    </>
  )
}

function Breakdown({ data, map }: { data: Record<string, number>; map: Record<string, string> }) {
  const rows = Object.entries(data)
  if (!rows.length) return <p className="text-sm text-muted">No data in this period.</p>
  const max = Math.max(...rows.map(([, n]) => n))
  return (
    <ul className="space-y-2">
      {rows.map(([k, n]) => (
        <li key={k} className="text-sm"><div className="flex justify-between"><span>{label(map, k)}</span><strong className="tabular-nums">{n}</strong></div>
          <div className="mt-1 h-2 rounded-full bg-canvas" aria-hidden="true"><div className="h-2 rounded-full bg-emerald" style={{ width: `${Math.max(4, (n / max) * 100)}%` }} /></div></li>
      ))}
    </ul>
  )
}
