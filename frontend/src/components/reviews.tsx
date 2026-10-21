import { useMutation } from '@tanstack/react-query'
import { Flag } from 'lucide-react'
import { useState } from 'react'
import { Modal, Stars, useToast } from '@/components/kit'
import { Button, Field, Select, Textarea } from '@/components/ui'
import { useAuth } from '@/features/auth/AuthProvider'
import { errorMessage } from '@/lib/api'
import { formatDate } from '@/lib/format'
import { reportReview } from '@/services/platform'
import type { PublicReview } from '@/types/platform'

const REASONS = [['ABUSIVE', 'Abusive or offensive'], ['SPAM', 'Spam or advertising'], ['FAKE', 'Fake or irrelevant'], ['PRIVATE', 'Contains private information'], ['OTHER', 'Other']] as const

export function ReviewList({ reviews }: { reviews: PublicReview[] }) {
  const { user } = useAuth()
  const toast = useToast()
  const [reporting, setReporting] = useState<PublicReview | null>(null)
  const [reason, setReason] = useState('ABUSIVE')
  const [note, setNote] = useState('')
  const report = useMutation({
    mutationFn: () => reportReview((reporting as PublicReview).id, reason, note),
    onSuccess: () => { toast('success', 'Thanks — our team will review this.'); setReporting(null); setNote('') },
    onError: (error) => toast('error', errorMessage(error)),
  })
  return (
    <>
      <ul className="divide-y divide-line">
        {reviews.map((r) => (
          <li key={r.id} className="py-4 first:pt-0 last:pb-0">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2"><Stars value={r.rating} /><span className="text-sm font-medium">{r.reviewer}</span></div>
              <span className="text-xs text-muted">{formatDate(r.created_at)}{r.edited_at ? ' · edited' : ''}</span>
            </div>
            {r.title && <p className="mt-1 text-sm font-semibold">{r.title}</p>}
            {r.comment && <p className="mt-1 whitespace-pre-line break-words text-sm text-ink">{r.comment}</p>}
            {r.reply && <div className="mt-2 rounded-control bg-pale p-3 text-sm"><p className="font-semibold text-forest">Reply from the store</p><p className="mt-0.5 whitespace-pre-line break-words">{r.reply.body}</p></div>}
            {user && (
              <button type="button" onClick={() => setReporting(r)} className="mt-2 inline-flex min-h-9 items-center gap-1 text-xs text-muted hover:text-danger"><Flag className="size-3.5" aria-hidden="true" />Report</button>
            )}
          </li>
        ))}
      </ul>
      <Modal open={reporting !== null} onClose={() => setReporting(null)} title="Report this review"
        footer={<><Button variant="outline" onClick={() => setReporting(null)}>Cancel</Button><Button loading={report.isPending} onClick={() => report.mutate()}>Send report</Button></>}>
        <div className="space-y-3">
          <Field label="Why are you reporting it?">{(p) => <Select {...p} value={reason} onChange={(e) => setReason(e.target.value)}>{REASONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</Select>}</Field>
          <Field label="Details (optional)">{(p) => <Textarea {...p} rows={3} maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} />}</Field>
        </div>
      </Modal>
    </>
  )
}
