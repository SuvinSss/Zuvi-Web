import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { LifeBuoy, Star } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ConfirmDialog, KeyValue, Modal, QueryBoundary, RatingInput, Section, Status, Timeline, useToast } from '@/components/kit'
import { EvidencePanel } from '@/components/evidence'
import { OrderTrackingPanel } from '@/components/tracking'
import { Button, Card, Field, PageHeader, Textarea, Input, ButtonLink } from '@/components/ui'
import { errorMessage } from '@/lib/api'
import { formatMoney } from '@/lib/format'
import { label, ORDER_STATUS, PAYMENT_METHOD, PAYMENT_STATUS, STORE_ORDER_STATUS } from '@/lib/labels'
import { cancelOrder, createReview, getOrder, getTracking, listMyReviews } from '@/services/platform'
import type { OrderDetail } from '@/types/platform'

export default function OrderPage() {
  const id = Number(useParams().id)
  const qc = useQueryClient()
  const toast = useToast()
  const order = useQuery({ queryKey: ['order', id], queryFn: () => getOrder(id), enabled: Number.isFinite(id) })
  const [cancelling, setCancelling] = useState(false)
  const [reason, setReason] = useState('')
  const cancel = useMutation({
    mutationFn: () => cancelOrder(id, reason.trim()),
    onSuccess: () => { toast('success', 'Your order was cancelled.'); setCancelling(false); void qc.invalidateQueries({ queryKey: ['order', id] }); void qc.invalidateQueries({ queryKey: ['orders'] }) },
    onError: (e) => toast('error', errorMessage(e)),
  })
  const o = order.data
  return (
    <QueryBoundary query={order} skeleton="detail">
      {o && (
        <>
          <PageHeader title={`Order ${o.order_number}`} subtitle={new Date(o.placed_at).toLocaleString('en-IN')}
            actions={<div className="flex flex-wrap gap-2">
              <ButtonLink to={`/account/support/new-ticket?order=${o.id}`} variant="outline" icon={LifeBuoy}>Get help</ButtonLink>
              {o.can_cancel && <Button variant="destructive" onClick={() => setCancelling(true)}>Cancel order</Button>}
            </div>} />
          <div className="grid gap-6 lg:grid-cols-[1fr_20rem]">
            <div className="space-y-6">
              <Card className="p-4"><div className="flex flex-wrap items-center gap-3"><Status value={o.status} label={label(ORDER_STATUS, o.status)} />
                <span className="text-sm text-muted">{label(PAYMENT_METHOD, o.payment_method)} · {label(PAYMENT_STATUS, o.payment_status)}</span></div>
                {o.cancellation_reason && <p className="mt-2 text-sm">Reason: {o.cancellation_reason}</p>}
              </Card>
              {o.fulfillment_type === 'DELIVERY' && <Section title="Delivery"><OrderTrackingPanel orderId={o.id} active={!['COMPLETED', 'CANCELLED'].includes(o.status)} /></Section>}
              {o.store_orders.map((so) => (
                <Section key={so.id} title={so.store.name}>
                  <Card className="p-4">
                    <div className="flex flex-wrap items-center justify-between gap-2"><span className="text-sm text-muted">{so.store_order_number}</span><Status value={so.status} label={label(STORE_ORDER_STATUS, so.status)} /></div>
                    <ul className="mt-3 divide-y divide-line">
                      {so.items.map((it, i) => (
                        <li key={i} className="flex justify-between gap-3 py-2 text-sm"><span className="min-w-0 break-words">{it.product_name} <span className="text-muted">× {Number(it.quantity)} {it.unit}</span></span><span className="tabular-nums">{formatMoney(it.line_total)}</span></li>
                      ))}
                    </ul>
                    {so.delivery && <p className="mt-2 text-right text-xs text-muted">Delivery {Number(so.delivery.customer_total) === 0 ? 'free' : formatMoney(so.delivery.customer_total)} · {Number(so.delivery.distance_km).toFixed(1)} km{so.delivery.distance_source === 'estimated' ? ' (estimated)' : ''}{Number(so.delivery.delivery_discount) > 0 ? ` · ${so.delivery.discount_reason}` : ''}</p>}
                    <p className="mt-1 text-right text-sm font-semibold">Store total {formatMoney(so.store_total)}</p>
                    {so.status === 'COMPLETED' && <ReviewPanel storeOrderId={so.id} storeName={so.store.name} />}
                  </Card>
                </Section>
              ))}
              <DeliveryProof order={o} />
              <Section title="Order timeline"><Card className="p-4"><Timeline items={o.timeline.map((t, i, a) => ({ key: `${t.status}-${i}`, title: label(ORDER_STATUS, t.status), at: t.at, tone: i === a.length - 1 ? (t.status === 'CANCELLED' ? 'bad' : 'current') : 'done' }))} /></Card></Section>
            </div>
            <aside className="space-y-4">
              <Card className="p-4"><h2 className="mb-3 font-semibold text-forest">Summary</h2>
                <KeyValue rows={[['Items', formatMoney(o.items_subtotal)], ['Delivery', formatMoney(o.delivery_charge)], ['Discount', formatMoney(o.discount_total)], ['Total', <strong key="t">{formatMoney(o.grand_total)}</strong>]]} /></Card>
              {o.delivery_address && <Card className="p-4"><h2 className="mb-2 font-semibold text-forest">Delivering to</h2>
                <address className="text-sm not-italic">{o.delivery_address.recipient_name}<br />{o.delivery_address.line1}{o.delivery_address.line2 ? `, ${o.delivery_address.line2}` : ''}<br />{o.delivery_address.city}, {o.delivery_address.state} {o.delivery_address.postal_code}<br />{o.delivery_address.phone_number}</address></Card>}
              {o.customer_notes && <Card className="p-4"><h2 className="mb-1 font-semibold text-forest">Your note</h2><p className="whitespace-pre-line text-sm">{o.customer_notes}</p></Card>}
              <Link className="block inline-flex min-h-11 items-center text-sm font-semibold text-forest underline" to={`/account/support/new-complaint?order=${o.id}`}>Report a problem with this order</Link>
            </aside>
          </div>
          <ConfirmDialog open={cancelling} onClose={() => setCancelling(false)} onConfirm={() => cancel.mutate()} busy={cancel.isPending} danger confirmLabel="Cancel order" title="Cancel this order?">
            <Field label="Reason (optional)" hint="This helps the store understand what happened.">{(p) => <Textarea {...p} rows={3} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} />}</Field>
          </ConfirmDialog>
        </>
      )}
    </QueryBoundary>
  )
}

