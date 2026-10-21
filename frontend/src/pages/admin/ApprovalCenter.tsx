import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, CheckCircle2, ClipboardCheck } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'
import { BulkBar, BulkDialog, SelectCheckbox, emptySelection, type BulkActionDef, type Selection } from '@/components/management'
import { DataTable, Pagination, QueryBoundary, Status } from '@/components/kit'
import { Alert, ButtonLink, Card, PageHeader } from '@/components/ui'
import { useUrlState } from '@/hooks/useUrlState'
import { formatMoney } from '@/lib/format'
import { approvalCenter, listStores } from '@/services/management'
import { adminPartners } from '@/services/ops'
import { listProducts } from '@/services/products'
import type { BulkModule } from '@/types/management'

export default function ApprovalCenter() {
  const q = useQuery({ queryKey: ['admin-approvals'], queryFn: approvalCenter, refetchInterval: 60_000 })
  return (
    <>
      <PageHeader title="Approval center" subtitle="Everything waiting for a decision, in one place." />
      <QueryBoundary query={q} isEmpty={q.data?.total === 0} empty={{ icon: CheckCircle2, title: 'Nothing is waiting for approval', text: 'New products, stores and partners will appear here.' }}>
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {q.data?.queues.map((queue) => (
            <Card key={queue.key} className="flex flex-col p-4">
              <div className="flex items-start justify-between gap-3"><h2 className="font-semibold text-forest">{queue.title}</h2><span className={`rounded-full px-2.5 py-0.5 text-sm font-semibold tabular-nums ${queue.count ? 'bg-warn-bg text-warn' : 'bg-canvas text-muted'}`}>{queue.count}</span></div>
              {queue.items.length > 0 ? (
                <ul className="mt-3 flex-1 space-y-1 text-sm">{queue.items.map((item) => <li key={item.id} className="truncate">{item.label}{Array.isArray(item.generated) && item.generated.length > 0 && <span className="ml-2 rounded bg-warn-bg px-1.5 text-xs text-warn">auto-filled</span>}</li>)}</ul>
              ) : <p className="mt-3 flex-1 text-sm text-muted">All clear.</p>}
              {queue.count > 0 && <ButtonLink className="mt-4 self-start" size="sm" variant="secondary" to={queue.link} icon={ArrowRight}>Review {queue.count}</ButtonLink>}
            </Card>
          ))}
        </div>
        {(q.data?.not_available.length ?? 0) > 0 && <p className="mt-4 text-xs text-muted">Not available yet: {q.data?.not_available.join('; ')}.</p>}
      </QueryBoundary>
    </>
  )
}

interface Row { id: number; cells: ReactNode[] }
interface ModuleConfig {
  title: string; module: BulkModule; headers: string[]; actions: BulkActionDef[]; filters: Record<string, string>
  fetch: (page: number) => Promise<{ count: number; rows: Row[] }>
}
const CONFIG: Record<string, ModuleConfig> = {
  products: {
    title: 'Products awaiting approval', module: 'products', headers: ['Product', 'Store', 'Store price', 'Notes'],
    actions: [{ action: 'approve', label: 'Approve' }, { action: 'reject', label: 'Reject', needsReason: true, danger: true }], filters: { status: 'PENDING' },
    fetch: async (page) => {
      const d = await listProducts({ status: 'PENDING', ordering: 'created_at', page, page_size: 20 })
      return { count: d.count, rows: d.results.map((p) => ({ id: p.id, cells: [<Link key="n" className="font-medium text-forest underline" to={`/admin/products/${p.id}`}>{p.name}</Link>, p.store.name, formatMoney(p.store_price),
        p.generated_fields?.length ? <span key="g" className="rounded bg-warn-bg px-1.5 text-xs text-warn">auto-filled: {p.generated_fields.join(', ')}</span> : p.image ? '' : <span key="i" className="text-xs text-muted">No photo</span>] })) }
    },
  },
  stores: {
    title: 'Store applications', module: 'stores', headers: ['Store', 'City', 'Verification'],
    actions: [{ action: 'approve', label: 'Approve' }, { action: 'reject', label: 'Reject', needsReason: true, danger: true }], filters: { status: 'PENDING' },
    fetch: async (page) => {
      const d = await listStores({ status: 'PENDING', ordering: 'created_at', page })
      return { count: d.count, rows: d.results.map((s) => ({ id: s.id, cells: [<Link key="n" className="font-medium text-forest underline" to={`/admin/stores/${s.id}`}>{s.name}</Link>, s.city || '—', <Status key="v" value={s.verification_status} />] })) }
    },
  },
  partners: {
    title: 'Delivery partner applications', module: 'partners', headers: ['Partner', 'Vehicle', 'Applied'],
    actions: [{ action: 'approve', label: 'Approve' }, { action: 'reject', label: 'Reject', needsReason: true, danger: true }], filters: { status: 'PENDING' },
    fetch: async (page) => {
      const d = await adminPartners({ status: 'PENDING', page })
      return { count: d.count, rows: d.results.map((p) => ({ id: p.id, cells: [p.full_name || p.username, `${p.vehicle_type}${p.vehicle_number ? ` · ${p.vehicle_number}` : ''}`, new Date(p.created_at).toLocaleDateString('en-IN')] })) }
    },
  },
}

