import { useQuery } from '@tanstack/react-query'
import { ClipboardList } from 'lucide-react'
import { Link, useNavigate } from 'react-router-dom'
import { DataTable, Pagination, QueryBoundary, Segmented, Status } from '@/components/kit'
import { Input, PageHeader } from '@/components/ui'
import { useUrlState } from '@/hooks/useUrlState'
import { formatMoney } from '@/lib/format'
import { label, PAYMENT_METHOD, STORE_ORDER_STATUS } from '@/lib/labels'
import { listStoreOrders } from '@/services/ops'

const FILTERS = ['', 'PENDING', 'ACCEPTED', 'PREPARING', 'READY', 'COMPLETED', 'CANCELLED', 'REJECTED']

export default function StoreOrders() {
  const navigate = useNavigate()
  const { values, page, set } = useUrlState(['status', 'q'] as const)
  const q = useQuery({ queryKey: ['store-orders', values, page], queryFn: () => listStoreOrders({ ...values, page }), placeholderData: (p) => p, refetchInterval: 60_000 })
  return (
    <>
      <PageHeader title="Orders" />
      <div className="mb-4 space-y-3">
        <Segmented label="Filter by status" value={values.status} onChange={(v) => set({ status: v })} options={FILTERS.map((f) => ({ value: f, label: f ? label(STORE_ORDER_STATUS, f) : 'All' }))} />
        <label className="block max-w-sm text-sm">Search<Input className="mt-1" type="search" defaultValue={values.q} placeholder="Order number" onKeyDown={(e) => e.key === 'Enter' && set({ q: e.currentTarget.value })} onBlur={(e) => e.target.value !== values.q && set({ q: e.target.value })} /></label>
      </div>
      <QueryBoundary query={q} isEmpty={q.data?.count === 0} empty={{ icon: ClipboardList, title: 'No orders found', text: 'New orders appear here as customers place them.' }}>
        <DataTable caption="Store orders" rows={q.data?.results ?? []} rowKey={(o) => o.id} onRowClick={(o) => navigate(`/store/orders/${o.id}`)}
          columns={[
            { key: 'n', header: 'Order', primary: true, cell: (o) => <Link to={`/store/orders/${o.id}`} className="inline-flex min-h-11 items-center font-semibold text-forest hover:underline" onClick={(e) => e.stopPropagation()}>{o.store_order_number}</Link> },
            { key: 'c', header: 'Customer', cell: (o) => o.recipient_first_name },
            { key: 't', header: 'Type', cell: (o) => (o.fulfillment_type === 'PICKUP' ? 'Pickup' : 'Delivery') },
            { key: 'p', header: 'Payment', cell: (o) => label(PAYMENT_METHOD, o.payment_method) },
            { key: 's', header: 'Status', cell: (o) => <Status value={o.status} label={label(STORE_ORDER_STATUS, o.status)} /> },
            { key: 'a', header: 'Total', className: 'text-right tabular-nums', cell: (o) => formatMoney(o.store_total) },
            { key: 'd', header: 'Placed', cell: (o) => new Date(o.created_at).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' }) },
          ]} />
        <Pagination page={page} count={q.data?.count ?? 0} onPage={(n) => set({ page: n })} />
      </QueryBoundary>
    </>
  )
}
