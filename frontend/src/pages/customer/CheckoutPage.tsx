import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { MapPin } from 'lucide-react'
import { useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { QueryBoundary } from '@/components/kit'
import { Alert, Button, Card, Field, PageHeader, Textarea, ButtonLink } from '@/components/ui'
import { errorMessage } from '@/lib/api'
import { formatMoney } from '@/lib/format'
import { getCheckoutPreview, placeOrder } from '@/services/platform'

function newKey() {
  return crypto.randomUUID().replace(/-/g, '')
}

export default function CheckoutPage() {
  const navigate = useNavigate()
  const client = useQueryClient()
  const preview = useQuery({ queryKey: ['checkout-preview'], queryFn: getCheckoutPreview, staleTime: 0, gcTime: 0 })
  const [addressId, setAddressId] = useState<number | null>(null)
  const [fulfillment, setFulfillment] = useState<string | null>(null)
  const [pickup, setPickup] = useState<Record<string, number>>({})
  const [notes, setNotes] = useState('')
  const [error, setError] = useState('')
  // One key per attempt-set: a retry after a network drop reuses it, so we can never create two orders.
  const key = useRef(newKey())
  const data = preview.data

  const place = useMutation({
    mutationFn: () => placeOrder({
      fulfillment_type: fulfillment ?? data?.fulfillment_types[0]?.value ?? 'DELIVERY',
      payment_method: data?.payment_methods[0]?.value ?? 'COD',
      delivery_address_id: (fulfillment ?? data?.fulfillment_types[0]?.value) === 'DELIVERY' ? (addressId ?? data?.addresses.find((a) => a.is_default)?.id ?? data?.addresses[0]?.id ?? null) : null,
      pickup_locations: pickup,
      customer_notes: notes,
    }, key.current),
    onSuccess: (order) => {
      void client.invalidateQueries({ queryKey: ['cart'] })
      void client.invalidateQueries({ queryKey: ['orders'] })
      key.current = newKey()
      navigate(`/account/orders/${order.id}`, { replace: true, state: { placed: true } })
    },
    onError: (e) => setError(errorMessage(e, 'We could not place your order.')),
  })

  const type = fulfillment ?? data?.fulfillment_types[0]?.value ?? 'DELIVERY'
  const chosen = addressId ?? data?.addresses.find((a) => a.is_default)?.id ?? data?.addresses[0]?.id ?? null
  const missingAddress = type === 'DELIVERY' && chosen === null
  const missingPickup = type !== 'DELIVERY' && data?.store_groups.some((g) => g.pickup_locations.length > 0 && !pickup[String(g.store.id)])

  return (
    <>
      <PageHeader title="Checkout" subtitle="Review your order and choose how you want to receive it." />
      <QueryBoundary query={preview} skeleton="detail" isEmpty={data?.store_groups.length === 0} empty={{ icon: MapPin, title: 'Your cart is empty', text: 'Add items before checking out.', action: <ButtonLink to="/shop">Browse products</ButtonLink> }}>
        {data && (
          <div className="grid gap-6 lg:grid-cols-[1fr_22rem]">
            <div className="space-y-5">
              {data.has_blocking_issues && <Alert tone="error" title="Fix these before you order">{data.blocking_messages.map((m) => <p key={m}>{m}</p>)}<Link to="/cart" className="mt-1 inline-block font-semibold underline">Back to cart</Link></Alert>}
              {data.fulfillment_types.length > 1 && (
                <Card className="p-4"><fieldset><legend className="mb-2 font-semibold text-forest">How would you like it?</legend>
                  <div className="grid gap-2 sm:grid-cols-2">{data.fulfillment_types.map((f) => (
                    <label key={f.value} className={`flex min-h-11 cursor-pointer items-center gap-2 rounded-control border p-3 text-sm ${type === f.value ? 'border-emerald bg-pale' : 'border-line'}`}>
                      <input type="radio" name="fulfillment" checked={type === f.value} onChange={() => setFulfillment(f.value)} />{f.label}
                    </label>))}</div></fieldset></Card>
              )}
              {type === 'DELIVERY' ? (
                <Card className="p-4">
                  <h2 className="mb-2 font-semibold text-forest">Delivery address</h2>
                  {data.addresses.length === 0 ? (
                    <Alert tone="warn" title="Add a delivery address">We need an address to deliver to. <Link to="/account/addresses?add=1&next=checkout" className="font-semibold underline">Add an address</Link></Alert>
                  ) : (
                    <fieldset><legend className="sr-only">Choose a delivery address</legend>
                      <div className="space-y-2">{data.addresses.map((a) => (
                        <label key={a.id} className={`flex cursor-pointer gap-3 rounded-control border p-3 text-sm ${chosen === a.id ? 'border-emerald bg-pale' : 'border-line'}`}>
                          <input type="radio" name="address" className="mt-1" checked={chosen === a.id} onChange={() => setAddressId(a.id)} />
                          <span><span className="font-semibold">{a.recipient_name}</span> · {a.phone_number}<br />{[a.line1, a.line2, a.landmark, a.city, a.state, a.postal_code].filter(Boolean).join(', ')}{a.is_default && <span className="ml-2 text-xs text-emerald">Default</span>}</span>
                        </label>))}</div>
                      <Link to="/account/addresses" className="mt-2 inline-block inline-flex min-h-11 items-center text-sm font-semibold text-forest hover:underline">Manage addresses</Link>
                    </fieldset>
                  )}
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
              <dl className="space-y-1.5 text-sm">
                <div className="flex justify-between"><dt className="text-muted">Items</dt><dd className="tabular-nums">{formatMoney(data.items_subtotal)}</dd></div>
                <div className="flex justify-between"><dt className="text-muted">Delivery</dt><dd className="tabular-nums">{Number(data.delivery_charge) === 0 ? 'Free' : formatMoney(data.delivery_charge)}</dd></div>
                {Number(data.discount_total) > 0 && <div className="flex justify-between"><dt className="text-muted">Discount</dt><dd className="tabular-nums">−{formatMoney(data.discount_total)}</dd></div>}
                <div className="flex justify-between border-t border-line pt-2 text-base font-semibold"><dt>Total</dt><dd className="tabular-nums text-forest">{formatMoney(data.grand_total)}</dd></div>
              </dl>
              <div className="rounded-control bg-canvas p-3 text-sm"><p className="font-semibold">Payment</p><p className="text-muted">{data.payment_methods.map((m) => m.label).join(', ')} — pay when you receive your order.</p></div>
              {error && <Alert tone="error">{error}</Alert>}
              <Button className="w-full" loading={place.isPending} disabled={data.has_blocking_issues || missingAddress || Boolean(missingPickup)} onClick={() => { setError(''); place.mutate() }}>Place order</Button>
              {(missingAddress || missingPickup) && <p className="text-xs text-muted">{missingAddress ? 'Choose a delivery address to continue.' : 'Choose a pickup location for each store.'}</p>}
            </Card>
          </div>
        )}
      </QueryBoundary>
    </>
  )
}
