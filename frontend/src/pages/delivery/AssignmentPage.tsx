import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { MapPin, Navigation, Phone } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { EvidencePanel } from '@/components/evidence'
import { FilePicker, Modal, QueryBoundary, ReasonDialog, Section, Status, useToast } from '@/components/kit'
import { Alert, Button, Card, Field, Input, PageHeader, Select, Textarea } from '@/components/ui'
import { errorMessage, fieldErrors } from '@/lib/api'
import { googleMapsDirections, MapView } from '@/components/location/MapView'
import { currentPosition, mapsLink, type Fix } from '@/lib/geo'
import { label } from '@/lib/labels'
import { completeDelivery, confirmPickupWithPhotos, deliveryAction, failDelivery, getDelivery, pingLocation } from '@/services/ops'
import type { DeliveryRecord } from '@/types/ops'
import { FAIL_REASONS, PARTNER_DELIVERY_STATUS } from './labels'

const LIVE = ['ACCEPTED', 'AT_STORE', 'IN_TRANSIT', 'ARRIVED']
const PING_EVERY_MS = 15_000

export default function AssignmentPage() {
  const id = Number(useParams().id)
  const qc = useQueryClient()
  const toast = useToast()
  const q = useQuery({ queryKey: ['delivery', id], queryFn: () => getDelivery(id), refetchInterval: (query) => (query.state.data?.status === 'OFFERED' ? 10_000 : false) })
  const set = (d: DeliveryRecord) => { qc.setQueryData(['delivery', id], d); void qc.invalidateQueries({ queryKey: ['assignments'] }); void qc.invalidateQueries({ queryKey: ['evidence', id] }) }
  const fail = (e: unknown) => toast('error', errorMessage(e))
  const act = useMutation({ mutationFn: (v: { action: 'accept' | 'reject' | 'arrive-store' | 'arrive'; body?: unknown }) => deliveryAction(id, v.action, v.body), onSuccess: set, onError: fail })
  const [rejecting, setRejecting] = useState(false)
  const [mode, setMode] = useState<null | 'pickup' | 'complete' | 'fail'>(null)
  const d = q.data
  return (
    <QueryBoundary query={q} skeleton="detail">
      {d && (
        <>
          <PageHeader title={d.store_name} subtitle={`Order ${d.order_number} · attempt ${d.attempt_number}`} actions={<Link className="inline-flex min-h-11 items-center text-sm font-semibold text-forest underline" to="/delivery/assignments">All deliveries</Link>} />
          <div className="space-y-4">
            <Card className="p-4"><div className="flex flex-wrap items-center justify-between gap-2"><Status value={d.status} label={label(PARTNER_DELIVERY_STATUS, d.status)} />{d.offer_expires_at && d.status === 'OFFERED' && <span className="text-sm text-warn">Offer expires {new Date(d.offer_expires_at).toLocaleTimeString('en-IN', { timeStyle: 'short' })}</span>}</div></Card>

            {LIVE.includes(d.status) && <LocationSharing deliveryId={d.id} />}
            {d.trip && (
              <Card className="grid grid-cols-3 gap-2 p-4 text-center">
                <div><p className="text-xs text-muted">Distance</p><p className="font-semibold tabular-nums">{Number(d.trip.distance_km).toFixed(1)} km</p>{d.trip.distance_source === 'estimated' && <p className="text-[0.7rem] text-muted">approx.</p>}</div>
                <div><p className="text-xs text-muted">You earn</p><p className="font-semibold tabular-nums text-forest">₹{Number(d.trip.estimated_payout).toFixed(0)}</p></div>
                <div><p className="text-xs text-muted">Time</p><p className="font-semibold tabular-nums">{d.trip.eta_minutes ? `~${d.trip.eta_minutes} min` : '—'}</p></div>
                <p className="col-span-3 text-xs text-muted">Pay is fixed when the customer orders and recorded when you complete the delivery.</p>
              </Card>
            )}

            {(d.pickup.latitude !== null || d.dropoff.latitude !== null) && (
              <Card className="space-y-2 p-3">
                <MapView height={220} label="Store and customer on the map" fitToMarkers markers={[
                  ...(d.pickup.latitude !== null && d.pickup.longitude !== null ? [{ lat: d.pickup.latitude, lon: d.pickup.longitude, label: `Pickup: ${d.pickup.name}`, color: '#b45309' }] : []),
                  ...(d.dropoff.latitude !== null && d.dropoff.longitude !== null ? [{ lat: d.dropoff.latitude, lon: d.dropoff.longitude, label: 'Drop-off', color: '#0f5132' }] : []),
                ]} />
                {d.pickup.latitude !== null && d.pickup.longitude !== null && d.dropoff.latitude !== null && d.dropoff.longitude !== null && (
                  <a className="inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-control bg-forest px-4 font-semibold text-white" target="_blank" rel="noreferrer"
                    href={googleMapsDirections([d.dropoff.latitude, d.dropoff.longitude], [d.pickup.latitude, d.pickup.longitude])}>
                    <Navigation className="size-4" aria-hidden="true" />Full route in Google Maps
                  </a>
                )}
              </Card>
            )}

            <Section title="Pickup">
              <Card className="space-y-2 p-4"><p className="font-semibold">{d.pickup.name}</p>
                {mapsLink(d.pickup.latitude, d.pickup.longitude) && <a className="inline-flex min-h-11 items-center gap-2 font-semibold text-forest underline" href={mapsLink(d.pickup.latitude, d.pickup.longitude)!} target="_blank" rel="noreferrer"><Navigation className="size-4" aria-hidden="true" />Navigate to store</a>}</Card>
            </Section>
            <Section title="Drop-off">
              <Card className="space-y-2 p-4">
                {d.customer ? (<>
                  <p className="font-semibold">{d.customer.name}</p>
                  <address className="text-sm not-italic"><MapPin className="mr-1 inline size-4" aria-hidden="true" />{[d.dropoff.line1, d.dropoff.line2, d.dropoff.landmark].filter(Boolean).join(', ')}<br />{d.dropoff.city} {d.dropoff.postal_code}</address>
                  <a className="inline-flex min-h-11 items-center gap-2 font-semibold text-forest underline" href={`tel:${d.customer.phone}`}><Phone className="size-4" aria-hidden="true" />Call {d.customer.phone}</a>
                  {d.customer.instructions && <Alert tone="info" title="Delivery instructions">{d.customer.instructions}</Alert>}
                </>) : <p className="text-sm text-muted">Customer details are shown after you accept. Area: {d.dropoff.city} {d.dropoff.postal_code}</p>}
                {mapsLink(d.dropoff.latitude, d.dropoff.longitude) && <a className="inline-flex min-h-11 items-center gap-2 font-semibold text-forest underline" href={mapsLink(d.dropoff.latitude, d.dropoff.longitude)!} target="_blank" rel="noreferrer"><Navigation className="size-4" aria-hidden="true" />Navigate to customer</a>}
              </Card>
            </Section>

            <div className="sticky bottom-16 z-10 -mx-4 flex flex-wrap gap-2 border-t border-line bg-white/95 p-3 backdrop-blur lg:static lg:mx-0 lg:border-0 lg:bg-transparent lg:p-0">
              {d.status === 'OFFERED' && <><Button size="lg" className="flex-1" loading={act.isPending && act.variables?.action === 'accept'} onClick={() => act.mutate({ action: 'accept' })}>Accept delivery</Button><Button size="lg" variant="outline" onClick={() => setRejecting(true)}>Decline</Button></>}
              {d.status === 'ACCEPTED' && <Button size="lg" className="flex-1" loading={act.isPending} onClick={() => act.mutate({ action: 'arrive-store' })}>I have reached the store</Button>}
              {d.status === 'AT_STORE' && <Button size="lg" className="flex-1" onClick={() => setMode('pickup')}>Confirm pickup</Button>}
              {d.status === 'IN_TRANSIT' && <Button size="lg" className="flex-1" loading={act.isPending} onClick={() => act.mutate({ action: 'arrive' })}>I have reached the customer</Button>}
              {d.status === 'ARRIVED' && <><Button size="lg" className="flex-1" onClick={() => setMode('complete')}>Complete delivery</Button><Button size="lg" variant="destructive" onClick={() => setMode('fail')}>Could not deliver</Button></>}
              {['ACCEPTED', 'AT_STORE', 'IN_TRANSIT'].includes(d.status) && <Button size="lg" variant="ghost" onClick={() => setMode('fail')}>Report a problem</Button>}
            </div>

            {['AT_STORE', 'IN_TRANSIT', 'ARRIVED', 'DELIVERED', 'FAILED'].includes(d.status) && <Section title="Proof"><EvidencePanel deliveryId={d.id} /></Section>}
          </div>
          <ReasonDialog open={rejecting} title="Decline this delivery?" field="Reason (optional)" optional confirm="Decline" danger busy={act.isPending} onClose={() => setRejecting(false)} onSubmit={(reason) => act.mutate({ action: 'reject', body: { reason } }, { onSuccess: () => setRejecting(false) })} />
          {mode === 'pickup' && <EvidenceDialog kind="pickup" delivery={d} onClose={() => setMode(null)} onDone={(r) => { set(r); setMode(null); toast('success', 'Pickup confirmed.') }} />}
          {mode === 'complete' && <EvidenceDialog kind="complete" delivery={d} onClose={() => setMode(null)} onDone={(r) => { set(r); setMode(null); toast('success', 'Delivery completed. Thank you!') }} />}
          {mode === 'fail' && <FailDialog delivery={d} onClose={() => setMode(null)} onDone={(r) => { set(r); setMode(null); toast('info', 'The problem was recorded. Support will follow up.') }} />}
        </>
      )}
    </QueryBoundary>
  )
}

