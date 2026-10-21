import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Info, MapPin } from 'lucide-react'
import { useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { QueryBoundary } from '@/components/kit'
import { AddressDialog } from '@/components/location/AddressDialog'
import { Alert, Button, Card, Field, PageHeader, Textarea, ButtonLink } from '@/components/ui'
import { useDeliveryLocation } from '@/features/location/DeliveryLocation'
import { errorMessage } from '@/lib/api'
import { formatMoney } from '@/lib/format'
import { checkoutQuote } from '@/services/delivery'
import { getCheckoutPreview, placeOrder } from '@/services/platform'
import type { CustomerDelivery } from '@/types/delivery'

function newKey() {
  return crypto.randomUUID().replace(/-/g, '')
}

function DeliveryLine({ name, d, error }: { name: string; d: CustomerDelivery | null; error: string | null }) {
  const [open, setOpen] = useState(false)
  if (!d) return <div className="text-sm"><p className="font-medium">{name}</p><p className="text-danger">{error ?? 'Cannot deliver.'}</p></div>
  const free = Number(d.customer_total) === 0
  return (
    <div className="text-sm">
      <div className="flex justify-between gap-3">
        <dt className="text-muted">Delivery from {name}</dt>
        <dd className="tabular-nums">{free ? <><s className="mr-1 text-muted">{formatMoney(d.customer_fee_before_discount)}</s>Free</> : formatMoney(d.customer_total)}</dd>
      </div>
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} className="mt-0.5 inline-flex min-h-8 items-center gap-1 text-xs text-forest underline-offset-2 hover:underline">
        <Info className="size-3.5" aria-hidden="true" />{d.explanation} · {Number(d.distance_km).toFixed(1)} km{d.eta_minutes ? ` · about ${d.eta_minutes} min` : ''}
      </button>
      {open && (
        <dl className="mt-1 space-y-0.5 rounded-control bg-canvas p-2 text-xs">
          <div className="flex justify-between"><dt>Distance{d.distance_source === 'estimated' ? ' (estimated, road route unavailable)' : ' by road'}</dt><dd>{Number(d.distance_km).toFixed(2)} km</dd></div>
          {Object.entries(d.surcharges).filter(([, v]) => Number(v) > 0).map(([k, v]) => <div key={k} className="flex justify-between"><dt>{k === 'peak' ? 'Busy-hour charge' : k === 'service_area' ? 'Hard-to-reach area' : 'Heavy items'}</dt><dd>{formatMoney(v)} included</dd></div>)}
          <div className="flex justify-between"><dt>Delivery fee</dt><dd>{formatMoney(d.customer_fee_before_discount)}</dd></div>
          {Number(d.delivery_discount) > 0 && <div className="flex justify-between text-deep"><dt>{d.discount_reason}</dt><dd>−{formatMoney(d.delivery_discount)}</dd></div>}
          {Number(d.delivery_tax) > 0 && <div className="flex justify-between"><dt>Tax on delivery</dt><dd>{formatMoney(d.delivery_tax)}</dd></div>}
        </dl>
      )}
    </div>
  )
}

