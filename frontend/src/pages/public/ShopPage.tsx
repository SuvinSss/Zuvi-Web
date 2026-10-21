import { useQuery } from '@tanstack/react-query'
import { Package, SlidersHorizontal } from 'lucide-react'
import { useState } from 'react'
import { Pagination, QueryBoundary } from '@/components/kit'
import { ProductCard } from '@/components/shop'
import { Button, Field, Input, PageHeader, Select } from '@/components/ui'
import { useUrlState } from '@/hooks/useUrlState'
import { listCategories, listPublicProducts, listPublicStores } from '@/services/platform'

const KEYS = ['q', 'category', 'store', 'ordering', 'min_price', 'max_price'] as const
const PAGE_SIZE = 20

export default function ShopPage() {
  const { values, page, set } = useUrlState(KEYS)
  const [showFilters, setShowFilters] = useState(false)
  const categories = useQuery({ queryKey: ['categories'], queryFn: listCategories, staleTime: 10 * 60_000 })
  const stores = useQuery({ queryKey: ['stores', 'all'], queryFn: () => listPublicStores({}), staleTime: 5 * 60_000 })
  const products = useQuery({
    queryKey: ['products', values, page],
    queryFn: ({ signal }) => listPublicProducts({ ...values, page, page_size: PAGE_SIZE }, signal),
    placeholderData: (previous) => previous,
  })
  const active = [values.category, values.store, values.min_price, values.max_price].filter(Boolean).length

  return (
    <>
      <PageHeader title={values.q ? `Results for “${values.q}”` : 'Shop'} subtitle={products.data ? `${products.data.count} product${products.data.count === 1 ? '' : 's'}` : undefined}
        actions={<Button variant="outline" icon={SlidersHorizontal} aria-expanded={showFilters} aria-controls="filters" onClick={() => setShowFilters((s) => !s)}>Filters{active ? ` (${active})` : ''}</Button>} />

      <div id="filters" hidden={!showFilters} className="mb-5 grid gap-3 rounded-card border border-line bg-white p-4 sm:grid-cols-2 lg:grid-cols-5">
        <Field label="Category">{(p) => (
          <Select {...p} value={values.category} onChange={(e) => set({ category: e.target.value })}>
            <option value="">All categories</option>{categories.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </Select>)}</Field>
        <Field label="Store">{(p) => (
          <Select {...p} value={values.store} onChange={(e) => set({ store: e.target.value })}>
            <option value="">All stores</option>{stores.data?.results.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </Select>)}</Field>
        <Field label="Sort by">{(p) => (
          <Select {...p} value={values.ordering} onChange={(e) => set({ ordering: e.target.value })}>
            <option value="">Name (A–Z)</option><option value="price">Price: low to high</option><option value="-price">Price: high to low</option><option value="newest">Newest</option>
          </Select>)}</Field>
        <Field label="Min price (₹)">{(p) => <Input {...p} type="number" inputMode="decimal" min="0" value={values.min_price} onChange={(e) => set({ min_price: e.target.value })} />}</Field>
        <Field label="Max price (₹)">{(p) => <Input {...p} type="number" inputMode="decimal" min="0" value={values.max_price} onChange={(e) => set({ max_price: e.target.value })} />}</Field>
        {(active > 0 || values.q) && <div className="sm:col-span-2 lg:col-span-5"><Button variant="ghost" onClick={() => set({ q: '', category: '', store: '', ordering: '', min_price: '', max_price: '' })}>Clear all filters</Button></div>}
      </div>

      <QueryBoundary query={products} skeleton="cards" isEmpty={products.data?.count === 0}
        empty={{ icon: Package, title: 'Nothing matches your search', text: 'Try a different word, or clear the filters.', action: <Button variant="outline" onClick={() => set({ q: '', category: '', store: '', min_price: '', max_price: '' })}>Clear filters</Button> }}>
        <div className={`grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 ${products.isFetching ? 'opacity-70' : ''}`}>{products.data?.results.map((p) => <ProductCard key={p.id} product={p} />)}</div>
        <Pagination page={page} count={products.data?.count ?? 0} pageSize={PAGE_SIZE} onPage={(n) => set({ page: n })} />
      </QueryBoundary>
    </>
  )
}
