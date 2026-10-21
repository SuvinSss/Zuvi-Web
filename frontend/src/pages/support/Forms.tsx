import { useMutation, useQuery } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useToast } from '@/components/kit'
import { Alert, Button, Card, Field, Input, PageHeader, Select, Textarea } from '@/components/ui'
import { errorMessage, fieldErrors } from '@/lib/api'
import { AGAINST, COMPLAINT_CATEGORY, TICKET_CATEGORY } from '@/lib/labels'
import { createComplaint, createTicket, listOrders } from '@/services/platform'
import { MultiFilePicker } from './shared'

function OrderSelect({ value, onChange, error }: { value: string; onChange: (v: string) => void; error?: string }) {
  const orders = useQuery({ queryKey: ['orders', '', 1], queryFn: () => listOrders({ page: 1 }) })
  return (
    <Field label="Related order (optional)" error={error}>
      {(p) => <Select {...p} value={value} onChange={(e) => onChange(e.target.value)}><option value="">Not about a specific order</option>{orders.data?.results.map((o) => <option key={o.id} value={o.id}>{o.order_number}</option>)}</Select>}
    </Field>
  )
}

export function NewTicketPage({ base }: { base: string }) {
  const navigate = useNavigate()
  const toast = useToast()
  const [params] = useSearchParams()
  const [v, setV] = useState({ category: params.get('order') ? 'ORDER' : 'OTHER', subject: '', description: '', order: params.get('order') ?? '' })
  const [files, setFiles] = useState<File[]>([])
  const m = useMutation({
    mutationFn: () => createTicket({ ...v, order: v.order ? Number(v.order) : null }, files),
    onSuccess: (t) => { toast('success', `Request ${t.reference} created.`); navigate(`${base}/tickets/${t.id}`) },
  })
  const fe = fieldErrors(m.error)
  const submit = (e: FormEvent) => { e.preventDefault(); m.mutate() }
  return (
    <>
      <PageHeader title="New support request" subtitle="Tell us what happened. We will reply here and by notification." />
      <Card className="max-w-2xl p-4 sm:p-6">
        <form onSubmit={submit} className="space-y-4" noValidate>
          {m.isError && !Object.keys(fe).length && <Alert>{errorMessage(m.error)}</Alert>}
          <Field label="Topic" error={fe.category}>{(p) => <Select {...p} value={v.category} onChange={(e) => setV({ ...v, category: e.target.value })}>{Object.entries(TICKET_CATEGORY).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</Select>}</Field>
          <OrderSelect value={v.order} onChange={(order) => setV({ ...v, order })} error={fe.order} />
          <Field label="Subject" required error={fe.subject}>{(p) => <Input {...p} maxLength={200} value={v.subject} onChange={(e) => setV({ ...v, subject: e.target.value })} />}</Field>
          <Field label="Describe the problem" required error={fe.description}>{(p) => <Textarea {...p} rows={6} maxLength={5000} value={v.description} onChange={(e) => setV({ ...v, description: e.target.value })} />}</Field>
          <MultiFilePicker files={files} onChange={setFiles} />
          {fe.attachments && <p role="alert" className="text-sm text-danger">{fe.attachments}</p>}
          <Button type="submit" loading={m.isPending}>Send request</Button>
        </form>
      </Card>
    </>
  )
}

export function NewComplaintPage({ base }: { base: string }) {
  const navigate = useNavigate()
  const toast = useToast()
  const [params] = useSearchParams()
  const [v, setV] = useState({ against_type: 'STORE', category: 'OTHER', description: '', desired_resolution: '', order: params.get('order') ?? '' })
  const [files, setFiles] = useState<File[]>([])
  const m = useMutation({
    mutationFn: () => createComplaint({ ...v, order: v.order ? Number(v.order) : null }, files),
    onSuccess: (c) => { toast('success', `Complaint ${c.reference} filed.`); navigate(`${base}/complaints/${c.id}`) },
  })
  const fe = fieldErrors(m.error)
  return (
    <>
      <PageHeader title="File a complaint" subtitle="Complaints are reviewed by our support team and tracked until resolved." />
      <Card className="max-w-2xl p-4 sm:p-6">
        <form onSubmit={(e) => { e.preventDefault(); m.mutate() }} className="space-y-4" noValidate>
          {m.isError && !Object.keys(fe).length && <Alert>{errorMessage(m.error)}</Alert>}
          <Field label="Who is it about?" error={fe.against_type}>{(p) => <Select {...p} value={v.against_type} onChange={(e) => setV({ ...v, against_type: e.target.value })}>{Object.entries(AGAINST).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</Select>}</Field>
          <OrderSelect value={v.order} onChange={(order) => setV({ ...v, order })} error={fe.order || fe.non_field_errors} />
          <Field label="What went wrong?" error={fe.category}>{(p) => <Select {...p} value={v.category} onChange={(e) => setV({ ...v, category: e.target.value })}>{Object.entries(COMPLAINT_CATEGORY).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</Select>}</Field>
          <Field label="Details" required error={fe.description}>{(p) => <Textarea {...p} rows={6} maxLength={5000} value={v.description} onChange={(e) => setV({ ...v, description: e.target.value })} />}</Field>
          <Field label="What outcome would you like? (optional)" error={fe.desired_resolution}>{(p) => <Input {...p} maxLength={255} value={v.desired_resolution} onChange={(e) => setV({ ...v, desired_resolution: e.target.value })} />}</Field>
          <MultiFilePicker files={files} onChange={setFiles} />
          <Button type="submit" loading={m.isPending}>Submit complaint</Button>
        </form>
      </Card>
    </>
  )
}
