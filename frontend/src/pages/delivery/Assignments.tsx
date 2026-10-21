import { useQuery } from '@tanstack/react-query'
import { Truck } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Pagination, QueryBoundary, Segmented, Status } from '@/components/kit'
import { PageHeader } from '@/components/ui'
import { useUrlState } from '@/hooks/useUrlState'
import { formatDate } from '@/lib/format'
import { label } from '@/lib/labels'
import { listAssignments } from '@/services/ops'
import { PARTNER_DELIVERY_STATUS } from './labels'

export default function Assignments() {
  const { values, page, set } = useUrlState(['scope'] as const)
  const scope = values.scope === 'history' ? 'history' : 'active'
  const q = useQuery({ queryKey: ['assignments', scope, page], queryFn: () => listAssignments(scope, page), placeholderData: (p) => p, refetchInterval: scope === 'active' ? 20_000 : false })
  return (
    <>
      <PageHeader title="Deliveries" />
      <div className="mb-4"><Segmented label="Show" value={scope} onChange={(v) => set({ scope: v })} options={[{ value: 'active', label: 'Active' }, { value: 'history', label: 'History' }]} /></div>
      <QueryBoundary query={q} isEmpty={q.data?.count === 0} empty={{ icon: Truck, title: scope === 'active' ? 'No active deliveries' : 'No past deliveries', text: scope === 'active' ? 'New offers will appear here while you are online.' : undefined }}>
        <ul className="space-y-2">
          {q.data?.results.map((d) => (
            <li key={d.id}><Link to={`/delivery/assignments/${d.id}`} className="block rounded-card border border-line bg-white p-4 shadow-card hover:bg-pale">
              <div className="flex items-center justify-between gap-2"><strong>{d.store_name}</strong><Status value={d.status} label={label(PARTNER_DELIVERY_STATUS, d.status)} /></div>
              <p className="text-sm text-muted">{d.order_number} → {d.dropoff.city} · {formatDate(d.delivered_at ?? d.assigned_at ?? d.created_at)}</p>
            </Link></li>
          ))}
        </ul>
        <Pagination page={page} count={q.data?.count ?? 0} onPage={(n) => set({ page: n })} />
      </QueryBoundary>
    </>
  )
}
