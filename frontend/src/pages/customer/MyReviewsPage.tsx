import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Star } from 'lucide-react'
import { useState } from 'react'
import { ConfirmDialog, Modal, Pagination, QueryBoundary, RatingInput, Status, Stars, useToast } from '@/components/kit'
import { Button, Card, Field, Input, PageHeader, Textarea } from '@/components/ui'
import { useUrlState } from '@/hooks/useUrlState'
import { errorMessage } from '@/lib/api'
import { formatDate } from '@/lib/format'
import { listMyReviews, updateReview, withdrawReview } from '@/services/platform'
import type { MyReview } from '@/types/platform'

const STATUS: Record<string, string> = { PUBLISHED: 'Published', HIDDEN: 'Hidden by moderators', REJECTED: 'Rejected', WITHDRAWN: 'Withdrawn', PENDING: 'Awaiting moderation' }

export default function MyReviewsPage() {
  const qc = useQueryClient()
  const toast = useToast()
  const { page, set } = useUrlState([] as const)
  const q = useQuery({ queryKey: ['my-reviews', page], queryFn: () => listMyReviews(page), placeholderData: (p) => p })
  const [edit, setEdit] = useState<MyReview | null>(null)
  const [withdraw, setWithdraw] = useState<MyReview | null>(null)
  const [form, setForm] = useState({ rating: 0, title: '', comment: '' })
  const refresh = () => void qc.invalidateQueries({ queryKey: ['my-reviews'] })
  const save = useMutation({ mutationFn: () => updateReview(edit!.id, form), onSuccess: () => { refresh(); setEdit(null); toast('success', 'Review updated.') }, onError: (e) => toast('error', errorMessage(e)) })
  const del = useMutation({ mutationFn: () => withdrawReview(withdraw!.id), onSuccess: () => { refresh(); setWithdraw(null); toast('success', 'Review withdrawn.') }, onError: (e) => toast('error', errorMessage(e)) })
  return (
    <>
      <PageHeader title="My reviews" />
      <QueryBoundary query={q} isEmpty={q.data?.count === 0} empty={{ icon: Star, title: 'No reviews yet', text: 'After an order is delivered you can review the store from the order page.' }}>
        <ul className="space-y-3">
          {q.data?.results.map((r) => (
            <li key={r.id}><Card className="p-4">
              <div className="flex flex-wrap items-center justify-between gap-2"><div className="flex items-center gap-2"><Stars value={r.rating} /><span className="text-sm text-muted">Order {r.store_order_number} · {formatDate(r.created_at)}</span></div><Status value={r.status} label={STATUS[r.status] ?? r.status} /></div>
              {r.title && <p className="mt-1 font-semibold">{r.title}</p>}
              {r.comment && <p className="mt-1 whitespace-pre-line break-words text-sm">{r.comment}</p>}
              {r.moderation_reason && <p className="mt-1 text-sm text-warn">Moderator note: {r.moderation_reason}</p>}
              {r.reply && <p className="mt-2 rounded-control bg-pale p-3 text-sm"><strong>Store reply:</strong> {r.reply.body}</p>}
              {['PUBLISHED'].includes(r.status) && <div className="mt-3 flex gap-2"><Button variant="outline" onClick={() => { setEdit(r); setForm({ rating: r.rating, title: r.title, comment: r.comment }) }}>Edit</Button><Button variant="ghost" onClick={() => setWithdraw(r)}>Withdraw</Button></div>}
            </Card></li>
          ))}
        </ul>
        <Pagination page={page} count={q.data?.count ?? 0} onPage={(n) => set({ page: n })} />
      </QueryBoundary>
      <Modal open={!!edit} onClose={() => setEdit(null)} title="Edit review" footer={<><Button variant="outline" onClick={() => setEdit(null)}>Cancel</Button><Button loading={save.isPending} onClick={() => save.mutate()}>Save</Button></>}>
        <div className="space-y-3"><RatingInput value={form.rating} onChange={(rating) => setForm({ ...form, rating })} />
          <Field label="Title">{(p) => <Input {...p} maxLength={120} value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />}</Field>
          <Field label="Review">{(p) => <Textarea {...p} rows={4} maxLength={2000} value={form.comment} onChange={(e) => setForm({ ...form, comment: e.target.value })} />}</Field></div>
      </Modal>
      <ConfirmDialog open={!!withdraw} onClose={() => setWithdraw(null)} onConfirm={() => del.mutate()} busy={del.isPending} danger confirmLabel="Withdraw" title="Withdraw this review?" message="It will no longer count towards the store's rating." />
    </>
  )
}
