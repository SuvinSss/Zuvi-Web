import { useQuery } from '@tanstack/react-query'
import { ArrowRight, Package, Store } from 'lucide-react'
import { Link } from 'react-router-dom'
import { QueryBoundary, Section } from '@/components/kit'
import { ProductCard, StoreCard } from '@/components/shop'
import { Card } from '@/components/ui'
import { listCategories, listPublicProducts, listPublicStores } from '@/services/platform'

export default function HomePage() {
  const categories = useQuery({ queryKey: ['categories'], queryFn: listCategories, staleTime: 10 * 60_000 })
  const stores = useQuery({ queryKey: ['stores', 'home'], queryFn: () => listPublicStores({}) })
  const products = useQuery({ queryKey: ['products', 'home'], queryFn: () => listPublicProducts({ ordering: 'newest', page_size: 8 }) })

  return (
    <div className="space-y-10">
      <section className="rounded-card bg-night px-5 py-8 text-white sm:px-10 sm:py-12">
        <h1 className="max-w-xl text-3xl font-semibold leading-tight sm:text-4xl">Fresh from your local stores, to your door.</h1>
        <p className="mt-3 max-w-lg text-white/75">Order groceries and essentials from nearby stores. Track every delivery from the store to your doorstep.</p>
        <div className="mt-5 flex flex-wrap gap-3">
          <Link to="/shop" className="inline-flex min-h-11 items-center gap-2 rounded-control bg-fresh px-5 text-sm font-semibold text-night hover:bg-emerald hover:text-white">Start shopping <ArrowRight className="size-4" aria-hidden="true" /></Link>
          <Link to="/stores" className="inline-flex min-h-11 items-center rounded-control px-5 text-sm font-semibold text-white ring-1 ring-inset ring-white/30 hover:bg-white/10">Browse stores</Link>
        </div>
      </section>

      <Section title="Shop by category">
        <QueryBoundary query={categories} isEmpty={categories.data?.length === 0} empty={{ icon: Package, title: 'No categories yet', text: 'Categories appear once stores add products.' }}>
          <ul className="flex flex-wrap gap-2">
            {categories.data?.map((c) => (
              <li key={c.id}><Link to={`/shop?category=${c.id}`} className="inline-flex min-h-11 items-center rounded-full border border-line bg-white px-4 text-sm font-medium hover:border-emerald hover:bg-pale">{c.name}</Link></li>
            ))}
          </ul>
        </QueryBoundary>
      </Section>

      <Section title="Newly added" actions={<Link to="/shop" className="inline-flex min-h-11 items-center text-sm font-semibold text-forest hover:underline">See all</Link>}>
        <QueryBoundary query={products} skeleton="cards" isEmpty={products.data?.count === 0} empty={{ icon: Package, title: 'No products available right now', text: 'Check back soon — stores are adding products.' }}>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">{products.data?.results.map((p) => <ProductCard key={p.id} product={p} />)}</div>
        </QueryBoundary>
      </Section>

      <Section title="Stores near you" actions={<Link to="/stores" className="inline-flex min-h-11 items-center text-sm font-semibold text-forest hover:underline">See all</Link>}>
        <QueryBoundary query={stores} skeleton="detail" isEmpty={stores.data?.count === 0} empty={{ icon: Store, title: 'No stores are open yet', text: 'Stores will show up here once they are approved.' }}>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{stores.data?.results.slice(0, 6).map((s) => <StoreCard key={s.id} store={s} />)}</div>
        </QueryBoundary>
      </Section>

      <Card className="flex flex-col items-start justify-between gap-3 p-5 sm:flex-row sm:items-center">
        <div><h2 className="text-lg font-semibold text-forest">Run a store or deliver with us?</h2><p className="text-sm text-muted">Partners sign up here and are approved by our team before they start.</p></div>
        <Link to="/register-partner" className="inline-flex min-h-11 items-center rounded-control bg-forest px-5 text-sm font-semibold text-white hover:bg-deep">Become a delivery partner</Link>
      </Card>
    </div>
  )
}
