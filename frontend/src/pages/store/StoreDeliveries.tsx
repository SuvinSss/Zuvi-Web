import { useQuery } from '@tanstack/react-query'
import { Truck } from 'lucide-react'
import { Link } from 'react-router-dom'
import { DataTable, Pagination, QueryBoundary, Segmented, Status } from '@/components/kit'
import { PageHeader } from '@/components/ui'
import { useUrlState } from '@/hooks/useUrlState'
import { label } from '@/lib/labels'
import { listStoreDeliveries } from '@/services/ops'

const STORE_DELIVERY_STATUS: Record<string, string> = {
  PENDING_ASSIGNMENT: 'Finding a partner', OFFERED: 'Offered to a partner', ACCEPTED: 'Partner on the way to you', AT_STORE: 'Partner at your store',
  IN_TRANSIT: 'Out for delivery', ARRIVED: 'At the customer', DELIVERED: 'Delivered', FAILED: 'Delivery failed', CANCELLED: 'Cancelled',
}
export default function StoreDeliveries() {
  const { values, page, set } = useUrlState(['status'] as const)
  const q = useQuery({ queryKey: ['store-deliveries', values.status, page], queryFn: () => listStoreDeliveries({ status: values.status, page }), placeholderData: (p) => p, refetchInterval: 30_000 })
  return (
    <>
      <PageHeader title="Deliveries" subtitle="Hand orders to the partner and review pickup proof from each order." />
      <div className="mb-4"><Segmented label="Status" value={values.status} onChange={(v) => set({ status: v })} options={[{ value: '', label: 'All' }, { value: 'ACCEPTED', label: 'Awaiting pickup' }, { value: 'AT_STORE', label: 'At store' }, { value: 'IN_TRANSIT', label: 'On the way' }, { value: 'DELIVERED', label: 'Delivered' }, { value: 'FAILED', label: 'Failed' }]} /></div>
      <QueryBoundary query={q} isEmpty={q.data?.count === 0} empty={{ icon: Truck, title: 'No deliveries', text: 'A delivery starts when you mark a delivery order ready.' }}>
        <DataTable caption="Deliveries" rows={q.data?.results ?? []} rowKey={(d) => d.id}
          columns={[
            { key: 'o', header: 'Order', primary: true, cell: (d) => d.store_order_number },
            { key: 's', header: 'Status', cell: (d) => <Status value={d.status} label={label(STORE_DELIVERY_STATUS, d.status)} /> },
            { key: 'p', header: 'Partner', cell: (d) => d.partner?.name ?? 'Not assigned' },
            { key: 'v', header: 'Vehicle', cell: (d) => (d.partner ? label({}, d.partner.vehicle_type) : '—') },
            { key: 'a', header: '', cell: (d) => <Link className="font-semibold text-forest underline" to={`/store/orders?q=${encodeURIComponent(d.store_order_number)}`}>Open order</Link> },
          ]} />
        <Pagination page={page} count={q.data?.count ?? 0} onPage={(n) => set({ page: n })} />
      </QueryBoundary>
    </>
  )
}
