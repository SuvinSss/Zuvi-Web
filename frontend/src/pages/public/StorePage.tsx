import { useQuery } from '@tanstack/react-query'
import { MapPin, Navigation, Package, Store } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Pagination, QueryBoundary, Section, Stars } from '@/components/kit'
import { ProductCard } from '@/components/shop'
import { ReviewList } from '@/components/reviews'
import { googleMapsDirections, MapView } from '@/components/location/MapView'
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
          {s.location && (
            <Section title="Location">
              <Card className="grid gap-4 p-4 md:grid-cols-[minmax(0,1fr)_16rem]">
                <MapView height={240} label={`${s.name} on the map`} markers={[{ lat: s.location.latitude, lon: s.location.longitude, label: s.name, color: '#b45309' }]} fitToMarkers zoom={16} />
                <div className="space-y-3 text-sm">
                  <p className="flex gap-2"><MapPin className="mt-0.5 size-4 shrink-0 text-emerald" aria-hidden="true" />{s.location.address}</p>
                  <a className="inline-flex min-h-11 items-center gap-2 font-semibold text-forest underline" target="_blank" rel="noreferrer"
                    href={googleMapsDirections([s.location.latitude, s.location.longitude], null, 'driving')}><Navigation className="size-4" aria-hidden="true" />Get directions</a>
                </div>
              </Card>
            </Section>
          )}
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