/** Shares the partner's position while this page is open and sharing is switched on. Nothing is sent otherwise. */
function LocationSharing({ deliveryId }: { deliveryId: number }) {
  const [on, setOn] = useState(false)
  const [status, setStatus] = useState('Location sharing is off. Customers cannot see your position.')
  const last = useRef(0)
  useEffect(() => {
    if (!on) return
    const watch = navigator.geolocation.watchPosition(
      (p) => {
        const now = Date.now()
        if (now - last.current < PING_EVERY_MS) return
        last.current = now
        pingLocation(deliveryId, { latitude: p.coords.latitude.toFixed(6), longitude: p.coords.longitude.toFixed(6), accuracy_m: Number.isFinite(p.coords.accuracy) ? Math.round(p.coords.accuracy) : null })
          .then(() => setStatus(`Sharing your location · last sent ${new Date().toLocaleTimeString('en-IN', { timeStyle: 'short' })}`))
          .catch((e) => setStatus(`Could not send location: ${errorMessage(e)}`))
      },
      (e) => { setStatus(e.code === e.PERMISSION_DENIED ? 'Location permission is blocked. Allow it in your browser settings.' : 'Waiting for a GPS signal…'); if (e.code === e.PERMISSION_DENIED) setOn(false) },
      { enableHighAccuracy: true, maximumAge: 5000, timeout: 20000 },
    )
    return () => navigator.geolocation.clearWatch(watch)
  }, [on, deliveryId])
  return (
    <Card className="p-4">
      <label className="flex min-h-11 items-center justify-between gap-3 font-semibold"><span>Share my live location</span>
        <input type="checkbox" role="switch" className="size-6" checked={on} onChange={(e) => { if (e.target.checked && !('geolocation' in navigator)) { setStatus('This device cannot share its location.'); return } setOn(e.target.checked); setStatus(e.target.checked ? 'Getting your location…' : 'Location sharing is off. Customers cannot see your position.') }} /></label>
      <p role="status" className="mt-1 text-sm text-muted">{status}</p>
      <p className="mt-1 text-xs text-muted">Sharing works only while this screen stays open. Keep the screen on during the delivery.</p>
    </Card>
  )
}

