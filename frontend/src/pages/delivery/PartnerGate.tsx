import { useQuery } from '@tanstack/react-query'
import { Outlet } from 'react-router-dom'
import { QueryBoundary } from '@/components/kit'
import { Alert, Card } from '@/components/ui'
import { partnerMe } from '@/services/ops'

/** Pending / rejected / suspended partners see their status instead of work screens. */
export default function PartnerGate() {
  const q = useQuery({ queryKey: ['partner-me'], queryFn: partnerMe })
  return (
    <QueryBoundary query={q} skeleton="detail">
      {q.data && q.data.status !== 'APPROVED' ? (
        <Card className="mx-auto max-w-lg p-6">
          <h1 className="text-xl font-semibold text-forest">{q.data.status === 'PENDING' ? 'Your application is being reviewed' : `Your account is ${q.data.status.toLowerCase()}`}</h1>
          <p className="mt-2 text-sm">{q.data.status === 'PENDING' ? 'We will notify you as soon as you are approved. You cannot receive deliveries until then.' : 'You cannot receive deliveries right now.'}</p>
          {q.data.status_reason && <Alert tone="warn" title="Reason">{q.data.status_reason}</Alert>}
        </Card>
      ) : <Outlet />}
    </QueryBoundary>
  )
}