export default function CheckoutPage() {
  const navigate = useNavigate()
  const client = useQueryClient()
  const location = useDeliveryLocation()
  const preview = useQuery({ queryKey: ['checkout-preview'], queryFn: getCheckoutPreview, staleTime: 0, gcTime: 0 })
  const [addressId, setAddressId] = useState<number | null>(null)
  const [fulfillment, setFulfillment] = useState<string | null>(null)
  const [pickup, setPickup] = useState<Record<string, number>>({})
  const [notes, setNotes] = useState('')
  const [error, setError] = useState('')
  const [changed, setChanged] = useState('')
  const [adding, setAdding] = useState(false)
  // One key per attempt-set: a retry after a network drop reuses it, so we can never create two orders.
  const key = useRef(newKey())
  const data = preview.data

  const type = fulfillment ?? data?.fulfillment_types[0]?.value ?? 'DELIVERY'
  const usable = (data?.addresses ?? []).filter((a) => Number(a.latitude) || Number(a.longitude))
  const chosen = addressId ?? (location.selected?.addressId && usable.some((a) => a.id === location.selected?.addressId) ? location.selected.addressId : null)
    ?? usable.find((a) => a.is_default)?.id ?? usable[0]?.id ?? null
  const cartKey = data?.store_groups.map((g) => g.items.map((i) => `${i.id}:${i.quantity}:${i.unit_price}`).join(',')).join('|')
  const quote = useQuery({
    queryKey: ['checkout-quote', type, chosen, cartKey],
    queryFn: () => checkoutQuote({ fulfillment_type: type, delivery_address_id: type === 'DELIVERY' ? chosen : null }),
    enabled: Boolean(data) && !data?.has_blocking_issues && (type !== 'DELIVERY' || chosen !== null), retry: false, staleTime: 0,
  })
  const q = quote.data

  const place = useMutation({
    mutationFn: () => placeOrder({
      fulfillment_type: type, payment_method: data?.payment_methods[0]?.value ?? 'COD',
      delivery_address_id: type === 'DELIVERY' ? chosen : null, pickup_locations: pickup, customer_notes: notes, quote_token: q?.quote_token ?? null,
    }, key.current),
    onSuccess: (order) => {
      void client.invalidateQueries({ queryKey: ['cart'] })
      void client.invalidateQueries({ queryKey: ['orders'] })
      key.current = newKey()
      navigate(`/account/orders/${order.id}`, { replace: true, state: { placed: true } })
    },
    onError: (e) => {
      const resp = (e as { response?: { status: number; data?: { quote_token?: string[] } } }).response
      if (resp?.status === 409) {
        setChanged(resp.data?.quote_token?.[0] ?? 'The total changed. Please review it.')
        key.current = newKey()
        void quote.refetch()
        return
      }
      setError(errorMessage(e, 'We could not place your order.'))
    },
  })

  const missingAddress = type === 'DELIVERY' && chosen === null
  const missingPickup = type !== 'DELIVERY' && data?.store_groups.some((g) => g.pickup_locations.length > 0 && !pickup[String(g.store.id)])
  const blocked = Boolean(data?.has_blocking_issues || missingAddress || missingPickup || !q || q.has_blocking_issues || quote.isFetching)
  const unpinned = (data?.addresses ?? []).filter((a) => !(Number(a.latitude) || Number(a.longitude)))

  return (
    <>
      <PageHeader title="Checkout" subtitle="Review your order and how you'll receive it." />
      <QueryBoundary query={preview} skeleton="detail" isEmpty={data?.store_groups.length === 0} empty={{ icon: MapPin, title: 'Your cart is empty', text: 'Add items before checking out.', action: <ButtonLink to="/shop">Browse products</ButtonLink> }}>
        {data && (
          <div className="grid gap-6 lg:grid-cols-[1fr_22rem]">
            <div className="space-y-5">
              {data.has_blocking_issues && <Alert tone="error" title="Fix these before you order">{data.blocking_messages.map((m) => <p key={m}>{m}</p>)}<Link to="/cart" className="mt-1 inline-block font-semibold underline">Back to cart</Link></Alert>}
              {data.fulfillment_types.length > 1 && (
                <Card className="p-4"><fieldset><legend className="mb-2 font-semibold text-forest">How would you like it?</legend>
                  <div className="grid gap-2 sm:grid-cols-2">{data.fulfillment_types.map((f) => (
                    <label key={f.value} className={`flex min-h-11 cursor-pointer items-center gap-2 rounded-control border p-3 text-sm ${type === f.value ? 'border-emerald bg-pale' : 'border-line'}`}>
                      <input type="radio" name="fulfillment" checked={type === f.value} onChange={() => { setFulfillment(f.value); setChanged('') }} />{f.label}
                    </label>))}</div></fieldset></Card>
              )}
              {type === 'DELIVERY' ? (
                <Card className="p-4">
                  <div className="mb-2 flex items-center justify-between gap-2"><h2 className="font-semibold text-forest">Deliver to</h2><Button size="sm" variant="outline" onClick={() => setAdding(true)}>Add address</Button></div>
                  {usable.length === 0 ? (
                    <Alert tone="warn" title="Add a delivery address">Pin your address on the map so we can check delivery and price it.</Alert>
                  ) : (
                    <fieldset><legend className="sr-only">Choose a delivery address</legend>
                      <div className="space-y-2">{usable.map((a) => (
                        <label key={a.id} className={`flex cursor-pointer gap-3 rounded-control border p-3 text-sm ${chosen === a.id ? 'border-emerald bg-pale' : 'border-line'}`}>
                          <input type="radio" name="address" className="mt-1" checked={chosen === a.id} onChange={() => { setAddressId(a.id); setChanged(''); location.selectAddress(a) }} />
                          <span><span className="font-semibold">{a.short_label ?? a.label}</span> · {a.recipient_name} · {a.phone_number}<br />{[a.line1, a.line2, a.landmark && `near ${a.landmark}`, a.city, a.postal_code].filter(Boolean).join(', ')}
                            {a.is_default && <span className="ml-2 text-xs text-emerald">Default</span>}</span>
                        </label>))}</div>
                      <Link to="/account/addresses" className="mt-2 inline-flex min-h-11 items-center text-sm font-semibold text-forest hover:underline">Manage addresses</Link>
                    </fieldset>
                  )}
                  {unpinned.length > 0 && <p className="mt-2 text-xs text-warn">{unpinned.length} saved address{unpinned.length > 1 ? 'es have' : ' has'} no map pin and can't be used until you confirm the pin in Saved addresses.</p>}
                </Card>
              ) : (
                <Card className="space-y-3 p-4"><h2 className="font-semibold text-forest">Pickup location</h2>
                  {data.store_groups.map((g) => (
                    <Field key={g.store.id} label={`Pick up ${g.store.name} order at`}>{(p) => (
                      <select {...p} className="block min-h-11 w-full rounded-control border border-line bg-white px-3 text-base sm:text-sm" value={pickup[String(g.store.id)] ?? ''} onChange={(e) => setPickup((s) => ({ ...s, [String(g.store.id)]: Number(e.target.value) }))}>
                        <option value="">Choose a location</option>{g.pickup_locations.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
                      </select>)}</Field>))}
                </Card>
              )}
              <Card className="p-4"><h2 className="mb-2 font-semibold text-forest">Items</h2>
                {data.store_groups.map((g) => (
                  <div key={g.store.id} className="mb-3 last:mb-0"><p className="text-sm font-semibold">{g.store.name}</p>
                    <ul className="divide-y divide-line text-sm">{g.items.map((i) => <li key={i.id} className="flex justify-between gap-3 py-1.5"><span className="min-w-0 break-words">{Number(i.quantity)} × {i.name}</span><span className="tabular-nums">{formatMoney(i.line_total)}</span></li>)}</ul></div>))}
              </Card>
              <Card className="p-4"><Field label="Note for the store or delivery partner (optional)">{(p) => <Textarea {...p} rows={2} maxLength={500} value={notes} onChange={(e) => setNotes(e.target.value)} />}</Field></Card>
            </div>
            <Card className="h-fit space-y-3 p-4 lg:sticky lg:top-24">
              <h2 className="font-semibold text-forest">Order summary</h2>
              {changed && <Alert tone="warn" title="Your total changed">{changed} Check the new total below, then place the order again.</Alert>}
              <dl className="space-y-2 text-sm" aria-live="polite" aria-busy={quote.isFetching}>
                <div className="flex justify-between"><dt className="text-muted">Items</dt><dd className="tabular-nums">{formatMoney(data.items_subtotal)}</dd></div>
                {Number(data.discount_total) > 0 && <div className="flex justify-between"><dt className="text-muted">Product discounts</dt><dd className="tabular-nums">−{formatMoney(data.discount_total)}</dd></div>}
                {type === 'DELIVERY' && quote.isFetching && <p className="text-xs text-muted">Working out delivery…</p>}
                {type === 'DELIVERY' && q?.stores.map((s) => <DeliveryLine key={s.store_id} name={s.store_name} d={s.delivery} error={s.error} />)}
                {type !== 'DELIVERY' && <div className="flex justify-between"><dt className="text-muted">Delivery</dt><dd>Pickup, no fee</dd></div>}
                <div className="flex justify-between border-t border-line pt-2 text-base font-semibold"><dt>To pay</dt><dd className="tabular-nums text-forest">{q ? formatMoney(q.grand_total) : '—'}</dd></div>
              </dl>
              {quote.isError && <Alert tone="error">{errorMessage(quote.error, 'We could not work out delivery right now.')}</Alert>}
              {q && !q.all_deliverable && <Alert tone="error" title="Can't deliver this order">{q.blocking_messages.map((m) => <p key={m}>{m}</p>)}<p className="mt-1">Choose another address{data.fulfillment_types.length > 1 ? ' or pickup' : ''}.</p></Alert>}
              <div className="rounded-control bg-canvas p-3 text-sm"><p className="font-semibold">Payment</p><p className="text-muted">{data.payment_methods.map((m) => m.label).join(', ')} — pay when you receive your order.</p></div>
              {error && <Alert tone="error">{error}</Alert>}
              <Button className="w-full" loading={place.isPending} disabled={blocked} onClick={() => { setError(''); setChanged(''); place.mutate() }}>Place order{q ? ` · ${formatMoney(q.grand_total)}` : ''}</Button>
              {(missingAddress || missingPickup) && <p className="text-xs text-muted">{missingAddress ? 'Add a delivery address with a map pin to continue.' : 'Choose a pickup location for each store.'}</p>}
              <p className="text-xs text-muted">Prices and delivery are checked again when you place the order.</p>
            </Card>
          </div>
        )}
      </QueryBoundary>
      {adding && <AddressDialog address={null} onSaved={() => { void client.invalidateQueries({ queryKey: ['checkout-preview'] }); void client.invalidateQueries({ queryKey: ['addresses'] }) }}
        onClose={(saved) => { setAdding(false); if (saved) { setAddressId(saved.id); location.selectAddress(saved) } }} />}
    </>
  )
}