function EvidenceDialog({ kind, delivery, onClose, onDone }: { kind: 'pickup' | 'complete'; delivery: DeliveryRecord; onClose: () => void; onDone: (d: DeliveryRecord) => void }) {
  const [photos, setPhotos] = useState<(File | null)[]>([null])
  const [v, setV] = useState({ notes: '', recipient_name: '', otp: '' })
  const [geoError, setGeoError] = useState('')
  const save = useMutation({
    mutationFn: async () => {
      let fix: Fix
      try { fix = await currentPosition() } catch (e) { setGeoError((e as Error).message); throw e }
      setGeoError('')
      const input = { latitude: fix.latitude, longitude: fix.longitude, accuracy_m: fix.accuracy_m, notes: v.notes, recipient_name: v.recipient_name, otp: v.otp, photos: photos.filter(Boolean) as File[] }
      return kind === 'pickup' ? confirmPickupWithPhotos(delivery.id, input) : completeDelivery(delivery.id, input)
    },
    onSuccess: onDone,
  })
  const fe = fieldErrors(save.error)
  const have = photos.filter(Boolean).length
  return (
    <Modal open onClose={onClose} title={kind === 'pickup' ? 'Confirm pickup' : 'Complete delivery'}>
      <form className="space-y-3" noValidate onSubmit={(e) => { e.preventDefault(); save.mutate() }}>
        {geoError && <Alert>{geoError}</Alert>}
        {save.isError && !geoError && !Object.keys(fe).length && <Alert>{errorMessage(save.error)}</Alert>}
        {Object.entries(fe).filter(([k]) => !['notes', 'recipient_name', 'otp'].includes(k)).map(([k, m]) => <Alert key={k}>{m}</Alert>)}
        <p className="text-sm text-muted">{kind === 'pickup' ? 'Take a photo of the packed order.' : 'A photo of the delivered order is required.'} Your current location is recorded with it.</p>
        {photos.map((p, i) => <FilePicker key={i} label={`Photo ${i + 1}${i === 0 ? ' *' : ''}`} capture="environment" file={p} onFile={(f) => setPhotos(photos.map((x, j) => (j === i ? f : x)))} />)}
        {photos.length < 3 && have === photos.length && <Button variant="outline" onClick={() => setPhotos([...photos, null])}>Add another photo</Button>}
        {kind === 'complete' && <>
          <Field label="Delivery code from the customer" error={fe.otp} hint="Ask the customer for the code shown in their order page.">{(p) => <Input {...p} inputMode="numeric" autoComplete="one-time-code" maxLength={10} value={v.otp} onChange={(e) => setV({ ...v, otp: e.target.value })} />}</Field>
          <Field label="Received by" error={fe.recipient_name}>{(p) => <Input {...p} value={v.recipient_name} onChange={(e) => setV({ ...v, recipient_name: e.target.value })} />}</Field>
        </>}
        <Field label="Notes (optional)" error={fe.notes}>{(p) => <Textarea {...p} rows={2} maxLength={2000} value={v.notes} onChange={(e) => setV({ ...v, notes: e.target.value })} />}</Field>
        <div className="flex justify-end gap-2 pt-2"><Button variant="outline" onClick={onClose}>Cancel</Button><Button type="submit" loading={save.isPending} disabled={have === 0}>{kind === 'pickup' ? 'Confirm pickup' : 'Complete delivery'}</Button></div>
      </form>
    </Modal>
  )
}

