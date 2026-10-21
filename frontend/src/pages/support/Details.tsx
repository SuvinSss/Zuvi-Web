import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'
import { KeyValue, QueryBoundary, ReasonDialog, Section, Status, Timeline, useToast } from '@/components/kit'
import { Alert, Button, Card, Field, PageHeader, Select, Textarea } from '@/components/ui'
import { errorMessage } from '@/lib/api'
import { formatDate } from '@/lib/format'
import { AGAINST, COMPLAINT_CATEGORY, COMPLAINT_STATUS, label, TICKET_CATEGORY, TICKET_STATUS } from '@/lib/labels'
import { addTicketMessage, assignTicket, commentComplaint, complaintAction, escalateTicket, getComplaint, getTicket, listAgents, setTicketPriority, setTicketStatus } from '@/services/platform'
import { Attachments, MultiFilePicker, PRIORITIES, SlaBadges, TICKET_STATUSES } from './shared'

function Composer({ staff, onSend, busy, error, prompt }: { staff: boolean; onSend: (body: string, internal: boolean, files: File[]) => Promise<unknown>; busy: boolean; error?: string; prompt: string }) {
  const [body, setBody] = useState('')
  const [internal, setInternal] = useState(false)
  const [files, setFiles] = useState<File[]>([])
  return (
    <form className="space-y-3" onSubmit={async (e) => { e.preventDefault(); if (!body.trim()) return; try { await onSend(body, internal, files); setBody(''); setFiles([]) } catch { /* shown via error */ } }}>
      {error && <Alert>{error}</Alert>}
      <Field label={prompt}>{(p) => <Textarea {...p} rows={4} maxLength={5000} value={body} onChange={(e) => setBody(e.target.value)} />}</Field>
      {staff && <label className="flex min-h-11 items-center gap-2 text-sm"><input type="checkbox" className="size-5" checked={internal} onChange={(e) => setInternal(e.target.checked)} />Internal note (not visible to the customer)</label>}
      <MultiFilePicker files={files} onChange={setFiles} />
      <Button type="submit" loading={busy} disabled={!body.trim()}>{internal ? 'Add internal note' : 'Send reply'}</Button>
    </form>
  )
}

