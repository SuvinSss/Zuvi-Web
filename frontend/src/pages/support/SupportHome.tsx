import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { QueryBoundary, Section, Stat } from '@/components/kit'
import { PageHeader } from '@/components/ui'
import { COMPLAINT_STATUS, label, TICKET_STATUS } from '@/lib/labels'
import { supportSummary } from '@/services/platform'

const go = (to: string, text: string) => <Link className="mt-1 inline-block text-sm font-semibold text-forest underline" to={to}>{text}</Link>

export default function SupportHome({ base = '/support' }: { base?: string }) {
  const q = useQuery({ queryKey: ['support-summary'], queryFn: supportSummary, refetchInterval: 60_000 })
  const s = q.data
  return (
    <>
      <PageHeader title="Support queue" />
      <QueryBoundary query={q} skeleton="detail">
        {s && (
          <div className="space-y-8">
            <Section title="Tickets">
              <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                <Stat label="Unassigned" value={s.tickets.unassigned} to={go(`${base}/tickets?scope=unassigned`, 'Open queue')} />
                <Stat label="Escalated" value={s.tickets.escalated} to={go(`${base}/tickets?scope=escalated`, 'Review')} />
                <Stat label="First reply overdue" value={s.tickets.first_response_breached} />
                <Stat label="Resolution overdue" value={s.tickets.resolution_breached} />
              </div>
              <ul className="mt-3 flex flex-wrap gap-2">{Object.entries(s.tickets.by_status).map(([k, n]) => <li key={k}><Link className="inline-flex min-h-9 items-center gap-2 rounded-full bg-white px-3 text-sm ring-1 ring-line hover:bg-pale" to={`${base}/tickets?status=${k}`}>{label(TICKET_STATUS, k)} <strong>{n}</strong></Link></li>)}</ul>
            </Section>
            <Section title="Complaints">
              <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                <Stat label="Unassigned" value={s.complaints.unassigned} to={go(`${base}/complaints?scope=unassigned`, 'Open queue')} />
                <Stat label="Escalated" value={s.complaints.escalated} />
                <Stat label="Acknowledgement overdue" value={s.complaints.acknowledgement_breached} />
                <Stat label="Resolution overdue" value={s.complaints.resolution_breached} />
              </div>
              <ul className="mt-3 flex flex-wrap gap-2">{Object.entries(s.complaints.by_status).map(([k, n]) => <li key={k}><Link className="inline-flex min-h-9 items-center gap-2 rounded-full bg-white px-3 text-sm ring-1 ring-line hover:bg-pale" to={`${base}/complaints?status=${k}`}>{label(COMPLAINT_STATUS, k)} <strong>{n}</strong></Link></li>)}</ul>
            </Section>
          </div>
        )}
      </QueryBoundary>
    </>
  )
}
