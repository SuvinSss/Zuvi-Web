import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight, FileSpreadsheet, PackageOpen, Plus, Search } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { BulkBar, BulkDialog, SelectCheckbox, emptySelection, type BulkActionDef, type Selection } from '@/components/management'
import { ProductImage } from '@/components/ProductImage'
import { Button, Card, EmptyState, ErrorState, Input, PageHeader, Select, Skeleton, StatusBadge, ButtonLink } from '@/components/ui'
import { useAuth } from '@/features/auth/AuthProvider'
import { useDebounced } from '@/hooks/useDebounced'
import { formatMoney } from '@/lib/format'
import { getMeta, listProducts } from '@/services/products'
import type { ProductListItem } from '@/types/api'

const PAGE_SIZE = 20
const SORTS = [
  { value: '-created_at', label: 'Newest first' },
  { value: 'name', label: 'Name A–Z' },
  { value: '-name', label: 'Name Z–A' },
  { value: 'store_price', label: 'Price low → high' },
  { value: '-store_price', label: 'Price high → low' },
  { value: '-updated_at', label: 'Recently updated' },
]

function RowSkeleton() {
  return (
    <div aria-hidden="true" className="flex items-center gap-4 p-4">
      <Skeleton className="size-14 shrink-0" />
      <div className="flex-1 space-y-2"><Skeleton className="h-4 w-1/2" /><Skeleton className="h-3 w-1/3" /></div>
    </div>
  )
}

function ProductRow({ product, selectable, selected, onSelect }: { product: ProductListItem; selectable: boolean; selected: boolean; onSelect: (on: boolean) => void }) {
  return (
    <li className="flex items-stretch">
      {selectable && <div className="grid place-items-center pl-2"><SelectCheckbox label={`Select ${product.name}`} checked={selected} onChange={onSelect} /></div>}
      <Link
        to={`/admin/products/${product.id}`}
        className="grid flex-1 grid-cols-[3.5rem_1fr_auto] items-center gap-x-4 gap-y-1 p-4 transition-colors hover:bg-pale focus-visible:bg-pale md:grid-cols-[3.5rem_minmax(0,2fr)_minmax(0,1fr)_7rem_6rem]"
      >
        <ProductImage image={product.image} name={product.name} className="row-span-2 size-14 md:row-span-1" />
        <div className="min-w-0">
          <p className="truncate font-medium text-ink">{product.name}</p>
          <p className="truncate text-xs text-muted">{product.sku} · {product.product_code}</p>
        </div>
        <div className="hidden min-w-0 md:block">
          <p className="truncate text-sm">{product.category.name}</p>
          <p className="truncate text-xs text-muted">{product.store.name}</p>
        </div>
        <p className="hidden text-right text-sm font-medium tabular-nums md:block">{formatMoney(product.store_price)}</p>
        <div className="flex flex-col items-end gap-1 md:items-start">
          <StatusBadge status={product.status} />
          {product.generated_fields && product.generated_fields.length > 0 && <span className="rounded bg-warn-bg px-1.5 text-xs text-warn" title="Filled in automatically by an import">auto-filled</span>}
          <span className="text-xs tabular-nums text-muted md:hidden">{formatMoney(product.store_price)}</span>
        </div>
      </Link>
    </li>
  )
}

