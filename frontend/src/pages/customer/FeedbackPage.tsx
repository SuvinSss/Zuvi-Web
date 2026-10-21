import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { MessageSquare } from 'lucide-react'
import { useState } from 'react'
import { Pagination, QueryBoundary, Section, Status, useToast } from '@/components/kit'
import { Alert, Button, Card, Field, PageHeader, Select, Textarea } from '@/components/ui'
import { useUrlState } from '@/hooks/useUrlState'
import { errorMessage, fieldErrors } from '@/lib/api'
import { formatDate } from '@/lib/format'
import { label } from '@/lib/labels'
import { listFeedback, submitFeedback } from '@/services/platform'

const KIND = { SUGGESTION: 'Suggestion', PRAISE: 'Praise', ISSUE: 'Problem', QUESTION: 'Question' }
const SUBJECT = { PLATFORM: 'The platform', APP: 'The app', STORE: 'A store', DELIVERY: 'Delivery service' }

export default function FeedbackPage() {
  const qc = useQueryClient()
  const toast = useToast()
  const { page, set } = useUrlState([] as const)
  const list = useQuery({ queryKey: ['feedback', page], queryFn: () => listFeedback({ page }), placeholderData: (p) => p })
  const [v, setV] = useState({ kind: 'SUGGESTION', subject_type: 'PLATFORM', message: '' })
  const send = useMutation({ mutationFn: () => submitFeedback(v), onSuccess: () => { toast('success', 'Thanks — your feedback was sent.'); setV({ ...v, message: '' }); void qc.invalidateQueries({ queryKey: ['feedback'] }) } })
  const fe = fieldErrors(send.error)
  return (
    <>
      <PageHeader title="Feedback" subtitle="Tell us what works and what does not. For an order problem, use Get help on the order instead." />
      <div className="grid gap-6 lg:grid-cols-2">
        <Section title="Send feedback">
          <Card className="p-4">
            <form onSubmit={(e) => { e.preventDefault(); send.mutate() }} className="space-y-3" noValidate>
              {send.isError && !Object.keys(fe).length && <Alert>{errorMessage(send.error)}</Alert>}
              <Field label="Type">{(p) => <Select {...p} value={v.kind} onChange={(e) => setV({ ...v, kind: e.target.value })}>{Object.entries(KIND).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</Select>}</Field>
              <Field label="About">{(p) => <Select {...p} value={v.subject_type} onChange={(e) => setV({ ...v, subject_type: e.target.value })}>{Object.entries(SUBJECT).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</Select>}</Field>
              <Field label="Your message" required error={fe.message}>{(p) => <Textarea {...p} rows={5} maxLength={3000} value={v.message} onChange={(e) => setV({ ...v, message: e.target.value })} />}</Field>
              <Button type="submit" loading={send.isPending}>Send feedback</Button>
            </form>
          </Card>
        </Section>
        <Section title="Your feedback">
          <QueryBoundary query={list} isEmpty={list.data?.count === 0} empty={{ icon: MessageSquare, title: 'Nothing sent yet' }}>
            <ul className="space-y-3">
              {list.data?.results.map((f) => (
                <li key={f.id}><Card className="p-4">
                  <div className="flex flex-wrap items-center justify-between gap-2"><span className="text-sm font-semibold">{f.reference} · {label(KIND, f.kind)}</span><Status value={f.status} /></div>
                  <p className="mt-1 whitespace-pre-line break-words text-sm">{f.message}</p>
                  <p className="mt-1 text-xs text-muted">{formatDate(f.created_at)}</p>
                  {f.replies.filter((r) => !r.is_internal).map((r) => <p key={r.id} className="mt-2 rounded-control bg-pale p-3 text-sm"><strong>Reply:</strong> {r.body}</p>)}
                </Card></li>
              ))}
            </ul>
            <Pagination page={page} count={list.data?.count ?? 0} onPage={(n) => set({ page: n })} />
          </QueryBoundary>
        </Section>
      </div>
    </>
  )
}
