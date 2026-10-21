import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { EvidencePanel } from '@/components/evidence'
import { KeyValue, QueryBoundary, ReasonDialog, Section, Status, Timeline, useToast } from '@/components/kit'
import { Alert, Button, Card, PageHeader } from '@/components/ui'
import { useAuth } from '@/features/auth/AuthProvider'
import { errorMessage } from '@/lib/api'
import { formatMoney } from '@/lib/format'
import { DELIVERY_STATUS, label, PAYMENT_METHOD, STORE_ORDER_STATUS } from '@/lib/labels'
import { confirmPickup, getStoreOrder, storeOrderAction } from '@/services/ops'

const ACTION_LABEL: Record<string, string> = { accept: 'Accept order', processing: 'Start preparing', ready: 'Mark ready', reject: 'Reject order' }

export default function StoreOrderPage() {
  const id = Number(useParams().id)
  const { user } = useAuth()
  const qc = useQueryClient()
  const toast = useToast()
  const q = useQuery({ queryKey: ['store-order', id], queryFn: () => getStoreOrder(id) })
  const [rejecting, setRejecting] = useState(false)
  const canManage = user?.store?.can_manage_orders ?? false
  const done = (o: unknown) => { qc.setQueryData(['store-order', id], o); void qc.invalidateQueries({ queryKey: ['store-orders'] }); void qc.invalidateQueries({ queryKey: ['store-me'] }) }
  const act = useMutation({ mutationFn: (v: { action: string; reason?: string }) => storeOrderAction(id, v.action, v.reason), onSuccess: (o) => { done(o); setRejecting(false); toast('success', 'Order updated.') }, onError: (e) => toast('error', errorMessage(e)) })
  const pickup = useMutation({ mutationFn: (deliveryId: number) => confirmPickup(deliveryId), onSuccess: () => { toast('success', 'Handover confirmed.'); void qc.invalidateQueries({ queryKey: ['evidence'] }); void qc.invalidateQueries({ queryKey: ['store-order', id] }) }, onError: (e) => toast('error', errorMessage(e)) })
  const o = q.data
  return (
    <QueryBoundary query={q} skeleton="detail">
      {o && (
        <>
          <PageHeader title={o.store_order_number} subtitle={`Order ${o.order_number}`} actions={<Link className="inline-flex min-h-11 items-center text-sm font-semibold text-forest underline" to="/store/orders">Back to orders</Link>} />
          <div className="grid gap-6 lg:grid-cols-[1fr_20rem]">
            <div className="space-y-6">
              <Card className="p-4">
                <div className="flex flex-wrap items-center justify-between gap-3"><Status value={o.status} label={label(STORE_ORDER_STATUS, o.status)} /><strong className="tabular-nums">{formatMoney(o.store_total)}</strong></div>
                {canManage && o.actions.length > 0 && (
                  <div className="mt-4 flex flex-wrap gap-2">
                    {o.actions.map((a) => a === 'reject'
                      ? <Button key={a} variant="danger" onClick={() => setRejecting(true)}>{ACTION_LABEL[a]}</Button>
                      : <Button key={a} loading={act.isPending && act.variables?.action === a} onClick={() => act.mutate({ action: a })}>{ACTION_LABEL[a] ?? label({}, a)}</Button>)}
                  </div>
                )}
                {!canManage && <p className="mt-3 text-sm text-muted">Your account can view orders but not change them.</p>}
              </Card>
              <Section title="Items">
                <Card className="p-4"><ul className="divide-y divide-line">{o.items.map((i) => <li key={i.id} className="flex justify-between gap-3 py-2 text-sm"><span className="min-w-0 break-words">{i.product_name} <span className="text-muted">({i.sku}) × {Number(i.quantity)} {i.unit}</span></span><span className="tabular-nums">{formatMoney(i.line_total)}</span></li>)}</ul></Card>
              </Section>
              {o.customer_notes && <Alert tone="info" title="Customer note">{o.customer_notes}</Alert>}
              {o.delivery && (
                <Section title="Delivery">
                  <Card className="space-y-3 p-4">
                    <KeyValue rows={[['Status', label(DELIVERY_STATUS, o.delivery.status)], ['Partner', o.delivery.partner_name ?? 'Not assigned yet']]} />
                    {['ACCEPTED', 'AT_STORE'].includes(o.delivery.status) && canManage && <Button loading={pickup.isPending} onClick={() => pickup.mutate(o.delivery!.id)}>Confirm handover to the partner</Button>}
                    <EvidencePanel deliveryId={o.delivery.id} emptyText="No handover proof yet." />
                  </Card>
                </Section>
              )}
            </div>
            <aside className="space-y-4">
              <Card className="p-4"><KeyValue rows={[['Type', o.fulfillment_type === 'PICKUP' ? 'Customer pickup' : 'Delivery'], ['Payment', label(PAYMENT_METHOD, o.payment_method)], ['Customer', o.recipient_first_name]]} />
                <p className="mt-2 text-xs text-muted">Customer contact details are shared only with the delivery partner.</p></Card>
              <Card className="p-4"><h2 className="mb-3 font-semibold text-forest">History</h2><Timeline items={o.timeline.map((t, i, a) => ({ key: `${t.status}-${i}`, title: label(STORE_ORDER_STATUS, t.status), note: t.reason, at: t.at, tone: i === a.length - 1 ? 'current' : 'done' }))} /></Card>
            </aside>
          </div>
          <ReasonDialog open={rejecting} title="Reject this order?" field="Reason (shown to the customer)" confirm="Reject order" danger busy={act.isPending} onClose={() => setRejecting(false)} onSubmit={(reason) => act.mutate({ action: 'reject', reason })} />
        </>
      )}
    </QueryBoundary>
  )
}
