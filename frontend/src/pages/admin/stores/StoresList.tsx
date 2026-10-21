import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, Plus, Store } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { BulkBar, BulkDialog, ActionMenu, SelectCheckbox, emptySelection, type BulkActionDef, type Selection } from '@/components/management'
import { DataTable, Pagination, QueryBoundary, Segmented, Status } from '@/components/kit'
import { ButtonLink, Input, PageHeader, Select } from '@/components/ui'
import { useUrlState } from '@/hooks/useUrlState'
import { listStores, storeMeta, storesExportUrl } from '@/services/management'
import type { StoreRow } from '@/types/management'

const FILTERS = ['status', 'q', 'category', 'store_type', 'verification', 'ordering'] as const
const BULK: Record<string, BulkActionDef> = {
  approve: { action: 'approve', label: 'Approve' },
  reject: { action: 'reject', label: 'Reject', needsReason: true, danger: true },
  suspend: { action: 'suspend', label: 'Suspend', needsReason: true, danger: true },
  reactivate: { action: 'reactivate', label: 'Reactivate' },
}
/** Which single-store actions make sense for a status (the server still decides). */
const ROW_ACTIONS: Record<string, string[]> = {
  DRAFT: ['approve'], NEEDS_INFO: ['reject'], PENDING: ['approve', 'reject'], ACTIVE: ['suspend'], SUSPENDED: ['reactivate'], REJECTED: [],
}
const STATUS_TABS = [['', 'All'], ['PENDING', 'Pending'], ['NEEDS_INFO', 'Needs info'], ['ACTIVE', 'Active'], ['SUSPENDED', 'Suspended'], ['DRAFT', 'Drafts'], ['REJECTED', 'Rejected']] as const

