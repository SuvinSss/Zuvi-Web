import { useQuery } from '@tanstack/react-query'
import { Package, Store } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Pagination, QueryBoundary, Section, Stars } from '@/components/kit'
import { ProductCard } from '@/components/shop'
import { ReviewList } from '@/components/reviews'
import { Card, PageHeader } from '@/components/ui'
import { getPublicStore, listPublicProducts, listStoreReviews } from '@/services/platform'

export default function StorePage() {
  const id = Number(useParams().id)
  const store = useQuery({ queryKey: ['store', id], queryFn: () => getPublicStore(id), retry: false })
  const [page, setPage] = useState(1)
  const [reviewPage, setReviewPage] = useState(1)
  const products = useQuery({ queryKey: ['products', 'store', id, page], queryFn: () => listPublicProducts({ store: String(id), page, page_size: 20 }), placeholderData: (p) => p })
  const reviews = useQuery({ queryKey: ['store-reviews', id, reviewPage], queryFn: () => listStoreReviews(id, reviewPage) })
  const s = store.data
  return (
    <QueryBoundary query={store} skeleton="detail">
      {s && (
        <div className="space-y-8">
          <nav aria-label="Breadcrumb" className="text-sm text-muted"><Link to="/stores" className="hover:text-forest">Stores</Link> <span aria-hidden="true">/</span> {s.name}</nav>
          <PageHeader title={s.name} subtitle={[s.city, s.description].filter(Boolean).join(' · ')} actions={<Stars value={s.rating.average} count={s.rating.count} />} />
          <Section title="Products">
            <QueryBoundary query={products} skeleton="cards" isEmpty={products.data?.count === 0} empty={{ icon: Store, title: 'No products available right now', text: 'This store has nothing in stock at the moment.' }}>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">{products.data?.results.map((p) => <ProductCard key={p.id} product={p} />)}</div>
              <Pagination page={page} count={products.data?.count ?? 0} onPage={setPage} />
            </QueryBoundary>
          </Section>
          <Section title="Store reviews">
            <QueryBoundary query={reviews} skeleton="detail" isEmpty={reviews.data?.count === 0} empty={{ icon: Package, title: 'No reviews yet', text: 'Customers can review a store after their order is completed.' }}>
              <Card className="p-4"><ReviewList reviews={reviews.data?.results ?? []} /><Pagination page={reviewPage} count={reviews.data?.count ?? 0} onPage={setReviewPage} /></Card>
            </QueryBoundary>
          </Section>
        </div>
      )}
    </QueryBoundary>
  )
}
