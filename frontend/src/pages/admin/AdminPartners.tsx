import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Bike } from 'lucide-react'
import { useState } from 'react'
import { DataTable, Pagination, QueryBoundary, ReasonDialog, Segmented, Status, useToast } from '@/components/kit'
import { Button, PageHeader } from '@/components/ui'
import { useUrlState } from '@/hooks/useUrlState'
import { errorMessage } from '@/lib/api'
import { formatDate } from '@/lib/format'
import { label } from '@/lib/labels'
import { adminPartners, partnerDecision } from '@/services/ops'
import type { PartnerRecord } from '@/types/ops'
import { PARTNER_STATUS } from '../delivery/labels'

export default function AdminPartners() {
  const qc = useQueryClient()
  const toast = useToast()
  const { values, page, set } = useUrlState(['status'] as const)
  const q = useQuery({ queryKey: ['admin-partners', values.status, page], queryFn: () => adminPartners({ status: values.status, page }), placeholderData: (p) => p })
  const [pending, setPending] = useState<{ p: PartnerRecord; action: 'reject' | 'suspend' } | null>(null)
  const decide = useMutation({
    mutationFn: (v: { id: number; action: 'approve' | 'reject' | 'suspend'; reason?: string }) => partnerDecision(v.id, v.action, v.reason),
    onSuccess: () => { toast('success', 'Partner updated.'); setPending(null); void qc.invalidateQueries({ queryKey: ['admin-partners'] }) },
    onError: (e) => toast('error', errorMessage(e)),
  })
  return (
    <>
      <PageHeader title="Delivery partners" />
      <div className="mb-4"><Segmented label="Status" value={values.status} onChange={(v) => set({ status: v })} options={[{ value: '', label: 'All' }, ...Object.entries(PARTNER_STATUS).map(([value, l]) => ({ value, label: l }))]} /></div>
      <QueryBoundary query={q} isEmpty={q.data?.count === 0} empty={{ icon: Bike, title: 'No partners match' }}>
        <DataTable caption="Delivery partners" rows={q.data?.results ?? []} rowKey={(p) => p.id}
          columns={[
            { key: 'n', header: 'Partner', primary: true, cell: (p) => <><strong>{p.full_name || p.username}</strong><br /><span className="text-xs text-muted">@{p.username}</span></> },
            { key: 'v', header: 'Vehicle', cell: (p) => `${label({}, p.vehicle_type)}${p.vehicle_number ? ` · ${p.vehicle_number}` : ''}` },
            { key: 's', header: 'Status', cell: (p) => <Status value={p.status} label={label(PARTNER_STATUS, p.status)} /> },
            { key: 'o', header: 'Online', cell: (p) => (p.is_online ? 'Online' : 'Offline') },
            { key: 'l', header: 'Last location', cell: (p) => (p.last_location_at ? new Date(p.last_location_at).toLocaleString('en-IN') : '—') },
            { key: 'j', header: 'Applied', cell: (p) => formatDate(p.created_at) },
            { key: 'a', header: 'Actions', cell: (p) => (
              <span className="flex flex-wrap gap-2">
                {['PENDING', 'SUSPENDED'].includes(p.status) && <Button size="sm" variant="outline" loading={decide.isPending && decide.variables?.id === p.id} onClick={() => decide.mutate({ id: p.id, action: 'approve' })}>{p.status === 'PENDING' ? 'Approve' : 'Reinstate'}</Button>}
                {p.status === 'PENDING' && <Button size="sm" variant="destructive" onClick={() => setPending({ p, action: 'reject' })}>Reject</Button>}
                {p.status === 'APPROVED' && <Button size="sm" variant="destructive" onClick={() => setPending({ p, action: 'suspend' })}>Suspend</Button>}
              </span>) },
          ]} />
        <Pagination page={page} count={q.data?.count ?? 0} onPage={(n) => set({ page: n })} />
      </QueryBoundary>
      <ReasonDialog open={!!pending} title={`${pending?.action === 'reject' ? 'Reject' : 'Suspend'} ${pending?.p.full_name || pending?.p.username}?`} field="Reason (shown to the partner)" confirm={pending?.action === 'reject' ? 'Reject' : 'Suspend'} danger busy={decide.isPending} onClose={() => setPending(null)} onSubmit={(reason) => pending && decide.mutate({ id: pending.p.id, action: pending.action, reason })} />
    </>
  )
}
