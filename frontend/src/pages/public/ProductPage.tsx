import { useQuery } from '@tanstack/react-query'
import { Package } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ProductImage } from '@/components/ProductImage'
import { Pagination, QueryBoundary, Section, Stars } from '@/components/kit'
import { AddToCart, toCardImage } from '@/components/shop'
import { ReviewList } from '@/components/reviews'
import { Card } from '@/components/ui'
import { formatMoney } from '@/lib/format'
import { getPublicProduct, listProductReviews } from '@/services/platform'

export default function ProductPage() {
  const { code = '' } = useParams()
  const product = useQuery({ queryKey: ['product', code], queryFn: () => getPublicProduct(code), retry: false })
  const [active, setActive] = useState(0)
  const [reviewPage, setReviewPage] = useState(1)
  const id = product.data?.id
  const reviews = useQuery({ queryKey: ['product-reviews', id, reviewPage], queryFn: () => listProductReviews(id as number, reviewPage), enabled: id !== undefined })
  const p = product.data

  return (
    <QueryBoundary query={product} skeleton="detail">
      {p && (
        <div className="space-y-8">
          <nav aria-label="Breadcrumb" className="text-sm text-muted">
            <Link to="/shop" className="hover:text-forest">Shop</Link> <span aria-hidden="true">/</span> <Link to={`/shop?category=${p.category.id}`} className="hover:text-forest">{p.category.name}</Link>
          </nav>
          <div className="grid gap-6 md:grid-cols-2">
            <div>
              <ProductImage size="detail" eager image={toCardImage(p.images[active]?.thumbnail ?? p.thumbnail, p.images[active]?.url ?? p.image, p.name, p.category.name)} name={p.name} className="w-full" />
              {p.images.length > 1 && (
                <ul className="mt-3 flex gap-2 overflow-x-auto" aria-label="Product photos">
                  {p.images.map((img, i) => (
                    <li key={i}><button type="button" aria-label={`Photo ${i + 1}`} aria-pressed={i === active} onClick={() => setActive(i)} className={`block size-16 overflow-hidden rounded-control ring-2 ${i === active ? 'ring-emerald' : 'ring-transparent'}`}>
                      <img src={img.thumbnail ?? img.url ?? ''} alt="" loading="lazy" className="size-full object-contain" /></button></li>
                  ))}
                </ul>
              )}
            </div>
            <div className="space-y-4">
              <div>
                <h1 className="text-2xl font-semibold text-forest sm:text-3xl">{p.name}</h1>
                <p className="mt-1 text-sm text-muted">{p.brand ? `${p.brand} · ` : ''}{p.unit_value} {p.unit.toLowerCase()} · Sold by <Link to={`/stores/${p.store.id}`} className="font-medium text-forest hover:underline">{p.store.name}</Link></p>
              </div>
              <Stars value={p.rating.average} count={p.rating.count} />
              <p className="text-3xl font-semibold tabular-nums text-forest">{formatMoney(p.price)}</p>
              <p className={`text-sm font-medium ${p.in_stock ? 'text-deep' : 'text-danger'}`}>{p.in_stock ? 'In stock' : 'Currently out of stock'}</p>
              <AddToCart product={p} />
              {p.description && <div><h2 className="text-sm font-semibold text-forest">About this product</h2><p className="mt-1 whitespace-pre-line text-sm text-ink">{p.description}</p></div>}
            </div>
          </div>
          <Section title="Customer reviews">
            <QueryBoundary query={reviews} skeleton="detail" isEmpty={reviews.data?.count === 0} empty={{ icon: Package, title: 'No reviews yet', text: 'Only customers who received this product can review it.' }}>
              <Card className="p-4">
                <ReviewList reviews={reviews.data?.results ?? []} />
                <Pagination page={reviewPage} count={reviews.data?.count ?? 0} onPage={setReviewPage} />
              </Card>
            </QueryBoundary>
          </Section>
        </div>
      )}
    </QueryBoundary>
  )
}