/** A pending queue with selection, "select all N matching" and the shared preview-confirm-result dialog. */
export function ApprovalQueue() {
  const { module = '' } = useParams()
  const cfg = CONFIG[module]
  const qc = useQueryClient()
  const { page, set } = useUrlState([] as const)
  const q = useQuery({ queryKey: ['approval-queue', module, page], queryFn: () => (cfg as ModuleConfig).fetch(page), enabled: Boolean(cfg), placeholderData: (p) => p })
  const [selection, setSelection] = useState<Selection>(emptySelection)
  const [def, setDef] = useState<BulkActionDef | null>(null)
  if (!cfg) return <Alert tone="error">That approval queue does not exist.</Alert>
  const rows = q.data?.rows ?? []
  const allOnPage = rows.length > 0 && rows.every((r) => selection.ids.has(r.id))
  const toggle = (id: number, on: boolean) => setSelection((s) => { const ids = new Set(s.ids); if (on) ids.add(id); else ids.delete(id); return { ids, selectAll: false } })
  const togglePage = (on: boolean) => setSelection((s) => { const ids = new Set(s.ids); rows.forEach((r) => (on ? ids.add(r.id) : ids.delete(r.id))); return { ids, selectAll: false } })
  return (
    <>
      <PageHeader title={cfg.title} subtitle="Select records, review the preview, then confirm. Records that cannot be approved are listed with the reason." actions={<ButtonLink variant="outline" to="/admin/approvals" icon={ClipboardCheck}>All queues</ButtonLink>} />
      <BulkBar selection={selection} pageCount={rows.length} total={q.data?.count ?? 0} actions={cfg.actions} onAction={setDef} onSelectAll={() => setSelection((s) => ({ ...s, selectAll: true }))} onClear={() => setSelection(emptySelection())} />
      <QueryBoundary query={q} isEmpty={q.data?.count === 0} empty={{ icon: CheckCircle2, title: 'Nothing waiting here' }}>
        <DataTable caption={cfg.title} rows={rows} rowKey={(r) => r.id}
          columns={[
            { key: 'sel', header: '', className: 'w-10', cell: (r) => <SelectCheckbox label={`Select row ${r.id}`} checked={selection.selectAll || selection.ids.has(r.id)} onChange={(on) => toggle(r.id, on)} /> },
            ...cfg.headers.map((h, i) => ({ key: h, header: h, primary: i === 0, cell: (r: Row) => r.cells[i] })),
          ]} />
        <div className="mt-2 flex items-center gap-2 text-sm text-muted"><SelectCheckbox label="Select all on this page" checked={allOnPage || selection.selectAll} indeterminate={!allOnPage && rows.some((r) => selection.ids.has(r.id))} onChange={togglePage} /><span>Select this page</span></div>
        <Pagination page={page} count={q.data?.count ?? 0} onPage={(n) => { set({ page: n }); setSelection((s) => (s.selectAll ? s : emptySelection())) }} />
      </QueryBoundary>
      <BulkDialog module={cfg.module} def={def} selection={selection} filters={cfg.filters} total={q.data?.count ?? 0} onClose={() => setDef(null)}
        onDone={() => { setSelection(emptySelection()); void qc.invalidateQueries({ queryKey: ['approval-queue'] }); void qc.invalidateQueries({ queryKey: ['admin-approvals'] }); void qc.invalidateQueries({ queryKey: ['admin-counts'] }); void qc.invalidateQueries({ queryKey: ['products'] }); void qc.invalidateQueries({ queryKey: ['admin-stores'] }) }} />
    </>
  )
}
