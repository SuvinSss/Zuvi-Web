import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Star } from 'lucide-react'
import { useState } from 'react'
import { Pagination, QueryBoundary, ReasonDialog, Segmented, Stars, Status, useToast } from '@/components/kit'
import { Button, Card, PageHeader, Select } from '@/components/ui'
import { useUrlState } from '@/hooks/useUrlState'
import { errorMessage } from '@/lib/api'
import { formatDate } from '@/lib/format'
import { adminReviews, moderateReview } from '@/services/ops'
import type { AdminReview } from '@/types/ops'

const STATUS: Record<string, string> = { PUBLISHED: 'Published', HIDDEN: 'Hidden', REJECTED: 'Rejected', WITHDRAWN: 'Withdrawn', PENDING: 'Pending' }
const TARGET: Record<string, string> = { STORE: 'Store', PRODUCT: 'Product', DELIVERY_PARTNER: 'Delivery partner' }

export default function AdminReviews() {
  const qc = useQueryClient()
  const toast = useToast()
  const { values, page, set } = useUrlState(['status', 'target_type', 'reported'] as const)
  const q = useQuery({ queryKey: ['admin-reviews', values, page], queryFn: () => adminReviews({ ...values, page }), placeholderData: (p) => p })
  const [pending, setPending] = useState<{ r: AdminReview; action: 'hide' | 'reject' } | null>(null)
  const mod = useMutation({
    mutationFn: (v: { id: number; action: 'hide' | 'reject' | 'restore'; reason?: string }) => moderateReview(v.id, v.action, v.reason),
    onSuccess: () => { toast('success', 'Review updated.'); setPending(null); void qc.invalidateQueries({ queryKey: ['admin-reviews'] }) },
    onError: (e) => toast('error', errorMessage(e)),
  })
  return (
    <>
      <PageHeader title="Review moderation" />
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <Segmented label="Reports" value={values.reported} onChange={(v) => set({ reported: v })} options={[{ value: '', label: 'All' }, { value: '1', label: 'Reported' }]} />
        <label className="text-sm">Status<Select className="mt-1" value={values.status} onChange={(e) => set({ status: e.target.value })}><option value="">Any</option>{Object.entries(STATUS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</Select></label>
        <label className="text-sm">About<Select className="mt-1" value={values.target_type} onChange={(e) => set({ target_type: e.target.value })}><option value="">Anything</option>{Object.entries(TARGET).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</Select></label>
      </div>
      <QueryBoundary query={q} isEmpty={q.data?.count === 0} empty={{ icon: Star, title: 'No reviews match' }}>
        <ul className="space-y-3">
          {q.data?.results.map((r) => (
            <li key={r.id}><Card className="p-4">
              <div className="flex flex-wrap items-center justify-between gap-2"><div className="flex items-center gap-2"><Stars value={r.rating} /><span className="text-sm">{r.reviewer} · {TARGET[r.target_type] ?? r.target_type} · order {r.store_order_number}</span></div><div className="flex items-center gap-2">{r.report_count > 0 && <span className="rounded-full bg-danger/10 px-2 py-0.5 text-xs text-danger">{r.report_count} report{r.report_count > 1 ? 's' : ''}</span>}<Status value={r.status} label={STATUS[r.status] ?? r.status} /></div></div>
              {r.title && <p className="mt-1 font-semibold">{r.title}</p>}
              {r.comment && <p className="mt-1 whitespace-pre-line break-words text-sm">{r.comment}</p>}
              <p className="mt-1 text-xs text-muted">{formatDate(r.created_at)}{r.moderation_reason ? ` · Moderation: ${r.moderation_reason}` : ''}</p>
              <div className="mt-3 flex flex-wrap gap-2">
                {r.status === 'PUBLISHED' && <><Button variant="secondary" onClick={() => setPending({ r, action: 'hide' })}>Hide</Button><Button variant="danger" onClick={() => setPending({ r, action: 'reject' })}>Reject</Button></>}
                {['HIDDEN', 'REJECTED'].includes(r.status) && <Button variant="secondary" loading={mod.isPending && mod.variables?.id === r.id} onClick={() => mod.mutate({ id: r.id, action: 'restore' })}>Restore</Button>}
              </div>
            </Card></li>
          ))}
        </ul>
        <Pagination page={page} count={q.data?.count ?? 0} onPage={(n) => set({ page: n })} />
      </QueryBoundary>
      <ReasonDialog open={!!pending} title={`${pending?.action === 'hide' ? 'Hide' : 'Reject'} this review?`} field="Reason (recorded in the audit log)" confirm={pending?.action === 'hide' ? 'Hide' : 'Reject'} busy={mod.isPending} onClose={() => setPending(null)} onSubmit={(reason) => pending && mod.mutate({ id: pending.r.id, action: pending.action, reason })} />
    </>
  )
}
