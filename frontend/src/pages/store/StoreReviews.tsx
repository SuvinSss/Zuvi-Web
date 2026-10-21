import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Star } from 'lucide-react'
import { useState } from 'react'
import { Modal, Pagination, QueryBoundary, Stars, useToast } from '@/components/kit'
import { Button, Card, Field, PageHeader, Textarea } from '@/components/ui'
import { useUrlState } from '@/hooks/useUrlState'
import { errorMessage } from '@/lib/api'
import { formatDate } from '@/lib/format'
import { listStoreReviews, replyToReview } from '@/services/ops'
import type { PublicReview } from '@/types/platform'

export default function StoreReviews() {
  const qc = useQueryClient()
  const toast = useToast()
  const { page, set } = useUrlState([] as const)
  const q = useQuery({ queryKey: ['store-reviews', page], queryFn: () => listStoreReviews(page), placeholderData: (p) => p })
  const [target, setTarget] = useState<PublicReview | null>(null)
  const [body, setBody] = useState('')
  const reply = useMutation({
    mutationFn: () => replyToReview(target!.id, body.trim()),
    onSuccess: () => { toast('success', 'Reply published.'); setTarget(null); setBody(''); void qc.invalidateQueries({ queryKey: ['store-reviews'] }) },
    onError: (e) => toast('error', errorMessage(e)),
  })
  return (
    <>
      <PageHeader title="Customer reviews" subtitle="You can reply once to each review. Replies are public. Ratings cannot be changed." />
      <QueryBoundary query={q} isEmpty={q.data?.count === 0} empty={{ icon: Star, title: 'No reviews yet', text: 'Reviews appear after customers receive their orders.' }}>
        <ul className="space-y-3">
          {q.data?.results.map((r) => (
            <li key={r.id}><Card className="p-4">
              <div className="flex flex-wrap items-center justify-between gap-2"><div className="flex items-center gap-2"><Stars value={r.rating} /><span className="text-sm font-medium">{r.reviewer}</span></div><span className="text-xs text-muted">{formatDate(r.created_at)}</span></div>
              {r.title && <p className="mt-1 font-semibold">{r.title}</p>}
              {r.comment && <p className="mt-1 whitespace-pre-line break-words text-sm">{r.comment}</p>}
              {r.reply ? <p className="mt-2 rounded-control bg-pale p-3 text-sm"><strong>Your reply:</strong> {r.reply.body}</p> : <Button className="mt-3" variant="outline" onClick={() => setTarget(r)}>Reply</Button>}
            </Card></li>
          ))}
        </ul>
        <Pagination page={page} count={q.data?.count ?? 0} onPage={(n) => set({ page: n })} />
      </QueryBoundary>
      <Modal open={!!target} onClose={() => setTarget(null)} title="Reply to review" footer={<><Button variant="outline" onClick={() => setTarget(null)}>Cancel</Button><Button loading={reply.isPending} disabled={!body.trim()} onClick={() => reply.mutate()}>Publish reply</Button></>}>
        <Field label="Your public reply">{(p) => <Textarea {...p} rows={4} maxLength={1000} value={body} onChange={(e) => setBody(e.target.value)} />}</Field>
      </Modal>
    </>
  )
}