/** Delivery proof is only fetched once the order has a delivery (the API hides pickup proof from customers). */
function DeliveryProof({ order }: { order: OrderDetail }) {
  const tracking = useQuery({ queryKey: ['tracking', order.id], queryFn: () => getTracking(order.id), enabled: order.fulfillment_type === 'DELIVERY' })
  const done = tracking.data?.deliveries.filter((d) => d.status === 'DELIVERED') ?? []
  if (!done.length) return null
  return <Section title="Proof of delivery">{done.map((d) => <EvidencePanel key={d.delivery_id} deliveryId={d.delivery_id} />)}</Section>
}

function ReviewPanel({ storeOrderId, storeName }: { storeOrderId: number; storeName: string }) {
  const qc = useQueryClient()
  const toast = useToast()
  const mine = useQuery({ queryKey: ['my-reviews', 'all'], queryFn: () => listMyReviews(1) })
  const [open, setOpen] = useState(false)
  const [rating, setRating] = useState(0)
  const [title, setTitle] = useState('')
  const [comment, setComment] = useState('')
  const existing = mine.data?.results.find((r) => r.store_order === storeOrderId && r.target_type === 'STORE')
  const save = useMutation({
    mutationFn: () => createReview({ store_order: storeOrderId, target_type: 'STORE', rating, title, comment }),
    onSuccess: () => { toast('success', 'Thanks for your review.'); setOpen(false); void qc.invalidateQueries({ queryKey: ['my-reviews'] }) },
    onError: (e) => toast('error', errorMessage(e)),
  })
  if (existing) return <p className="mt-3 text-sm text-muted">You reviewed {storeName}: {existing.rating}/5. <Link className="font-semibold text-forest underline" to="/account/reviews">Manage reviews</Link></p>
  return (
    <div className="mt-3">
      <Button variant="outline" icon={Star} onClick={() => setOpen(true)}>Review {storeName}</Button>
      <Modal open={open} onClose={() => setOpen(false)} title={`Review ${storeName}`} footer={<><Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button><Button onClick={() => (rating ? save.mutate() : toast('error', 'Choose a star rating first.'))} loading={save.isPending}>Submit review</Button></>}>
        <div className="space-y-3">
          <RatingInput value={rating} onChange={setRating} />
          <Field label="Title (optional)">{(p) => <Input {...p} maxLength={120} value={title} onChange={(e) => setTitle(e.target.value)} />}</Field>
          <Field label="Your review (optional)">{(p) => <Textarea {...p} rows={4} maxLength={2000} value={comment} onChange={(e) => setComment(e.target.value)} />}</Field>
        </div>
      </Modal>
    </div>
  )
}
