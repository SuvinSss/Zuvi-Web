import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ClipboardList, Download } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { DataTable, KeyValue, Pagination, QueryBoundary, ReasonDialog, Section, Status, Timeline, useToast } from '@/components/kit'
import { Button, Card, Field, Input, PageHeader, Select } from '@/components/ui'
import { useUrlState } from '@/hooks/useUrlState'
import { errorMessage } from '@/lib/api'
import { formatMoney } from '@/lib/format'
import { DELIVERY_STATUS, label, ORDER_STATUS, PAYMENT_METHOD, PAYMENT_STATUS, STORE_ORDER_STATUS } from '@/lib/labels'
import { adminOrder, adminOrderCancel, adminOrderStatus, adminOrders, downloadOrdersCsv } from '@/services/ops'
import type { OrderDetail } from '@/types/platform'

export function AdminOrdersList() {
  const navigate = useNavigate()
  const { values, page, set } = useUrlState(['status', 'payment_status', 'q', 'from', 'to'] as const)
  const q = useQuery({ queryKey: ['admin-orders', values, page], queryFn: () => adminOrders({ ...values, page }), placeholderData: (p) => p })
  const toast = useToast()
  const exportCsv = useMutation({ mutationFn: () => downloadOrdersCsv(values), onSuccess: () => toast('success', 'Orders exported.'), onError: (e) => toast('error', errorMessage(e)) })
  const filtered = Object.values(values).some(Boolean)
  return (
    <>
      <PageHeader title="Orders" subtitle={q.data ? `${q.data.count} order${q.data.count === 1 ? '' : 's'}${filtered ? ' match the filters' : ''}` : undefined}
        actions={<Button variant="secondary" icon={Download} loading={exportCsv.isPending} onClick={() => exportCsv.mutate()}>Export CSV</Button>} />
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <label className="text-sm">Status<Select className="mt-1" value={values.status} onChange={(e) => set({ status: e.target.value })}><option value="">Any</option>{Object.entries(ORDER_STATUS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</Select></label>
        <label className="text-sm">Payment<Select className="mt-1" value={values.payment_status} onChange={(e) => set({ payment_status: e.target.value })}><option value="">Any</option>{Object.entries(PAYMENT_STATUS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</Select></label>
        <label className="text-sm">From<Input className="mt-1" type="date" value={values.from} onChange={(e) => set({ from: e.target.value })} /></label>
        <label className="text-sm">To<Input className="mt-1" type="date" value={values.to} onChange={(e) => set({ to: e.target.value })} /></label>
        <label className="min-w-[12rem] flex-1 text-sm sm:max-w-xs">Search<Input className="mt-1" type="search" defaultValue={values.q} placeholder="Order, customer or phone" onKeyDown={(e) => e.key === 'Enter' && set({ q: e.currentTarget.value })} onBlur={(e) => e.target.value !== values.q && set({ q: e.target.value })} /></label>
      </div>
      <QueryBoundary query={q} isEmpty={q.data?.count === 0} empty={{ icon: ClipboardList, title: filtered ? 'No orders match these filters' : 'No orders yet', text: filtered ? 'Try clearing a filter.' : undefined, action: filtered ? <Button variant="secondary" onClick={() => set({ status: '', payment_status: '', q: '', from: '', to: '' })}>Reset filters</Button> : undefined }}>
        <DataTable caption="Orders" rows={q.data?.results ?? []} rowKey={(o) => o.id} onRowClick={(o) => navigate(`/admin/orders/${o.id}`)}
          columns={[
            { key: 'n', header: 'Order', primary: true, cell: (o) => <Link className="inline-flex min-h-11 items-center font-semibold text-forest hover:underline" to={`/admin/orders/${o.id}`} onClick={(e) => e.stopPropagation()}>{o.order_number}</Link> },
            { key: 'c', header: 'Customer', cell: (o) => o.customer },
            { key: 's', header: 'Status', cell: (o) => <Status value={o.status} label={label(ORDER_STATUS, o.status)} /> },
            { key: 'p', header: 'Payment', cell: (o) => `${label(PAYMENT_METHOD, o.payment_method)} · ${label(PAYMENT_STATUS, o.payment_status)}` },
            { key: 't', header: 'Total', className: 'text-right tabular-nums', cell: (o) => formatMoney(o.grand_total) },
            { key: 'd', header: 'Placed', cell: (o) => new Date(o.placed_at).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' }) },
          ]} />
        <Pagination page={page} count={q.data?.count ?? 0} onPage={(n) => set({ page: n })} />
      </QueryBoundary>
    </>
  )
}

type AdminOrderDetail = OrderDetail & {
  customer: { id: number; username: string; email: string; phone: string }
  audit_history: { old: string; new: string; by: string | null; reason: string; at: string }[]
  deliveries: { id: number; status: string; attempt: number; needs_attention: boolean }[]
}
const SETTABLE = ['PLACED', 'CONFIRMED', 'IN_PROGRESS', 'COMPLETED']

export function AdminOrderPage() {
  const id = Number(useParams().id)
  const qc = useQueryClient()
  const toast = useToast()
  const q = useQuery({ queryKey: ['admin-order', id], queryFn: () => adminOrder(id) as unknown as Promise<AdminOrderDetail> })
  const [cancelling, setCancelling] = useState(false)
  const [status, setStatus] = useState('')
  const [reason, setReason] = useState('')
  const refresh = () => { void qc.invalidateQueries({ queryKey: ['admin-order', id] }); void qc.invalidateQueries({ queryKey: ['admin-orders'] }) }
  const cancel = useMutation({ mutationFn: (r: string) => adminOrderCancel(id, r), onSuccess: () => { toast('success', 'Order cancelled.'); setCancelling(false); refresh() }, onError: (e) => toast('error', errorMessage(e)) })
  const change = useMutation({ mutationFn: () => adminOrderStatus(id, status, reason), onSuccess: () => { toast('success', 'Status updated.'); setStatus(''); setReason(''); refresh() }, onError: (e) => toast('error', errorMessage(e)) })
  const o = q.data
  return (
    <QueryBoundary query={q} skeleton="detail">
      {o && (
        <>
          <PageHeader title={`Order ${o.order_number}`} subtitle={new Date(o.placed_at).toLocaleString('en-IN')} actions={<Link className="inline-flex min-h-11 items-center text-sm font-semibold text-forest underline" to="/admin/orders">Back to orders</Link>} />
          <div className="grid gap-6 lg:grid-cols-[1fr_22rem]">
            <div className="space-y-6">
              <Card className="p-4"><div className="flex flex-wrap items-center gap-3"><Status value={o.status} label={label(ORDER_STATUS, o.status)} /><span className="text-sm text-muted">{label(PAYMENT_METHOD, o.payment_method)} · {label(PAYMENT_STATUS, o.payment_status)}</span></div>
                {o.cancellation_reason && <p className="mt-2 text-sm">Cancellation reason: {o.cancellation_reason}</p>}</Card>
              {o.store_orders.map((so) => (
                <Section key={so.id} title={`${so.store.name} · ${so.store_order_number}`}>
                  <Card className="p-4"><div className="mb-2"><Status value={so.status} label={label(STORE_ORDER_STATUS, so.status)} /></div>
                    <ul className="divide-y divide-line">{so.items.map((i, k) => <li key={k} className="flex justify-between gap-3 py-2 text-sm"><span>{i.product_name} <span className="text-muted">× {Number(i.quantity)} {i.unit}</span></span><span className="tabular-nums">{formatMoney(i.line_total)}</span></li>)}</ul></Card>
                </Section>
              ))}
              {o.deliveries.length > 0 && <Section title="Deliveries"><Card className="p-4"><ul className="space-y-2">{o.deliveries.map((d) => <li key={d.id} className="flex flex-wrap items-center justify-between gap-2 text-sm"><Link className="font-semibold text-forest underline" to={`/admin/deliveries/${d.id}`}>Delivery #{d.id} (attempt {d.attempt})</Link><span className="flex items-center gap-2">{d.needs_attention && <span className="text-warn">Needs attention</span>}<Status value={d.status} label={label(DELIVERY_STATUS, d.status)} /></span></li>)}</ul></Card></Section>}
              <Section title="Status history"><Card className="p-4"><Timeline items={o.audit_history.map((h, i, a) => ({ key: String(i), title: `${h.old ? label(ORDER_STATUS, h.old) + ' → ' : ''}${label(ORDER_STATUS, h.new)}`, note: `${h.by ?? 'System'}${h.reason ? ` — ${h.reason}` : ''}`, at: h.at, tone: i === a.length - 1 ? 'current' : 'done' }))} /></Card></Section>
            </div>
            <aside className="space-y-4">
              <Card className="p-4"><KeyValue rows={[['Customer', o.customer.username], ['Email', o.customer.email], ['Phone', o.customer.phone], ['Items', formatMoney(o.items_subtotal)], ['Delivery', formatMoney(o.delivery_charge)], ['Total', <strong key="t">{formatMoney(o.grand_total)}</strong>]]} /></Card>
              {o.delivery_address && <Card className="p-4"><address className="text-sm not-italic">{o.delivery_address.recipient_name}<br />{o.delivery_address.line1}, {o.delivery_address.city} {o.delivery_address.postal_code}</address></Card>}
              {!['COMPLETED', 'CANCELLED'].includes(o.status) && (
                <Card className="space-y-3 p-4"><h2 className="font-semibold text-forest">Management actions</h2>
                  <Field label="Set status">{(p) => <Select {...p} value={status} onChange={(e) => setStatus(e.target.value)}><option value="">Choose…</option>{SETTABLE.filter((s) => s !== o.status).map((s) => <option key={s} value={s}>{label(ORDER_STATUS, s)}</option>)}</Select>}</Field>
                  {status && <Field label="Reason">{(p) => <Input {...p} value={reason} onChange={(e) => setReason(e.target.value)} />}</Field>}
                  {status && <Button className="w-full" loading={change.isPending} onClick={() => change.mutate()}>Update status</Button>}
                  {status === 'COMPLETED' && <p className="text-xs text-muted">Orders with an unfinished delivery cannot be completed without delivery proof.</p>}
                  <Button variant="danger" className="w-full" onClick={() => setCancelling(true)}>Cancel order</Button></Card>
              )}
            </aside>
          </div>
          <ReasonDialog open={cancelling} title="Cancel this order?" field="Reason" confirm="Cancel order" danger busy={cancel.isPending} onClose={() => setCancelling(false)} onSubmit={(r) => cancel.mutate(r)} />
        </>
      )}
    </QueryBoundary>
  )
}
