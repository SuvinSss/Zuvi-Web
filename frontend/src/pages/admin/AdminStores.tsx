import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Store } from 'lucide-react'
import { useState } from 'react'
import { DataTable, Pagination, QueryBoundary, ReasonDialog, Segmented, Status, useToast } from '@/components/kit'
import { Button, Input, PageHeader } from '@/components/ui'
import { useUrlState } from '@/hooks/useUrlState'
import { errorMessage } from '@/lib/api'
import { adminStores, setStoreStatus } from '@/services/ops'
import type { AdminStore } from '@/types/ops'

const NEXT: Record<string, [string, string, boolean][]> = {
  PENDING: [['ACTIVE', 'Approve', false], ['REJECTED', 'Reject', true]],
  ACTIVE: [['SUSPENDED', 'Suspend', true]],
  SUSPENDED: [['ACTIVE', 'Reactivate', false]],
  REJECTED: [['PENDING', 'Reopen', false]],
}
const REASON_REQUIRED = new Set(['REJECTED', 'SUSPENDED'])

export default function AdminStores() {
  const qc = useQueryClient()
  const toast = useToast()
  const { values, page, set } = useUrlState(['status', 'q'] as const)
  const q = useQuery({ queryKey: ['admin-stores', values, page], queryFn: () => adminStores({ ...values, page }), placeholderData: (p) => p })
  const [pending, setPending] = useState<{ store: AdminStore; status: string; text: string } | null>(null)
  const change = useMutation({
    mutationFn: (v: { id: number; status: string; reason?: string }) => setStoreStatus(v.id, v.status, v.reason),
    onSuccess: () => { toast('success', 'Store updated.'); setPending(null); void qc.invalidateQueries({ queryKey: ['admin-stores'] }) },
    onError: (e) => toast('error', errorMessage(e)),
  })
  const start = (store: AdminStore, status: string, text: string) => (REASON_REQUIRED.has(status) ? setPending({ store, status, text }) : change.mutate({ id: store.id, status }))
  return (
    <>
      <PageHeader title="Stores" />
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <Segmented label="Status" value={values.status} onChange={(v) => set({ status: v })} options={[{ value: '', label: 'All' }, { value: 'PENDING', label: 'Pending' }, { value: 'ACTIVE', label: 'Active' }, { value: 'SUSPENDED', label: 'Suspended' }, { value: 'REJECTED', label: 'Rejected' }]} />
        <label className="min-w-[12rem] flex-1 text-sm sm:max-w-xs">Search<Input className="mt-1" type="search" defaultValue={values.q} placeholder="Name or code" onKeyDown={(e) => e.key === 'Enter' && set({ q: e.currentTarget.value })} onBlur={(e) => e.target.value !== values.q && set({ q: e.target.value })} /></label>
      </div>
      <QueryBoundary query={q} isEmpty={q.data?.count === 0} empty={{ icon: Store, title: 'No stores match' }}>
        <DataTable caption="Stores" rows={q.data?.results ?? []} rowKey={(s) => s.id}
          columns={[
            { key: 'n', header: 'Store', primary: true, cell: (s) => <><strong>{s.name}</strong><br /><span className="text-xs text-muted">{String(s.store_code ?? '')}</span></> },
            { key: 'c', header: 'City', cell: (s) => String(s.city ?? '—') },
            { key: 'cat', header: 'Category', cell: (s) => String(s.category ?? '—') },
            { key: 'r', header: 'Rating', cell: (s) => { const r = s.rating as { average: number; count: number } | undefined; return r?.count ? `${r.average.toFixed(1)} (${r.count})` : '—' } },
            { key: 's', header: 'Status', cell: (s) => <Status value={s.status} /> },
            { key: 'a', header: 'Actions', cell: (s) => <span className="flex flex-wrap gap-2">{(NEXT[s.status] ?? []).map(([to, text, danger]) => <Button key={to} className="min-h-9" variant={danger ? 'danger' : 'secondary'} loading={change.isPending && change.variables?.id === s.id} onClick={() => start(s, to, text)}>{text}</Button>)}</span> },
          ]} />
        <Pagination page={page} count={q.data?.count ?? 0} onPage={(n) => set({ page: n })} />
      </QueryBoundary>
      <ReasonDialog open={!!pending} title={`${pending?.text} ${pending?.store.name}?`} field="Reason (shown to the store)" confirm={pending?.text ?? ''} danger busy={change.isPending} onClose={() => setPending(null)} onSubmit={(reason) => pending && change.mutate({ id: pending.store.id, status: pending.status, reason })} />
    </>
  )
}
