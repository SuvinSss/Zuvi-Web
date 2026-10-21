import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Minus, Plus, ShoppingBag, Store } from 'lucide-react'
import { useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui'
import { Stars, useToast } from '@/components/kit'
import { ProductImage } from '@/components/ProductImage'
import { useAuth } from '@/features/auth/AuthProvider'
import { errorMessage } from '@/lib/api'
import { formatMoney } from '@/lib/format'
import { addToCart } from '@/services/platform'
import type { CardImage } from '@/types/api'
import type { PublicProduct, PublicStore } from '@/types/platform'

export function toCardImage(thumbnail: string | null, display: string | null, name: string, category?: string): CardImage {
  return { source: thumbnail || display ? 'uploaded' : 'fallback', alt_text: name, thumbnail_url: thumbnail ?? display, display_url: display ?? thumbnail, fallback: { category: category ?? '', category_slug: '', brand: '' } }
}

/** Add-to-cart with a quantity stepper. Anonymous visitors are sent to sign in and brought back. */
export function AddToCart({ product, compact = false }: { product: Pick<PublicProduct, 'id' | 'name' | 'in_stock'>; compact?: boolean }) {
  const { user } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const toast = useToast()
  const client = useQueryClient()
  const [quantity, setQuantity] = useState(1)
  const add = useMutation({
    mutationFn: () => addToCart(product.id, String(quantity)),
    onSuccess: (cart) => { client.setQueryData(['cart'], cart); toast('success', `${product.name} added to your cart.`) },
    onError: (error) => toast('error', errorMessage(error, 'Could not add this to your cart.')),
  })
  if (!product.in_stock) return <Button variant="secondary" disabled className={compact ? 'w-full' : ''}>Out of stock</Button>
  if (user && user.role !== 'CUSTOMER') return null
  const onAdd = () => {
    if (!user) { navigate('/login', { state: { from: location.pathname + location.search } }); return }
    add.mutate()
  }
  return (
    <div className={`flex ${compact ? 'flex-col' : 'flex-wrap'} items-stretch gap-2`}>
      <div className="inline-flex items-center justify-between rounded-control ring-1 ring-inset ring-line" role="group" aria-label={`Quantity of ${product.name}`}>
        <button type="button" aria-label="Decrease quantity" disabled={quantity <= 1} onClick={() => setQuantity((q) => Math.max(1, q - 1))} className="grid size-11 place-items-center rounded-l-control hover:bg-pale disabled:opacity-40"><Minus className="size-4" aria-hidden="true" /></button>
        <span className="min-w-8 text-center text-sm font-semibold tabular-nums" aria-live="polite">{quantity}</span>
        <button type="button" aria-label="Increase quantity" disabled={quantity >= 99} onClick={() => setQuantity((q) => Math.min(99, q + 1))} className="grid size-11 place-items-center rounded-r-control hover:bg-pale disabled:opacity-40"><Plus className="size-4" aria-hidden="true" /></button>
      </div>
      <Button icon={ShoppingBag} loading={add.isPending} onClick={onAdd} className="flex-1">{user ? 'Add to cart' : 'Sign in to buy'}</Button>
    </div>
  )
}

export function ProductCard({ product }: { product: PublicProduct }) {
  return (
    <article className="flex flex-col overflow-hidden rounded-card border border-line bg-white shadow-card">
      <Link to={`/shop/${encodeURIComponent(product.product_code)}`} className="block p-2 pb-0" aria-label={`${product.name}, ${formatMoney(product.price)}`}>
        <ProductImage image={toCardImage(product.thumbnail, product.image, product.name, product.category.name)} name={product.name} />
      </Link>
      <div className="flex flex-1 flex-col gap-1 p-3">
        <p className="text-xs text-muted">{product.store.name}</p>
        <h3 className="line-clamp-2 min-h-10 text-sm font-semibold leading-5 text-ink"><Link to={`/shop/${encodeURIComponent(product.product_code)}`} className="hover:text-forest">{product.name}</Link></h3>
        <p className="text-xs text-muted">{product.unit_value} {product.unit.toLowerCase()}</p>
        {product.rating.count > 0 && <Stars value={product.rating.average} count={product.rating.count} size="size-3.5" />}
        <p className="mt-auto pt-1 text-base font-semibold tabular-nums text-forest">{formatMoney(product.price)}</p>
        <AddToCart product={product} compact />
      </div>
    </article>
  )
}

export function StoreCard({ store }: { store: PublicStore }) {
  return (
    <Link to={`/stores/${store.id}`} className="flex gap-3 rounded-card border border-line bg-white p-3 shadow-card hover:border-emerald/50">
      <div className="grid size-16 shrink-0 place-items-center overflow-hidden rounded-control bg-pale text-emerald">
        {store.image ? <img src={store.image} alt="" loading="lazy" className="size-full object-cover" /> : <Store className="size-7" aria-hidden="true" />}
      </div>
      <div className="min-w-0">
        <h3 className="truncate font-semibold text-forest">{store.name}</h3>
        <p className="text-xs text-muted">{store.city}</p>
        {store.description && <p className="mt-1 line-clamp-2 text-sm text-muted">{store.description}</p>}
        <div className="mt-1"><Stars value={store.rating.average} count={store.rating.count} size="size-3.5" /></div>
      </div>
    </Link>
  )
}
