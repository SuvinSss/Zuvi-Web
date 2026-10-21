import { useQuery } from '@tanstack/react-query'
import { ShoppingBag } from 'lucide-react'
import { Link, useNavigate } from 'react-router-dom'
import { DataTable, Pagination, QueryBoundary, Segmented, Status } from '@/components/kit'
import { PageHeader, ButtonLink } from '@/components/ui'
import { useUrlState } from '@/hooks/useUrlState'
import { formatDate, formatMoney } from '@/lib/format'
import { label, ORDER_STATUS } from '@/lib/labels'
import { listOrders } from '@/services/platform'

const FILTERS = [['', 'All'], ['PLACED', 'Placed'], ['CONFIRMED', 'Confirmed'], ['IN_PROGRESS', 'In progress'], ['COMPLETED', 'Delivered'], ['CANCELLED', 'Cancelled']] as const

export default function OrdersPage() {
  const navigate = useNavigate()
  const { values, page, set } = useUrlState(['status'] as const)
  const orders = useQuery({ queryKey: ['orders', values.status, page], queryFn: () => listOrders({ status: values.status, page }), placeholderData: (p) => p })
  return (
    <>
      <PageHeader title="My orders" />
      <div className="mb-4"><Segmented label="Filter by status" value={values.status} onChange={(v) => set({ status: v })} options={FILTERS.map(([value, l]) => ({ value, label: l }))} /></div>
      <QueryBoundary query={orders} isEmpty={orders.data?.count === 0}
        empty={{ icon: ShoppingBag, title: values.status ? 'No orders with this status' : 'No orders yet', text: values.status ? 'Try another filter.' : 'When you place an order it will appear here.', action: values.status ? undefined : <ButtonLink to="/shop">Start shopping</ButtonLink> }}>
        <DataTable caption="Orders" rows={orders.data?.results ?? []} rowKey={(o) => o.id} onRowClick={(o) => navigate(`/account/orders/${o.id}`)}
          columns={[
            { key: 'n', header: 'Order', primary: true, cell: (o) => <Link to={`/account/orders/${o.id}`} className="inline-flex min-h-11 items-center font-semibold text-forest hover:underline" onClick={(e) => e.stopPropagation()}>{o.order_number}</Link> },
            { key: 'd', header: 'Placed', cell: (o) => formatDate(o.placed_at) },
            { key: 's', header: 'Status', cell: (o) => <Status value={o.status} label={label(ORDER_STATUS, o.status)} /> },
            { key: 't', header: 'Total', className: 'text-right tabular-nums', cell: (o) => formatMoney(o.grand_total) },
          ]} />
        <Pagination page={page} count={orders.data?.count ?? 0} onPage={(n) => set({ page: n })} />
      </QueryBoundary>
    </>
  )
}
