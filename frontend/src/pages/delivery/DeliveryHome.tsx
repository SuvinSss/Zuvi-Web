import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Truck } from 'lucide-react'
import { Link } from 'react-router-dom'
import { QueryBoundary, Section, Stat, Status, useToast } from '@/components/kit'
import { Alert, Button, Card, PageHeader } from '@/components/ui'
import { errorMessage } from '@/lib/api'
import { currentPosition } from '@/lib/geo'
import { label } from '@/lib/labels'
import { listAssignments, partnerMe, setOnline } from '@/services/ops'
import { PARTNER_DELIVERY_STATUS, PARTNER_STATUS } from './labels'

export default function DeliveryHome() {
  const qc = useQueryClient()
  const toast = useToast()
  const me = useQuery({ queryKey: ['partner-me'], queryFn: partnerMe })
  const active = useQuery({ queryKey: ['assignments', 'active', 1], queryFn: () => listAssignments('active'), refetchInterval: 20_000 })
  const toggle = useMutation({
    mutationFn: async (online: boolean) => setOnline(online, online ? await currentPosition() : undefined),
    onSuccess: (p) => { qc.setQueryData(['partner-me'], p); toast('success', p.is_online ? 'You are online and can receive offers.' : 'You are offline.') },
    onError: (e) => toast('error', errorMessage(e)),
  })
  const offers = active.data?.results.filter((d) => d.status === 'OFFERED') ?? []
  return (
    <>
      <PageHeader title="Today" />
      <QueryBoundary query={me} skeleton="detail">
        {me.data && (
          <Card className="mb-6 p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div><p className="text-lg font-semibold">{me.data.is_online ? 'You are online' : 'You are offline'}</p>
                <p className="text-sm text-muted">{me.data.is_online ? 'Nearby orders can be offered to you.' : 'Go online to receive delivery offers. We will ask for your location.'}</p></div>
              <Button size="lg" variant={me.data.is_online ? 'secondary' : 'primary'} className="min-w-36" loading={toggle.isPending} onClick={() => toggle.mutate(!me.data!.is_online)}>{me.data.is_online ? 'Go offline' : 'Go online'}</Button>
            </div>
            <p className="mt-2 text-xs text-muted">Account: {label(PARTNER_STATUS, me.data.status)} · {label({}, me.data.vehicle_type)}</p>
          </Card>
        )}
      </QueryBoundary>
      {offers.length > 0 && <Alert tone="info" title={`${offers.length} delivery offer${offers.length > 1 ? 's' : ''} waiting`}>Offers expire quickly — open one to accept or decline.</Alert>}
      <div className="my-4 grid grid-cols-2 gap-3"><Stat label="Active deliveries" value={active.data?.count ?? '—'} /><Stat label="Offers" value={offers.length} /></div>
      <Section title="Active" actions={<Link className="inline-flex min-h-11 items-center text-sm font-semibold text-forest underline" to="/delivery/assignments">See all</Link>}>
        <QueryBoundary query={active} isEmpty={active.data?.count === 0} empty={{ icon: Truck, title: 'No active deliveries', text: me.data?.is_online ? 'Stay online — offers will appear here.' : 'Go online to start receiving offers.' }}>
          <ul className="space-y-2">
            {active.data?.results.map((d) => (
              <li key={d.id}><Link to={`/delivery/assignments/${d.id}`} className="block rounded-card border border-line bg-white p-4 shadow-card hover:bg-pale">
                <div className="flex items-center justify-between gap-2"><strong>{d.store_name}</strong><Status value={d.status} label={label(PARTNER_DELIVERY_STATUS, d.status)} /></div>
                <p className="text-sm text-muted">{d.order_number} → {d.dropoff.city}</p>
              </Link></li>
            ))}
          </ul>
        </QueryBoundary>
      </Section>
    </>
  )
}