export function TicketDetailPage({ base, staff, supervisor }: { base: string; staff: boolean; supervisor?: boolean }) {
  const id = Number(useParams().id)
  const qc = useQueryClient()
  const toast = useToast()
  const q = useQuery({ queryKey: ['ticket', id], queryFn: () => getTicket(id) })
  const agents = useQuery({ queryKey: ['agents'], queryFn: listAgents, enabled: staff && !!supervisor })
  const [escalating, setEscalating] = useState(false)
  const done = (t: unknown) => { qc.setQueryData(['ticket', id], t); void qc.invalidateQueries({ queryKey: ['tickets'] }) }
  const fail = (e: unknown) => toast('error', errorMessage(e))
  const send = useMutation({ mutationFn: (v: { body: string; internal: boolean; files: File[] }) => addTicketMessage(id, v.body, v.internal, v.files), onSuccess: done })
  const status = useMutation({ mutationFn: (s: string) => setTicketStatus(id, s), onSuccess: (t) => { done(t); toast('success', 'Status updated.') }, onError: fail })
  const priority = useMutation({ mutationFn: (p: string) => setTicketPriority(id, p), onSuccess: (t) => { done(t); toast('success', 'Priority updated.') }, onError: fail })
  const assign = useMutation({ mutationFn: (a?: number) => assignTicket(id, a), onSuccess: (t) => { done(t); toast('success', 'Assignment updated.') }, onError: fail })
  const escalate = useMutation({ mutationFn: (r: string) => escalateTicket(id, r), onSuccess: (t) => { done(t); setEscalating(false); toast('success', 'Escalated to a supervisor.') }, onError: fail })
  const t = q.data
  const closed = t?.status === 'CLOSED'
  return (
    <QueryBoundary query={q} skeleton="detail">
      {t && (
        <>
          <PageHeader title={t.reference} subtitle={t.subject} actions={<Link className="inline-flex min-h-11 items-center text-sm font-semibold text-forest underline" to={base}>Back to tickets</Link>} />
          <div className="grid gap-6 lg:grid-cols-[1fr_20rem]">
            <div className="space-y-6">
              <Card className="p-4"><div className="mb-2 flex flex-wrap items-center gap-2"><Status value={t.status} label={label(TICKET_STATUS, t.status)} />{t.escalated && <span className="rounded-full bg-warn/15 px-2 py-0.5 text-xs text-warn">Escalated</span>}<SlaBadges sla={t.sla} /></div>
                <p className="whitespace-pre-line break-words text-sm">{t.description}</p><Attachments items={t.attachments} /></Card>
              <Section title="Conversation">
                <ul className="space-y-3">
                  {t.messages.map((m) => (
                    <li key={m.id}><Card className={`p-4 ${m.is_internal ? 'border-warn bg-warn/5' : ''}`}>
                      <p className="text-sm font-semibold">{m.author.name}{m.is_internal && <span className="ml-2 text-xs font-medium text-warn">Internal note</span>}</p>
                      <p className="text-xs text-muted">{new Date(m.created_at).toLocaleString('en-IN')}</p>
                      <p className="mt-1 whitespace-pre-line break-words text-sm">{m.body}</p>
                    </Card></li>
                  ))}
                  {!t.messages.length && <li className="text-sm text-muted">No replies yet.</li>}
                </ul>
              </Section>
              {!closed ? <Section title={staff ? 'Reply' : 'Add a reply'}><Card className="p-4"><Composer staff={staff} prompt="Message" busy={send.isPending} error={send.isError ? errorMessage(send.error) : undefined} onSend={(body, internal, files) => send.mutateAsync({ body, internal, files })} /></Card></Section>
                : <Alert tone="info">This request is closed. Open a new request if you still need help.</Alert>}
              {staff && t.events.length > 0 && <Section title="Activity"><Card className="p-4"><Timeline items={t.events.map((e, i) => ({ key: String(i), title: label({}, e.kind), note: e.detail, at: e.created_at }))} /></Card></Section>}
            </div>
            <aside className="space-y-4">
              <Card className="p-4"><KeyValue rows={[['Category', label(TICKET_CATEGORY, t.category)], ['Opened', formatDate(t.created_at)], ['Order', t.order ? (staff ? t.order_number : <Link className="underline" to={`/account/orders/${t.order}`}>{t.order_number}</Link>) : null], ...(staff ? [['Requester', t.requester?.name], ['Assigned to', t.assigned_to?.name ?? 'Unassigned'], ['Priority', label({}, t.priority)]] as [string, ReactNode][] : [])]} /></Card>
              {staff && (
                <Card className="space-y-3 p-4">
                  <h2 className="font-semibold text-forest">Actions</h2>
                  <Field label="Status">{(p) => <Select {...p} value={t.status} onChange={(e) => status.mutate(e.target.value)} disabled={status.isPending}>{TICKET_STATUSES.map((s) => <option key={s} value={s}>{label(TICKET_STATUS, s)}</option>)}</Select>}</Field>
                  <Field label="Priority">{(p) => <Select {...p} value={t.priority} onChange={(e) => priority.mutate(e.target.value)} disabled={priority.isPending}>{PRIORITIES.map((s) => <option key={s} value={s}>{label({}, s)}</option>)}</Select>}</Field>
                  <Button variant="secondary" className="w-full" onClick={() => assign.mutate(undefined)} loading={assign.isPending}>Assign to me</Button>
                  {supervisor && agents.data && <Field label="Assign to agent">{(p) => <Select {...p} value="" onChange={(e) => e.target.value && assign.mutate(Number(e.target.value))}><option value="">Choose an agent…</option>{agents.data.map((a) => <option key={a.id} value={a.id}>{a.name} ({a.open_tickets} open)</option>)}</Select>}</Field>}
                  {!t.escalated && <Button variant="danger" className="w-full" onClick={() => setEscalating(true)}>Escalate</Button>}
                </Card>
              )}
            </aside>
          </div>
          <ReasonDialog open={escalating} title="Escalate ticket" field="Reason for escalation" confirm="Escalate" busy={escalate.isPending} onClose={() => setEscalating(false)} onSubmit={(r) => escalate.mutate(r)} />
        </>
      )}
    </QueryBoundary>
  )
}