export default function StoresList() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { values, page, set } = useUrlState(FILTERS)
  const meta = useQuery({ queryKey: ['store-meta'], queryFn: storeMeta, staleTime: 5 * 60_000 })
  const query = { ...values, page }
  const q = useQuery({ queryKey: ['admin-stores', query], queryFn: () => listStores(query), placeholderData: (p) => p })
  const [selection, setSelection] = useState<Selection>(emptySelection)
  const [dialog, setDialog] = useState<{ def: BulkActionDef; selection: Selection } | null>(null)
  const rows = q.data?.results ?? []
  const allOnPage = rows.length > 0 && rows.every((r) => selection.ids.has(r.id))
  const toggle = (id: number, on: boolean) => setSelection((s) => { const ids = new Set(s.ids); if (on) ids.add(id); else ids.delete(id); return { ids, selectAll: false } })
  const togglePage = (on: boolean) => setSelection((s) => { const ids = new Set(s.ids); rows.forEach((r) => (on ? ids.add(r.id) : ids.delete(r.id))); return { ids, selectAll: false } })
  const filtersForServer = Object.fromEntries(Object.entries({ status: values.status, category: values.category, q: values.q }).filter(([, v]) => v))
  const bulkActions = [BULK.approve!, BULK.reject!, BULK.suspend!, BULK.reactivate!]

  return (
    <>
      <PageHeader title="Stores" subtitle="Create, review and manage every store on the platform."
        actions={<>
          <ButtonLink variant="outline" icon={Download} href={storesExportUrl(query)}>Export CSV</ButtonLink>
          {meta.data?.can_add && <ButtonLink icon={Plus} to="/admin/stores/new">Add store</ButtonLink>}
        </>} />
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <Segmented label="Status" value={values.status} onChange={(v) => { set({ status: v }); setSelection(emptySelection()) }} options={STATUS_TABS.map(([value, label]) => ({ value, label }))} />
      </div>
      <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <label className="text-sm">Search<Input className="mt-1" type="search" defaultValue={values.q} placeholder="Name, code, phone or city" onKeyDown={(e) => e.key === 'Enter' && set({ q: e.currentTarget.value })} onBlur={(e) => e.target.value !== values.q && set({ q: e.target.value })} /></label>
        <label className="text-sm">Category<Select className="mt-1" value={values.category} onChange={(e) => set({ category: e.target.value })}><option value="">All categories</option>{meta.data?.categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</Select></label>
        <label className="text-sm">Type<Select className="mt-1" value={values.store_type} onChange={(e) => set({ store_type: e.target.value })}><option value="">All types</option>{meta.data?.types.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}</Select></label>
        <label className="text-sm">Verification<Select className="mt-1" value={values.verification} onChange={(e) => set({ verification: e.target.value })}><option value="">Any</option><option value="UNVERIFIED">Unverified</option><option value="VERIFIED">Verified</option><option value="REJECTED">Verification rejected</option></Select></label>
        <label className="text-sm">Sort<Select className="mt-1" value={values.ordering} onChange={(e) => set({ ordering: e.target.value })}><option value="">Name A–Z</option><option value="-created_at">Newest first</option><option value="created_at">Oldest first</option><option value="city">City</option><option value="status">Status</option></Select></label>
      </div>
      {meta.data?.can_approve && (
        <BulkBar selection={selection} pageCount={rows.length} total={q.data?.count ?? 0} actions={bulkActions}
          onAction={(def) => setDialog({ def, selection })} onSelectAll={() => setSelection((s) => ({ ...s, selectAll: true }))} onClear={() => setSelection(emptySelection())} />
      )}
      <QueryBoundary query={q} isEmpty={q.data?.count === 0} empty={{ icon: Store, title: 'No stores match', text: 'Try different filters, or add a store.' }}>
        <DataTable caption="Stores" rows={rows} rowKey={(s) => s.id}
          columns={[
            ...(meta.data?.can_approve ? [{ key: 'sel', header: '', className: 'w-10', cell: (s: StoreRow) => <SelectCheckbox label={`Select ${s.name}`} checked={selection.selectAll || selection.ids.has(s.id)} onChange={(on) => toggle(s.id, on)} /> }] : []),
            { key: 'n', header: 'Store', primary: true, cell: (s: StoreRow) => <><button type="button" className="text-left font-semibold text-forest underline-offset-2 hover:underline" onClick={() => navigate(`/admin/stores/${s.id}`)}>{s.name}</button><br /><span className="text-xs text-muted">{s.store_code}</span></> },
            { key: 'c', header: 'City', cell: (s: StoreRow) => s.city || '—' },
            { key: 'cat', header: 'Category', cell: (s: StoreRow) => s.category ?? '—' },
            { key: 's', header: 'Status', cell: (s: StoreRow) => <span className="flex flex-wrap items-center gap-1"><Status value={s.status} />{!s.ordering_enabled && s.status === 'ACTIVE' && <Status value="PENDING" label="Not taking orders" />}</span> },
            { key: 'v', header: 'Verification', cell: (s: StoreRow) => <Status value={s.verification_status} /> },
            { key: 'a', header: 'Actions', cell: (s: StoreRow) => (
              <ActionMenu label={`Actions for ${s.name}`} items={[
                { label: 'View details', onSelect: () => navigate(`/admin/stores/${s.id}`) },
                ...(meta.data?.can_change ? [{ label: 'Edit', onSelect: () => navigate(`/admin/stores/${s.id}/edit`) }] : []),
                ...(meta.data?.can_approve ? (ROW_ACTIONS[s.status] ?? []).map((a) => ({ label: BULK[a]!.label, danger: BULK[a]!.danger ?? false, onSelect: () => setDialog({ def: BULK[a]!, selection: { ids: new Set([s.id]), selectAll: false } }) })) : []),
              ]} />) },
          ]} />
        <div className="mt-2 flex items-center gap-2 text-sm text-muted">
          <SelectCheckbox label="Select all stores on this page" checked={allOnPage || selection.selectAll} indeterminate={!allOnPage && rows.some((r) => selection.ids.has(r.id))} onChange={togglePage} />
          <span>Select this page</span>
        </div>
        <Pagination page={page} count={q.data?.count ?? 0} onPage={(n) => set({ page: n })} />
      </QueryBoundary>
      <BulkDialog module="stores" def={dialog?.def ?? null} selection={dialog?.selection ?? emptySelection()} filters={filtersForServer} total={q.data?.count ?? 0}
        onClose={() => setDialog(null)} onDone={() => { setSelection(emptySelection()); void qc.invalidateQueries({ queryKey: ['admin-stores'] }); void qc.invalidateQueries({ queryKey: ['admin-counts'] }) }} />
    </>
  )
}
