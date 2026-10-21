import { useQuery } from '@tanstack/react-query'
import { Inbox, LifeBuoy, Plus } from 'lucide-react'
import { Link, useNavigate } from 'react-router-dom'
import { DataTable, Pagination, QueryBoundary, Segmented, Status } from '@/components/kit'
import { Button, Input, PageHeader, Select } from '@/components/ui'
import { useUrlState } from '@/hooks/useUrlState'
import { formatDate } from '@/lib/format'
import { AGAINST, COMPLAINT_CATEGORY, COMPLAINT_STATUS, label, TICKET_CATEGORY, TICKET_STATUS } from '@/lib/labels'
import { listComplaints, listTickets } from '@/services/platform'
import { COMPLAINT_STATUSES, PRIORITIES, SlaBadges, TICKET_STATUSES } from './shared'

export function TicketsList({ base, staff }: { base: string; staff: boolean }) {
  const navigate = useNavigate()
  const { values, page, set } = useUrlState(['status', 'priority', 'q', 'scope'] as const)
  const q = useQuery({
    queryKey: ['tickets', values, page],
    queryFn: () => listTickets({ page, status: values.status, priority: values.priority, q: values.q, unassigned: values.scope === 'unassigned' ? '1' : undefined, mine: values.scope === 'mine' ? '1' : undefined, escalated: values.scope === 'escalated' ? '1' : undefined }),
    placeholderData: (p) => p,
  })
  return (
    <>
      <PageHeader title={staff ? 'Tickets' : 'My support requests'} actions={!staff && <div className="flex gap-2"><Link to={`${base}/new-ticket`}><Button icon={Plus}>New request</Button></Link><Link to={`${base}/new-complaint`}><Button variant="secondary">File a complaint</Button></Link></div>} />
      {!staff && <p className="mb-3 text-sm"><Link className="font-semibold text-forest underline" to={`${base}/complaints`}>View my complaints</Link></p>}
      <div className="mb-4 flex flex-wrap items-end gap-3">
        {staff && <Segmented label="Queue" value={values.scope} onChange={(v) => set({ scope: v })} options={[{ value: '', label: 'All' }, { value: 'mine', label: 'Mine' }, { value: 'unassigned', label: 'Unassigned' }, { value: 'escalated', label: 'Escalated' }]} />}
        <label className="text-sm">Status<Select className="mt-1" value={values.status} onChange={(e) => set({ status: e.target.value })}><option value="">Any</option>{TICKET_STATUSES.map((s) => <option key={s} value={s}>{label(TICKET_STATUS, s)}</option>)}</Select></label>
        {staff && <label className="text-sm">Priority<Select className="mt-1" value={values.priority} onChange={(e) => set({ priority: e.target.value })}><option value="">Any</option>{PRIORITIES.map((s) => <option key={s} value={s}>{label({}, s)}</option>)}</Select></label>}
        <label className="min-w-[12rem] flex-1 text-sm sm:max-w-xs">Search<Input className="mt-1" type="search" defaultValue={values.q} onKeyDown={(e) => e.key === 'Enter' && set({ q: e.currentTarget.value })} onBlur={(e) => e.target.value !== values.q && set({ q: e.target.value })} placeholder="Reference or subject" /></label>
      </div>
      <QueryBoundary query={q} isEmpty={q.data?.count === 0} empty={{ icon: staff ? Inbox : LifeBuoy, title: 'No tickets found', text: staff ? 'Nothing matches these filters.' : 'Need help with an order? Start a new request.' }}>
        <DataTable caption="Support tickets" rows={q.data?.results ?? []} rowKey={(t) => t.id} onRowClick={(t) => navigate(`${base}/tickets/${t.id}`)}
          columns={[
            { key: 'r', header: 'Ticket', primary: true, cell: (t) => <Link className="inline-flex min-h-11 items-center font-semibold text-forest hover:underline" to={`${base}/tickets/${t.id}`} onClick={(e) => e.stopPropagation()}>{t.reference}</Link> },
            { key: 's', header: 'Subject', cell: (t) => <span className="break-words">{t.subject}</span> },
            { key: 'c', header: 'Category', cell: (t) => label(TICKET_CATEGORY, t.category) },
            { key: 'st', header: 'Status', cell: (t) => <Status value={t.status} label={label(TICKET_STATUS, t.status)} /> },
            ...(staff ? [{ key: 'p', header: 'Priority', cell: (t: { priority: string; escalated: boolean }) => <>{label({}, t.priority)}{t.escalated ? ' · escalated' : ''}</> }, { key: 'sla', header: 'SLA', cell: (t: { sla: import('@/types/platform').Sla | null }) => <SlaBadges sla={t.sla} /> }, { key: 'a', header: 'Assigned', cell: (t: { assigned_to: { name: string } | null }) => t.assigned_to?.name ?? 'Unassigned' }] : []),
            { key: 'u', header: 'Updated', cell: (t) => formatDate(t.updated_at) },
          ]} />
        <Pagination page={page} count={q.data?.count ?? 0} onPage={(n) => set({ page: n })} />
      </QueryBoundary>
    </>
  )
}

