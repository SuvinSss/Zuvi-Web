import { useQuery } from '@tanstack/react-query'
import { Search, Store } from 'lucide-react'
import { Pagination, QueryBoundary } from '@/components/kit'
import { StoreCard } from '@/components/shop'
import { Field, Input, PageHeader } from '@/components/ui'
import { useUrlState } from '@/hooks/useUrlState'
import { listPublicStores } from '@/services/platform'

export default function StoresPage() {
  const { values, page, set } = useUrlState(['q'] as const)
  const stores = useQuery({ queryKey: ['stores', values.q, page], queryFn: () => listPublicStores({ q: values.q, page }), placeholderData: (p) => p })
  return (
    <>
      <PageHeader title="Stores" subtitle="Local stores delivering to you." />
      <div className="mb-4 max-w-md">
        <Field label="Search stores">{(p) => (
          <div className="relative"><Search className="pointer-events-none absolute left-3 top-1/2 size-5 -translate-y-1/2 text-muted" aria-hidden="true" />
            <Input {...p} type="search" className="pl-10" value={values.q} onChange={(e) => set({ q: e.target.value })} placeholder="Store name" /></div>)}</Field>
      </div>
      <QueryBoundary query={stores} skeleton="detail" isEmpty={stores.data?.count === 0} empty={{ icon: Store, title: values.q ? 'No stores match that name' : 'No stores are open yet', text: values.q ? 'Check the spelling or clear the search.' : 'Stores appear here once approved.' }}>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{stores.data?.results.map((s) => <StoreCard key={s.id} store={s} />)}</div>
        <Pagination page={page} count={stores.data?.count ?? 0} onPage={(n) => set({ page: n })} />
      </QueryBoundary>
    </>
  )
}
