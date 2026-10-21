import { useQuery } from '@tanstack/react-query'
import { Wallet } from 'lucide-react'
import { QueryBoundary } from '@/components/kit'
import { Card, PageHeader } from '@/components/ui'
import { formatDateTime, formatMoney } from '@/lib/format'
import { myEarnings } from '@/services/delivery'

const PARTS: Record<string, string> = { rider_per_order: 'Per order', rider_per_km: 'Distance pay', rider_fixed_share: 'Share of daily pay' }

export default function EarningsPage() {
  const q = useQuery({ queryKey: ['my-earnings'], queryFn: myEarnings })
  const s = q.data?.summary
  return (
    <>
      <PageHeader title="Earnings" subtitle="Every completed delivery and paid failed attempt. Amounts are set by Zuuvi's pay rules and can't be edited here." />
      <QueryBoundary query={q} isEmpty={q.data?.results.length === 0} empty={{ icon: Wallet, title: 'No earnings yet', text: 'Complete a delivery to see your pay here.' }}>
        {s && (
          <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[['Today', s.today], ['Waiting to be paid', s.unpaid], ['All time', s.total], ['Deliveries', s.deliveries]].map(([l, v]) => (
              <Card key={l} className="p-3"><p className="text-xs text-muted">{l}</p><p className="text-xl font-semibold tabular-nums text-forest">{l === 'Deliveries' ? v : formatMoney(v)}</p></Card>
            ))}
          </div>
        )}
        <ul className="space-y-2">{q.data?.results.map((e) => (
          <li key={e.id}><Card className="p-3 text-sm">
            <div className="flex items-baseline justify-between gap-2"><span className="font-semibold">{e.kind_label}</span><span className="text-base font-semibold tabular-nums">{formatMoney(e.amount)}</span></div>
            <p className="text-xs text-muted">{e.store_order ?? ''} · {formatDateTime(e.created_at)} · {e.status === 'PAID' ? `Paid ${e.paid_at ? formatDateTime(e.paid_at) : ''}` : 'Not paid yet'}</p>
            {Object.entries(e.breakdown).filter(([k]) => k in PARTS && Number(e.breakdown[k]) > 0).length > 0 && (
              <p className="mt-1 text-xs text-muted">{Object.entries(e.breakdown).filter(([k]) => k in PARTS && Number(e.breakdown[k]) > 0).map(([k, v]) => `${PARTS[k]} ₹${Number(v).toFixed(2)}`).join(' + ')}{e.breakdown.distance_km ? ` · ${Number(e.breakdown.distance_km).toFixed(1)} km` : ''}</p>
            )}
          </Card></li>))}</ul>
      </QueryBoundary>
    </>
  )
}