type CAction = 'assign' | 'request-info' | 'escalate' | 'take-over' | 'resolve' | 'reject' | 'close' | 'reopen'
export function ComplaintDetailPage({ base, staff, supervisor }: { base: string; staff: boolean; supervisor?: boolean }) {
  const id = Number(useParams().id)
  const qc = useQueryClient()
  const toast = useToast()
  const q = useQuery({ queryKey: ['complaint', id], queryFn: () => getComplaint(id) })
  const agents = useQuery({ queryKey: ['agents'], queryFn: listAgents, enabled: staff && !!supervisor })
  const [dialog, setDialog] = useState<null | { action: CAction; title: string; field: string; key: string; confirm: string; danger?: boolean }>(null)
  const done = (c: unknown) => { qc.setQueryData(['complaint', id], c); void qc.invalidateQueries({ queryKey: ['complaints'] }) }
  const comment = useMutation({ mutationFn: (v: { body: string; internal: boolean; files: File[] }) => commentComplaint(id, v.body, v.internal, v.files), onSuccess: done })
  const act = useMutation({
    mutationFn: (v: { action: CAction; body?: Record<string, unknown> }) => complaintAction(id, v.action, v.body),
    onSuccess: (c) => { done(c); setDialog(null); toast('success', 'Complaint updated.') },
    onError: (e) => toast('error', errorMessage(e)),
  })
  const c = q.data
  const open = c && !['CLOSED'].includes(c.status)
  const D = (action: CAction, title: string, field: string, key: string, confirm: string, danger = false) => () => setDialog({ action, title, field, key, confirm, danger })
  return (
    <QueryBoundary query={q} skeleton="detail">
      {c && (
        <>
          <PageHeader title={c.reference} subtitle={`${label(COMPLAINT_CATEGORY, c.category)} · ${label(AGAINST, c.against_type)}`} actions={<Link className="inline-flex min-h-11 items-center text-sm font-semibold text-forest underline" to={`${base}/complaints`}>Back to complaints</Link>} />
          <div className="grid gap-6 lg:grid-cols-[1fr_20rem]">
            <div className="space-y-6">
              <Card className="p-4">
                <div className="mb-2 flex flex-wrap items-center gap-2"><Status value={c.status} label={label(COMPLAINT_STATUS, c.status)} /><SlaBadges sla={c.sla} /></div>
                <p className="whitespace-pre-line break-words text-sm">{c.description}</p>
                {c.desired_resolution && <p className="mt-2 text-sm"><strong>Requested outcome:</strong> {c.desired_resolution}</p>}
                {c.resolution && <p className="mt-2 rounded-control bg-pale p-3 text-sm"><strong>Resolution:</strong> {c.resolution}</p>}
                <Attachments items={c.attachments} />
              </Card>
              <Section title="Timeline"><Card className="p-4"><Timeline items={c.timeline.map((e) => ({ key: String(e.id), title: `${e.actor?.name ?? 'System'}${e.is_internal ? ' · internal' : ''}`, note: e.body || (e.to_status ? `Status: ${label(COMPLAINT_STATUS, e.to_status)}` : label({}, e.kind)), at: e.created_at }))} /></Card></Section>
              {open && <Section title={staff ? 'Respond' : 'Add information'}><Card className="p-4"><Composer staff={staff} prompt="Message" busy={comment.isPending} error={comment.isError ? errorMessage(comment.error) : undefined} onSend={(body, internal, files) => comment.mutateAsync({ body, internal, files })} /></Card></Section>}
            </div>
            <aside className="space-y-4">
              <Card className="p-4"><KeyValue rows={[['Filed', formatDate(c.created_at)], ['Order', c.order ? (staff ? c.order_number : <Link className="underline" to={`/account/orders/${c.order}`}>{c.order_number}</Link>) : null], ['Store', c.store_name], ...(staff ? [['Complainant', c.complainant?.name], ['Assigned to', c.assigned_to?.name ?? 'Unassigned'], ['Severity', label({}, c.severity)]] as [string, ReactNode][] : [])]} /></Card>
              {staff && open && (
                <Card className="space-y-2 p-4">
                  <h2 className="font-semibold text-forest">Actions</h2>
                  <Button variant="secondary" className="w-full" loading={act.isPending && act.variables?.action === 'assign'} onClick={() => act.mutate({ action: 'assign', body: {} })}>Assign to me</Button>
                  {supervisor && agents.data && <Field label="Assign to agent">{(p) => <Select {...p} value="" onChange={(e) => e.target.value && act.mutate({ action: 'assign', body: { assignee: Number(e.target.value) } })}><option value="">Choose an agent…</option>{agents.data.map((a) => <option key={a.id} value={a.id}>{a.name} ({a.open_complaints} open)</option>)}</Select>}</Field>}
                  {supervisor && <Button variant="secondary" className="w-full" onClick={() => act.mutate({ action: 'take-over' })}>Take over</Button>}
                  <Button variant="secondary" className="w-full" onClick={D('request-info', 'Request information', 'What do you need from the customer?', 'message', 'Send request')}>Request information</Button>
                  <Button variant="secondary" className="w-full" onClick={D('escalate', 'Escalate complaint', 'Reason for escalation', 'reason', 'Escalate')}>Escalate</Button>
                  <Button className="w-full" onClick={D('resolve', 'Resolve complaint', 'Describe the resolution', 'resolution', 'Resolve')}>Resolve</Button>
                  <Button variant="danger" className="w-full" onClick={D('reject', 'Do not uphold', 'Reason', 'reason', 'Reject', true)}>Reject</Button>
                  {['RESOLVED', 'REJECTED'].includes(c.status) && <Button variant="secondary" className="w-full" onClick={() => act.mutate({ action: 'close' })}>Close</Button>}
                </Card>
              )}
              {staff && ['RESOLVED', 'REJECTED', 'CLOSED'].includes(c.status) && <Button variant="secondary" className="w-full" onClick={D('reopen', 'Reopen complaint', 'Reason for reopening', 'reason', 'Reopen')}>Reopen</Button>}
            </aside>
          </div>
          {dialog && <ReasonDialog open title={dialog.title} field={dialog.field} confirm={dialog.confirm} danger={dialog.danger} busy={act.isPending} onClose={() => setDialog(null)} onSubmit={(text) => act.mutate({ action: dialog.action, body: { [dialog.key]: text } })} />}
        </>
      )}
    </QueryBoundary>
  )
}