export default function ProductsPage() {
  const { user } = useAuth()
  const [params, setParams] = useSearchParams()
  const [search, setSearch] = useState(params.get('q') ?? '')
  const debounced = useDebounced(search, 300)

  // Keep the URL (and so back/forward, reloads and shared links) as the filter state.
  useEffect(() => {
    setParams((current) => {
      const next = new URLSearchParams(current)
      if (debounced) next.set('q', debounced)
      else next.delete('q')
      if (next.get('q') !== current.get('q')) next.delete('page')
      return next
    }, { replace: true })
  }, [debounced, setParams])

  const page = Math.max(1, Number(params.get('page')) || 1)
  const query = {
    q: params.get('q') ?? '', status: params.get('status') ?? '', category: params.get('category') ?? '',
    has_image: params.get('has_image') ?? '', store: params.get('store') ?? '', ordering: params.get('ordering') ?? '-created_at', page, page_size: PAGE_SIZE,
  }
  const list = useQuery({ queryKey: ['products', query], queryFn: ({ signal }) => listProducts(query, signal), placeholderData: keepPreviousData })
  const meta = useQuery({ queryKey: ['meta'], queryFn: () => getMeta(), staleTime: 5 * 60_000 })

  const setFilter = (key: string, value: string) =>
    setParams((current) => {
      const next = new URLSearchParams(current)
      if (value) next.set(key, value)
      else next.delete(key)
      next.delete('page')
      return next
    })
  const goToPage = (n: number) => setParams((current) => { const next = new URLSearchParams(current); next.set('page', String(n)); return next })

  const qc = useQueryClient()
  const canBulk = Boolean(user?.permissions.change)
  const [selection, setSelection] = useState<Selection>(emptySelection)
  const [bulk, setBulk] = useState<BulkActionDef | null>(null)
  const rows = list.data?.results ?? []
  const allOnPage = rows.length > 0 && rows.every((r) => selection.ids.has(r.id))
  const toggle = (id: number, on: boolean) => setSelection((s) => { const ids = new Set(s.ids); if (on) ids.add(id); else ids.delete(id); return { ids, selectAll: false } })
  const togglePage = (on: boolean) => setSelection((s) => { const ids = new Set(s.ids); rows.forEach((r) => (on ? ids.add(r.id) : ids.delete(r.id))); return { ids, selectAll: false } })
  const bulkFilters = Object.fromEntries(Object.entries({ status: query.status, category: query.category, store: query.store, q: query.q }).filter(([, v]) => v))
  const bulkActions: BulkActionDef[] = [{ action: 'approve', label: 'Approve' }, { action: 'reject', label: 'Reject', needsReason: true, danger: true }, { action: 'deactivate', label: 'Deactivate' }, { action: 'resubmit', label: 'Send for review' },
    ...(meta.data?.can?.pricing ? [{ action: 'set_pricing', label: 'Set margin', fields: [
      { key: 'margin_type', label: 'Margin type', options: [{ value: 'PERCENTAGE', label: 'Percentage of store price' }, { value: 'FIXED', label: 'Fixed amount (₹)' }] },
      { key: 'margin', label: 'Margin', hint: 'Added to each product’s store price. Products where this would sell below cost are left out.' }] }] : [])]
  const totalPages = list.data ? Math.max(1, Math.ceil(list.data.count / PAGE_SIZE)) : 1
  const filtered = Boolean(query.q || query.status || query.category || query.has_image)

  return (
    <>
      <PageHeader
        title="Products"
        subtitle="Search, filter and edit the catalogue. Photos are optimized automatically."
        actions={user?.permissions.add && (
          <>
            <ButtonLink to="/admin/products/import" variant="outline" icon={FileSpreadsheet}>Import</ButtonLink>
            <ButtonLink to="/admin/products/new" icon={Plus}>New product</ButtonLink>
          </>
        )}
      />

      <Card className="mb-4 p-3 sm:p-4">
        <form role="search" onSubmit={(event) => event.preventDefault()} className="grid gap-3 sm:grid-cols-2 lg:grid-cols-[2fr_1fr_1fr_1fr_1fr]">
          <div className="relative sm:col-span-2 lg:col-span-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted" aria-hidden="true" />
            <Input aria-label="Search products" type="search" placeholder="Search name, SKU or code" className="pl-9" value={search} onChange={(event) => setSearch(event.target.value)} />
          </div>
          <Select aria-label="Status" value={query.status} onChange={(event) => setFilter('status', event.target.value)}>
            <option value="">All statuses</option>
            {(meta.data?.statuses ?? []).map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
          </Select>
          <Select aria-label="Category" value={query.category} onChange={(event) => setFilter('category', event.target.value)}>
            <option value="">All categories</option>
            {(meta.data?.categories ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </Select>
          <Select aria-label="Photo" value={query.has_image} onChange={(event) => setFilter('has_image', event.target.value)}>
            <option value="">Any photo status</option>
            <option value="true">With photo</option>
            <option value="false">Missing photo</option>
          </Select>
          <Select aria-label="Sort by" value={query.ordering} onChange={(event) => setFilter('ordering', event.target.value)}>
            {SORTS.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
          </Select>
        </form>
      </Card>

      {query.store && <p className="mb-3 text-sm">Showing one store’s products. <button type="button" className="font-medium text-forest underline" onClick={() => setFilter('store', '')}>Show all stores</button></p>}
      {canBulk && <BulkBar selection={selection} pageCount={rows.length} total={list.data?.count ?? 0} actions={bulkActions} onAction={setBulk} onSelectAll={() => setSelection((s) => ({ ...s, selectAll: true }))} onClear={() => setSelection(emptySelection())} />}
      <Card className="overflow-hidden">
        {list.isPending ? (
          <div role="status" aria-label="Loading products" className="divide-y divide-line">{Array.from({ length: 6 }, (_, i) => <RowSkeleton key={i} />)}</div>
        ) : list.isError ? (
          <ErrorState message="The product list could not be loaded." onRetry={() => void list.refetch()} />
        ) : list.data.results.length === 0 ? (
          <EmptyState
            icon={PackageOpen}
            title={filtered ? 'No products match these filters' : 'No products yet'}
            action={filtered ? <Button variant="outline" onClick={() => { setSearch(''); setParams({}) }}>Clear filters</Button> : user?.permissions.add ? <ButtonLink to="/admin/products/new" icon={Plus}>Add your first product</ButtonLink> : undefined}
          >
            {filtered ? 'Try a different search or clear the filters.' : 'Create a product, or import many at once from an Excel file.'}
          </EmptyState>
        ) : (
          <>
            <div aria-hidden="true" className="hidden grid-cols-[3.5rem_minmax(0,2fr)_minmax(0,1fr)_7rem_6rem] gap-x-4 border-b border-line bg-canvas px-4 py-2 text-xs font-semibold uppercase tracking-wide text-muted md:grid">
              <span /><span>Product</span><span>Category / store</span><span className="text-right">Store price</span><span>Status</span>
            </div>
            <ul className={`divide-y divide-line transition-opacity ${list.isPlaceholderData ? 'opacity-60' : ''}`}>
              {list.data.results.map((product) => <ProductRow key={product.id} product={product} selectable={canBulk} selected={selection.selectAll || selection.ids.has(product.id)} onSelect={(on) => toggle(product.id, on)} />)}
            </ul>
            <nav aria-label="Pagination" className="flex items-center justify-between gap-3 border-t border-line p-3">
              {canBulk && <label className="flex items-center gap-2 text-sm text-muted"><SelectCheckbox label="Select all products on this page" checked={allOnPage || selection.selectAll} indeterminate={!allOnPage && rows.some((r) => selection.ids.has(r.id))} onChange={togglePage} />Select page</label>}
              <p className="text-sm text-muted">{list.data.count} product{list.data.count === 1 ? '' : 's'} · page {page} of {totalPages}</p>
              <div className="flex gap-2">
                <Button variant="outline" icon={ChevronLeft} disabled={page <= 1} onClick={() => goToPage(page - 1)} aria-label="Previous page" />
                <Button variant="outline" icon={ChevronRight} disabled={page >= totalPages} onClick={() => goToPage(page + 1)} aria-label="Next page" />
              </div>
            </nav>
          </>
        )}
      </Card>
      <BulkDialog module="products" def={bulk} selection={selection} filters={bulkFilters} total={list.data?.count ?? 0} onClose={() => setBulk(null)}
        onDone={() => { setSelection(emptySelection()); void qc.invalidateQueries({ queryKey: ['products'] }); void qc.invalidateQueries({ queryKey: ['admin-counts'] }); void qc.invalidateQueries({ queryKey: ['admin-approvals'] }) }} />
    </>
  )
}