export function ComplaintsList({ base, staff }: { base: string; staff: boolean }) {
  const navigate = useNavigate()
  const { values, page, set } = useUrlState(['status', 'severity', 'q', 'scope'] as const)
  const q = useQuery({
    queryKey: ['complaints', values, page],
    queryFn: () => listComplaints({ page, status: values.status, severity: values.severity, q: values.q, unassigned: values.scope === 'unassigned' ? '1' : undefined, mine: values.scope === 'mine' ? '1' : undefined }),
    placeholderData: (p) => p,
  })
  return (
    <>
      <PageHeader title={staff ? 'Complaints' : 'My complaints'} actions={!staff && <Link to={`${base}/new-complaint`}><Button icon={Plus}>File a complaint</Button></Link>} />
      {!staff && <p className="mb-3 text-sm"><Link className="font-semibold text-forest underline" to={base}>Back to support requests</Link></p>}
      <div className="mb-4 flex flex-wrap items-end gap-3">
        {staff && <Segmented label="Queue" value={values.scope} onChange={(v) => set({ scope: v })} options={[{ value: '', label: 'All' }, { value: 'mine', label: 'Mine' }, { value: 'unassigned', label: 'Unassigned' }]} />}
        <label className="text-sm">Status<Select className="mt-1" value={values.status} onChange={(e) => set({ status: e.target.value })}><option value="">Any</option>{COMPLAINT_STATUSES.map((s) => <option key={s} value={s}>{label(COMPLAINT_STATUS, s)}</option>)}</Select></label>
        <label className="min-w-[12rem] flex-1 text-sm sm:max-w-xs">Search<Input className="mt-1" type="search" defaultValue={values.q} onKeyDown={(e) => e.key === 'Enter' && set({ q: e.currentTarget.value })} onBlur={(e) => e.target.value !== values.q && set({ q: e.target.value })} placeholder="Reference" /></label>
      </div>
      <QueryBoundary query={q} isEmpty={q.data?.count === 0} empty={{ icon: Inbox, title: 'No complaints found', text: staff ? 'Nothing matches these filters.' : 'You have not filed any complaints.' }}>
        <DataTable caption="Complaints" rows={q.data?.results ?? []} rowKey={(c) => c.id} onRowClick={(c) => navigate(`${base}/complaints/${c.id}`)}
          columns={[
            { key: 'r', header: 'Complaint', primary: true, cell: (c) => <Link className="inline-flex min-h-11 items-center font-semibold text-forest hover:underline" to={`${base}/complaints/${c.id}`} onClick={(e) => e.stopPropagation()}>{c.reference}</Link> },
            { key: 'a', header: 'Against', cell: (c) => label(AGAINST, c.against_type) + (c.store_name ? ` · ${c.store_name}` : '') },
            { key: 'c', header: 'Category', cell: (c) => label(COMPLAINT_CATEGORY, c.category) },
            { key: 's', header: 'Status', cell: (c) => <Status value={c.status} label={label(COMPLAINT_STATUS, c.status)} /> },
            ...(staff ? [{ key: 'sev', header: 'Severity', cell: (c: { severity: string }) => label({}, c.severity) }, { key: 'sla', header: 'SLA', cell: (c: { sla: import('@/types/platform').Sla | null }) => <SlaBadges sla={c.sla} /> }, { key: 'asg', header: 'Assigned', cell: (c: { assigned_to: { name: string } | null }) => c.assigned_to?.name ?? 'Unassigned' }] : []),
            { key: 'u', header: 'Updated', cell: (c) => formatDate(c.updated_at) },
          ]} />
        <Pagination page={page} count={q.data?.count ?? 0} onPage={(n) => set({ page: n })} />
      </QueryBoundary>
    </>
  )
}
