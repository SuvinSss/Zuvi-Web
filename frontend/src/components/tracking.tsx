import { useQuery } from '@tanstack/react-query'
import { Clock, MapPin, Navigation } from 'lucide-react'
import { Card, Alert } from '@/components/ui'
import { Status, Timeline } from '@/components/kit'
import { DELIVERY_STATUS, label } from '@/lib/labels'
import { errorMessage } from '@/lib/api'
import { googleMapsPlace, MapView } from '@/components/location/MapView'
import { getTracking } from '@/services/platform'
import type { TrackingDelivery } from '@/types/platform'

const TERMINAL = new Set(['DELIVERED', 'CANCELLED'])
const ageText = (s: number | null) => (s === null ? 'unknown' : s < 60 ? 'just now' : s < 3600 ? `${Math.round(s / 60)} min ago` : `${Math.round(s / 3600)} h ago`)

export function OrderTrackingPanel({ orderId, active }: { orderId: number; active: boolean }) {
  const q = useQuery({
    queryKey: ['tracking', orderId], queryFn: () => getTracking(orderId),
    // Poll only while a delivery is live; otherwise one fetch is enough.
    refetchInterval: (query) => (active && query.state.data?.deliveries.some((d) => !TERMINAL.has(d.status)) ? 20_000 : false),
  })
  if (q.isPending) return <p className="text-sm text-muted" aria-busy="true">Loading delivery status…</p>
  if (q.isError) return <Alert title="Tracking is unavailable">{errorMessage(q.error)}</Alert>
  if (!q.data.deliveries.length) return <p className="text-sm text-muted">Delivery tracking starts once the store has prepared your order.</p>
  return <div className="space-y-4">{q.data.deliveries.map((d) => <DeliveryCard key={d.delivery_id} d={d} />)}</div>
}

function DeliveryCard({ d }: { d: TrackingDelivery }) {
  const loc = d.location
  const hasPos = loc && loc.latitude !== undefined && loc.longitude !== undefined
  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-semibold">{d.store_name} <span className="text-sm font-normal text-muted">· {d.store_order_number}</span></p>
        <Status value={d.status} label={label(DELIVERY_STATUS, d.status)} />
      </div>
      {d.partner && <p className="mt-2 text-sm">Delivery partner: <strong>{d.partner.first_name}</strong>{d.partner.vehicle_type ? ` · ${d.partner.vehicle_type.toLowerCase()}` : ''}</p>}
      {d.otp && <p className="mt-2 rounded-control bg-pale p-3 text-sm">Delivery code: <strong className="text-lg tracking-widest">{d.otp}</strong><br /><span className="text-muted">Share it with the partner only when you receive your order.</span></p>}
      {hasPos && !TERMINAL.has(d.status) && (
        <div className="mt-3 rounded-control bg-canvas p-3 text-sm">
          <div className="mb-2">
            <MapView height={220} label="Delivery partner, store and your address on a map" fitToMarkers markers={[
              { lat: loc.latitude!, lon: loc.longitude!, label: 'Delivery partner', color: '#1d4ed8' },
              ...(d.dropoff ? [{ lat: d.dropoff.latitude, lon: d.dropoff.longitude, label: 'Your address', color: '#0f5132' }] : []),
              ...(d.pickup ? [{ lat: d.pickup.latitude, lon: d.pickup.longitude, label: d.store_name, color: '#b45309' }] : []),
            ]} />
            <p className="mt-1 flex flex-wrap gap-x-3 text-xs text-muted"><span><span className="inline-block size-2 rounded-full bg-[#1d4ed8]" aria-hidden="true" /> Partner</span><span><span className="inline-block size-2 rounded-full bg-[#0f5132]" aria-hidden="true" /> You</span>{d.pickup && <span><span className="inline-block size-2 rounded-full bg-[#b45309]" aria-hidden="true" /> Store</span>}</p>
          </div>
          <p className="flex items-center gap-2"><MapPin className="size-4" aria-hidden="true" />Last known position: {loc.latitude!.toFixed(4)}, {loc.longitude!.toFixed(4)}</p>
          <p className="mt-1 flex items-center gap-2 text-muted"><Clock className="size-4" aria-hidden="true" />Updated {ageText(loc.age_seconds)}</p>
          {loc.is_stale && <p role="status" className="mt-2 font-medium text-warn">The partner's location has not updated recently, so this position may be out of date.</p>}
          <a className="mt-2 inline-flex min-h-11 items-center gap-2 font-semibold text-forest underline" target="_blank" rel="noreferrer"
            href={googleMapsPlace(loc.latitude!, loc.longitude!)}><Navigation className="size-4" aria-hidden="true" />Open in Google Maps</a>
        </div>
      )}
      {!hasPos && !TERMINAL.has(d.status) && d.status !== 'PENDING_ASSIGNMENT' && d.status !== 'OFFERED' && <p className="mt-3 text-sm text-muted">Live location has not been shared yet.</p>}
      <p className="mt-3 text-xs text-muted">Arrival estimates are not available yet.</p>
      <div className="mt-4"><Timeline items={d.timeline.map((t, i, arr) => ({ key: `${t.status}-${i}`, title: label(DELIVERY_STATUS, t.status), at: t.at, note: t.note, tone: i === arr.length - 1 ? (t.status === 'FAILED' ? 'bad' : 'current') : 'done' }))} /></div>
    </Card>
  )
}
