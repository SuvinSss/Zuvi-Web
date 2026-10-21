import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Truck } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { EvidencePanel } from '@/components/evidence'
import { DataTable, KeyValue, Modal, Pagination, QueryBoundary, ReasonDialog, Section, Segmented, Status, useToast } from '@/components/kit'
import { Button, Card, Field, PageHeader, Select } from '@/components/ui'
import { useUrlState } from '@/hooks/useUrlState'
import { errorMessage } from '@/lib/api'
import { DELIVERY_STATUS, label } from '@/lib/labels'
import { adminAssign, adminAttempts, adminCancelDelivery, adminDeliveries, adminDelivery, adminPartners, adminRetry } from '@/services/ops'

export function AdminDeliveriesList() {
  const navigate = useNavigate()
  const { values, page, set } = useUrlState(['status', 'needs_attention'] as const)
  const q = useQuery({ queryKey: ['admin-deliveries', values, page], queryFn: () => adminDeliveries({ ...values, page }), placeholderData: (p) => p, refetchInterval: 30_000 })
  return (
    <>
      <PageHeader title="Deliveries" />
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <Segmented label="Attention" value={values.needs_attention} onChange={(v) => set({ needs_attention: v })} options={[{ value: '', label: 'All' }, { value: '1', label: 'Needs attention' }]} />
        <label className="text-sm">Status<Select className="mt-1" value={values.status} onChange={(e) => set({ status: e.target.value })}><option value="">Any</option>{Object.entries(DELIVERY_STATUS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</Select></label>
      </div>
      <QueryBoundary query={q} isEmpty={q.data?.count === 0} empty={{ icon: Truck, title: 'No deliveries match' }}>
        <DataTable caption="Deliveries" rows={q.data?.results ?? []} rowKey={(d) => d.id} onRowClick={(d) => navigate(`/admin/deliveries/${d.id}`)}
          columns={[
            { key: 'id', header: 'Delivery', primary: true, cell: (d) => <Link className="inline-flex min-h-11 items-center font-semibold text-forest hover:underline" to={`/admin/deliveries/${d.id}`} onClick={(e) => e.stopPropagation()}>#{d.id} · {d.store_order_number}</Link> },
            { key: 's', header: 'Status', cell: (d) => <><Status value={d.status} label={label(DELIVERY_STATUS, d.status)} />{d.needs_attention && <span className="ml-2 text-xs text-warn">Needs attention</span>}</> },
            { key: 'st', header: 'Store', cell: (d) => d.store_name },
            { key: 'p', header: 'Partner', cell: (d) => d.partner?.name ?? 'Unassigned' },
            { key: 'r', header: 'Rejections', className: 'text-right tabular-nums', cell: (d) => d.rejection_count },
            { key: 'c', header: 'Created', cell: (d) => new Date(d.created_at).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' }) },
          ]} />
        <Pagination page={page} count={q.data?.count ?? 0} onPage={(n) => set({ page: n })} />
      </QueryBoundary>
    </>
  )
}

export function AdminDeliveryPage() {
  const id = Number(useParams().id)
  const qc = useQueryClient()
  const toast = useToast()
  const q = useQuery({ queryKey: ['admin-delivery', id], queryFn: () => adminDelivery(id) })
  const attempts = useQuery({ queryKey: ['admin-attempts', id], queryFn: () => adminAttempts(id) })
  const [assigning, setAssigning] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const done = () => { void qc.invalidateQueries({ queryKey: ['admin-delivery', id] }); void qc.invalidateQueries({ queryKey: ['admin-attempts', id] }); void qc.invalidateQueries({ queryKey: ['admin-deliveries'] }) }
  const retry = useMutation({ mutationFn: () => adminRetry(id), onSuccess: () => { toast('success', 'Delivery queued for a new attempt.'); done() }, onError: (e) => toast('error', errorMessage(e)) })
  const cancel = useMutation({ mutationFn: (r: string) => adminCancelDelivery(id, r), onSuccess: () => { toast('success', 'Delivery cancelled.'); setCancelling(false); done() }, onError: (e) => toast('error', errorMessage(e)) })
  const d = q.data
  return (
    <QueryBoundary query={q} skeleton="detail">
      {d && (
        <>
          <PageHeader title={`Delivery #${d.id}`} subtitle={`${d.store_order_number} · ${d.store_name}`} actions={<Link className="inline-flex min-h-11 items-center text-sm font-semibold text-forest underline" to="/admin/deliveries">All deliveries</Link>} />
          <div className="grid gap-6 lg:grid-cols-[1fr_22rem]">
            <div className="space-y-6">
              <Card className="p-4"><div className="flex flex-wrap items-center gap-3"><Status value={d.status} label={label(DELIVERY_STATUS, d.status)} />{d.needs_attention && <span className="text-sm font-medium text-warn">Needs attention — automatic assignment stopped</span>}</div>
                <div className="mt-4"><KeyValue rows={[['Attempt', d.attempt_number], ['Partner', d.partner ? `${d.partner.name} (${d.partner.phone})` : 'Unassigned'], ['Customer', d.customer ? `${d.customer.name} (${d.customer.phone})` : '—'], ['Drop-off', [d.dropoff.line1, d.dropoff.city, d.dropoff.postal_code].filter(Boolean).join(', ')], ['Rejections', d.rejection_count], ['Delivered', d.delivered_at ? new Date(d.delivered_at).toLocaleString('en-IN') : '—']]} /></div></Card>
              <Section title="Proof"><EvidencePanel deliveryId={d.id} /></Section>
              <Section title="Attempts"><QueryBoundary query={attempts}><Card className="p-4"><ul className="divide-y divide-line">{attempts.data?.map((a) => <li key={a.number} className="py-2 text-sm"><strong>Attempt {a.number}</strong> · {label({}, a.outcome)}{a.failure_reason && ` · ${label({}, a.failure_reason)}`}{a.failure_note && <p className="text-muted">{a.failure_note}</p>}</li>)}{attempts.data?.length === 0 && <li className="py-2 text-sm text-muted">No attempts recorded.</li>}</ul></Card></QueryBoundary></Section>
            </div>
            <aside className="space-y-3">
              <Card className="space-y-2 p-4"><h2 className="font-semibold text-forest">Actions</h2>
                {['PENDING_ASSIGNMENT', 'OFFERED', 'ACCEPTED', 'AT_STORE'].includes(d.status) && <Button className="w-full" onClick={() => setAssigning(true)}>{d.partner ? 'Reassign partner' : 'Assign a partner'}</Button>}
                {d.status === 'FAILED' && <Button className="w-full" loading={retry.isPending} onClick={() => retry.mutate()}>Retry delivery</Button>}
                {!['DELIVERED', 'CANCELLED'].includes(d.status) && <Button variant="destructive" className="w-full" onClick={() => setCancelling(true)}>Cancel delivery</Button>}
              </Card>
            </aside>
          </div>
          {assigning && <AssignDialog id={d.id} onClose={() => setAssigning(false)} onDone={() => { setAssigning(false); toast('success', 'Partner assigned.'); done() }} />}
          <ReasonDialog open={cancelling} title="Cancel this delivery?" field="Reason" confirm="Cancel delivery" danger busy={cancel.isPending} onClose={() => setCancelling(false)} onSubmit={(r) => cancel.mutate(r)} />
        </>
      )}
    </QueryBoundary>
  )
}

function AssignDialog({ id, onClose, onDone }: { id: number; onClose: () => void; onDone: () => void }) {
  const partners = useQuery({ queryKey: ['admin-partners', 'APPROVED', 1], queryFn: () => adminPartners({ status: 'APPROVED' }) })
  const [partner, setPartner] = useState('')
  const toast = useToast()
  const assign = useMutation({ mutationFn: () => adminAssign(id, Number(partner), 'Assigned by admin'), onSuccess: onDone, onError: (e) => toast('error', errorMessage(e)) })
  return (
    <Modal open onClose={onClose} title="Assign a delivery partner" footer={<><Button variant="outline" onClick={onClose}>Cancel</Button><Button disabled={!partner} loading={assign.isPending} onClick={() => assign.mutate()}>Assign</Button></>}>
      <QueryBoundary query={partners}>
        <Field label="Approved partner" hint="Online partners are listed as such; offline partners can still be assigned.">{(p) => <Select {...p} value={partner} onChange={(e) => setPartner(e.target.value)}><option value="">Choose…</option>{partners.data?.results.map((x) => <option key={x.id} value={x.id}>{x.full_name || x.username} — {x.is_online ? 'online' : 'offline'}</option>)}</Select>}</Field>
      </QueryBoundary>
    </Modal>
  )
}