function FailDialog({ delivery, onClose, onDone }: { delivery: DeliveryRecord; onClose: () => void; onDone: (d: DeliveryRecord) => void }) {
  const [v, setV] = useState({ reason: 'CUSTOMER_UNAVAILABLE', note: '' })
  const save = useMutation({
    mutationFn: async () => {
      const fix = await currentPosition().catch(() => null) // location is helpful but must not block reporting a problem
      return failDelivery(delivery.id, { ...v, ...(fix ? { latitude: fix.latitude, longitude: fix.longitude } : {}) })
    },
    onSuccess: onDone,
  })
  const fe = fieldErrors(save.error)
  return (
    <Modal open onClose={onClose} title="Report a problem">
      <form className="space-y-3" noValidate onSubmit={(e) => { e.preventDefault(); save.mutate() }}>
        {save.isError && !Object.keys(fe).length && <Alert>{errorMessage(save.error)}</Alert>}
        <Field label="What happened?" error={fe.reason}>{(p) => <Select {...p} value={v.reason} onChange={(e) => setV({ ...v, reason: e.target.value })}>{FAIL_REASONS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</Select>}</Field>
        <Field label="Details" error={fe.note} required={v.reason === 'OTHER'}>{(p) => <Textarea {...p} rows={3} maxLength={2000} value={v.note} onChange={(e) => setV({ ...v, note: e.target.value })} />}</Field>
        <p className="text-sm text-muted">This ends the current attempt. An admin decides whether to retry.</p>
        <div className="flex justify-end gap-2 pt-2"><Button variant="outline" onClick={onClose}>Back</Button><Button type="submit" variant="destructive" loading={save.isPending}>Report problem</Button></div>
      </form>
    </Modal>
  )
}
