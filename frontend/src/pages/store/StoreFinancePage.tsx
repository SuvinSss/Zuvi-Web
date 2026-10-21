import { useQuery } from '@tanstack/react-query'
import { Wallet } from 'lucide-react'
import { QueryBoundary } from '@/components/kit'
import { Alert, Card, PageHeader } from '@/components/ui'
import { formatDateTime, formatMoney } from '@/lib/format'
import { storeFinance } from '@/services/delivery'

export default function StoreFinancePage() {
  const q = useQuery({ queryKey: ['store-finance'], queryFn: storeFinance })
  const t = q.data?.totals
  return (
    <>
      <PageHeader title="Money" subtitle="What you sold, Zuuvi's commission, offers you fund, and what you are owed." />
      <QueryBoundary query={q} isEmpty={q.data?.orders.length === 0} empty={{ icon: Wallet, title: 'No orders yet', text: 'Your settlement appears here once customers order.' }}>
        {q.data && t && (
          <div className="space-y-4">
            {q.data.location_problems.length > 0 && <Alert tone="warn" title="Customers may not see you for delivery">{q.data.location_problems.map((p) => <p key={p}>{p}</p>)}<p className="mt-1">Contact Zuuvi support to fix your map location or delivery area.</p></Alert>}
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <Card className="p-3"><p className="text-xs text-muted">Items sold</p><p className="text-xl font-semibold tabular-nums">{formatMoney(t.items)}</p></Card>
              <Card className="p-3"><p className="text-xs text-muted">Commission ({Number(q.data.commission_percentage)}%)</p><p className="text-xl font-semibold tabular-nums">−{formatMoney(t.commission)}</p></Card>
              <Card className="p-3"><p className="text-xs text-muted">Offers you funded</p><p className="text-xl font-semibold tabular-nums">−{formatMoney(t.store_promotions)}</p></Card>
              <Card className="p-3"><p className="text-xs text-muted">Your settlement</p><p className="text-xl font-semibold tabular-nums text-forest">{formatMoney(t.settlement)}</p></Card>
            </div>
            <p className="text-sm text-muted">{q.data.note}</p>
            <div className="overflow-x-auto rounded-control ring-1 ring-line">
              <table className="w-full min-w-[40rem] text-sm">
                <caption className="sr-only">Settlement per order</caption>
                <thead className="bg-canvas text-left text-xs text-muted"><tr><th className="p-2">Order</th><th className="p-2 text-right">Items</th><th className="p-2 text-right">Commission</th><th className="p-2 text-right">Your offers</th><th className="p-2 text-right">Settlement</th><th className="p-2 text-right">Delivery (to Zuuvi)</th></tr></thead>
                <tbody className="divide-y divide-line">{q.data.orders.map((o) => (
                  <tr key={o.store_order}><td className="p-2">{o.store_order}<br /><span className="text-xs text-muted">{formatDateTime(o.created_at)}</span></td>
                    <td className="p-2 text-right tabular-nums">{formatMoney(o.items)}</td><td className="p-2 text-right tabular-nums">−{formatMoney(o.commission)}</td>
                    <td className="p-2 text-right tabular-nums">{Number(o.store_funded_promotion) ? `−${formatMoney(o.store_funded_promotion)}` : '—'}</td>
                    <td className="p-2 text-right font-semibold tabular-nums">{formatMoney(o.settlement)}</td><td className="p-2 text-right tabular-nums text-muted">{formatMoney(o.delivery_fee_paid_by_customer)}</td></tr>))}</tbody>
              </table>
            </div>
          </div>
        )}
      </QueryBoundary>
    </>
  )
}
