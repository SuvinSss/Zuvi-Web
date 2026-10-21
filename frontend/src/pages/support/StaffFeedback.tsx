import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { MessageSquare } from 'lucide-react'
import { useState } from 'react'
import { DataTable, Modal, Pagination, QueryBoundary, Segmented, Status, useToast } from '@/components/kit'
import { Alert, Button, Field, PageHeader, Select, Textarea } from '@/components/ui'
import { useUrlState } from '@/hooks/useUrlState'
import { errorMessage } from '@/lib/api'
import { formatDate } from '@/lib/format'
import { escalateFeedback, listFeedback, replyFeedback, setFeedbackStatus } from '@/services/platform'
import type { FeedbackItem } from '@/types/platform'

const STATUSES = ['NEW', 'IN_REVIEW', 'REPLIED', 'ESCALATED', 'CLOSED']

export default function StaffFeedback() {
  const { values, page, set } = useUrlState(['status'] as const)
  const q = useQuery({ queryKey: ['feedback', 'staff', values.status, page], queryFn: () => listFeedback({ status: values.status, page }), placeholderData: (p) => p })
  const [open, setOpen] = useState<number | null>(null)
  const current = q.data?.results.find((f) => f.id === open) ?? null
  return (
    <>
      <PageHeader title="Feedback" />
      <div className="mb-4"><Segmented label="Status" value={values.status} onChange={(v) => set({ status: v })} options={[{ value: '', label: 'All' }, ...STATUSES.map((s) => ({ value: s, label: s.replace('_', ' ').toLowerCase().replace(/^./, (c) => c.toUpperCase()) }))]} /></div>
      <QueryBoundary query={q} isEmpty={q.data?.count === 0} empty={{ icon: MessageSquare, title: 'No feedback' }}>
        <DataTable caption="Feedback" rows={q.data?.results ?? []} rowKey={(f) => f.id} onRowClick={(f) => setOpen(f.id)}
          columns={[
            { key: 'r', header: 'Reference', primary: true, cell: (f) => <button type="button" className="font-semibold text-forest hover:underline" onClick={(e) => { e.stopPropagation(); setOpen(f.id) }}>{f.reference}</button> },
            { key: 'k', header: 'Type', cell: (f) => `${f.kind.toLowerCase()} · ${f.subject_type.toLowerCase()}` },
            { key: 'm', header: 'Message', cell: (f) => <span className="line-clamp-2 break-words">{f.message}</span> },
            { key: 'a', header: 'From', cell: (f) => f.author_name },
            { key: 's', header: 'Status', cell: (f) => <Status value={f.status} /> },
            { key: 'd', header: 'Sent', cell: (f) => formatDate(f.created_at) },
          ]} />
        <Pagination page={page} count={q.data?.count ?? 0} onPage={(n) => set({ page: n })} />
      </QueryBoundary>
      {current && <FeedbackDialog item={current} onClose={() => setOpen(null)} />}
    </>
  )
}

function FeedbackDialog({ item, onClose }: { item: FeedbackItem; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [body, setBody] = useState('')
  const [internal, setInternal] = useState(false)
  const refresh = () => void qc.invalidateQueries({ queryKey: ['feedback'] })
  const err = (e: unknown) => toast('error', errorMessage(e))
  const reply = useMutation({ mutationFn: () => replyFeedback(item.id, body.trim(), internal), onSuccess: () => { toast('success', internal ? 'Note added.' : 'Reply sent.'); setBody(''); refresh() }, onError: err })
  const status = useMutation({ mutationFn: (s: string) => setFeedbackStatus(item.id, s), onSuccess: () => { toast('success', 'Status updated.'); refresh() }, onError: err })
  const escalate = useMutation({ mutationFn: () => escalateFeedback(item.id), onSuccess: () => { toast('success', 'Escalated to support.'); refresh() }, onError: err })
  return (
    <Modal open onClose={onClose} title={`${item.reference} — ${item.kind.toLowerCase()}`}>
      <div className="space-y-4">
        <p className="whitespace-pre-line break-words text-sm">{item.message}</p>
        <p className="text-xs text-muted">From {item.author_name}{item.store_name ? ` about ${item.store_name}` : ''} · {formatDate(item.created_at)}{item.ticket_reference ? ` · Ticket ${item.ticket_reference}` : ''}</p>
        {item.replies.map((r) => <p key={r.id} className={`rounded-control p-3 text-sm ${r.is_internal ? 'bg-warn/10' : 'bg-pale'}`}><strong>{r.is_internal ? 'Internal note' : r.from_support ? 'Support' : 'Customer'}:</strong> {r.body}</p>)}
        <Field label="Status">{(p) => <Select {...p} value={item.status} onChange={(e) => status.mutate(e.target.value)}>{STATUSES.map((s) => <option key={s} value={s}>{s.replace('_', ' ').toLowerCase()}</option>)}</Select>}</Field>
        <Field label="Reply">{(p) => <Textarea {...p} rows={3} maxLength={3000} value={body} onChange={(e) => setBody(e.target.value)} />}</Field>
        <label className="flex min-h-11 items-center gap-2 text-sm"><input type="checkbox" className="size-5" checked={internal} onChange={(e) => setInternal(e.target.checked)} />Internal note (hidden from the sender)</label>
        {reply.isError && <Alert>{errorMessage(reply.error)}</Alert>}
        <div className="flex flex-wrap justify-between gap-2"><Button variant="secondary" loading={escalate.isPending} disabled={item.status === 'ESCALATED'} onClick={() => escalate.mutate()}>Escalate to support</Button><Button loading={reply.isPending} disabled={!body.trim()} onClick={() => reply.mutate()}>{internal ? 'Add note' : 'Send reply'}</Button></div>
      </div>
    </Modal>
  )
}
