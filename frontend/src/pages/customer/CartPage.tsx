import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Minus, Plus, ShoppingBag, Trash2 } from 'lucide-react'
import { Link } from 'react-router-dom'
import { QueryBoundary, useToast } from '@/components/kit'
import { Alert, Button, Card, PageHeader } from '@/components/ui'
import { errorMessage } from '@/lib/api'
import { formatMoney } from '@/lib/format'
import { clearCart, getCart, removeCartItem, setCartQuantity } from '@/services/platform'
import type { Cart, CartLine } from '@/types/platform'

function Line({ line, busy, onQty, onRemove }: { line: CartLine; busy: boolean; onQty: (q: number) => void; onRemove: () => void }) {
  const qty = Number(line.quantity)
  return (
    <li className="flex flex-col gap-3 py-4 sm:flex-row sm:items-center">
      <div className="min-w-0 flex-1">
        <Link to={`/shop/${encodeURIComponent(line.product_code)}`} className="font-semibold text-ink hover:text-forest">{line.name}</Link>
        <p className="text-xs text-muted">Sold by {line.store.name}</p>
        {line.unit_price && <p className="text-sm text-muted">{formatMoney(line.unit_price)} each</p>}
        {!line.is_available && <p className="mt-1 text-sm font-medium text-danger">This item is no longer available. Remove it to continue.</p>}
        {line.warnings.map((w) => <p key={w} className="mt-1 text-sm text-warn">{w}</p>)}
      </div>
      <div className="flex items-center justify-between gap-4 sm:justify-end">
        <div className="inline-flex items-center rounded-control ring-1 ring-inset ring-line" role="group" aria-label={`Quantity of ${line.name}`}>
          <button type="button" aria-label="Decrease quantity" disabled={busy || qty <= 1} onClick={() => onQty(qty - 1)} className="grid size-11 place-items-center rounded-l-control hover:bg-pale disabled:opacity-40"><Minus className="size-4" aria-hidden="true" /></button>
          <span className="min-w-8 text-center text-sm font-semibold tabular-nums" aria-live="polite">{qty}</span>
          <button type="button" aria-label="Increase quantity" disabled={busy || !line.is_available} onClick={() => onQty(qty + 1)} className="grid size-11 place-items-center rounded-r-control hover:bg-pale disabled:opacity-40"><Plus className="size-4" aria-hidden="true" /></button>
        </div>
        <p className="w-24 text-right font-semibold tabular-nums">{formatMoney(line.line_total)}</p>
        <button type="button" aria-label={`Remove ${line.name}`} disabled={busy} onClick={onRemove} className="grid size-11 place-items-center rounded-control text-muted hover:bg-danger-bg hover:text-danger"><Trash2 className="size-5" aria-hidden="true" /></button>
      </div>
    </li>
  )
}

export default function CartPage() {
  const client = useQueryClient()
  const toast = useToast()
  const cart = useQuery({ queryKey: ['cart'], queryFn: getCart })
  const done = (next: Cart) => client.setQueryData(['cart'], next)
  const fail = (error: unknown) => { toast('error', errorMessage(error)); void client.invalidateQueries({ queryKey: ['cart'] }) }
  const qty = useMutation({ mutationFn: ({ id, q }: { id: number; q: number }) => setCartQuantity(id, String(q)), onSuccess: done, onError: fail })
  const remove = useMutation({ mutationFn: (id: number) => removeCartItem(id), onSuccess: done, onError: fail })
  const clear = useMutation({ mutationFn: clearCart, onSuccess: () => { client.setQueryData(['cart'], { items: [], item_count: 0, subtotal: '0.00', has_issues: false }) }, onError: fail })
  const busy = qty.isPending || remove.isPending || clear.isPending
  const data = cart.data

  return (
    <>
      <PageHeader title="Your cart" actions={data && data.items.length > 0 ? <Button variant="ghost" onClick={() => clear.mutate()} disabled={busy}>Empty cart</Button> : undefined} />
      <QueryBoundary query={cart} skeleton="detail" isEmpty={data?.items.length === 0}
        empty={{ icon: ShoppingBag, title: 'Your cart is empty', text: 'Add something from a store and it will show up here.', action: <Link to="/shop"><Button>Start shopping</Button></Link> }}>
        {data && (
          <div className="grid gap-6 lg:grid-cols-[1fr_20rem]">
            <Card className="px-4"><ul className="divide-y divide-line">{data.items.map((l) => <Line key={l.id} line={l} busy={busy} onQty={(q) => qty.mutate({ id: l.id, q })} onRemove={() => remove.mutate(l.id)} />)}</ul></Card>
            <Card className="h-fit space-y-3 p-4 lg:sticky lg:top-24">
              <h2 className="font-semibold text-forest">Summary</h2>
              <div className="flex justify-between text-sm"><span className="text-muted">Items ({data.item_count})</span><span className="font-semibold tabular-nums">{formatMoney(data.subtotal)}</span></div>
              <p className="text-xs text-muted">Delivery charges and the final total are calculated by our server at checkout.</p>
              {data.has_issues && <Alert tone="warn">Some items need attention before you can check out.</Alert>}
              {data.has_issues ? <Button disabled className="w-full">Check out</Button> : <Link to="/checkout" className="block"><Button className="w-full">Check out</Button></Link>}
            </Card>
          </div>
        )}
      </QueryBoundary>
    </>
  )
}
