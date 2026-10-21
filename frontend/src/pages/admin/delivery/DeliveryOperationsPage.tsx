import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Map as MapIcon, Wallet } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Modal, QueryBoundary, useToast } from '@/components/kit'
import { MapView } from '@/components/location/MapView'
import { SelectCheckbox, TabPanel, Tabs } from '@/components/management'
import { Alert, Button, Card, Field, Input, PageHeader, Select } from '@/components/ui'
import { errorMessage, fieldErrors } from '@/lib/api'
import { formatDateTime, formatMoney } from '@/lib/format'
import { adminEarnings, createZone, deliveryOperations, markEarningsPaid, updateZone, zones } from '@/services/delivery'
import type { Zone } from '@/types/delivery'

const REASONS: Record<string, string> = { CUSTOMER_UNAVAILABLE: 'Customer unavailable', WRONG_ADDRESS: 'Wrong or unreachable address', CUSTOMER_REFUSED: 'Customer refused', UNSAFE_LOCATION: 'Unsafe location', VEHICLE_PROBLEM: 'Vehicle problem', OTHER: 'Other' }

function Stat({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return <div className="rounded-control bg-canvas p-3"><p className="text-xs text-muted">{label}</p><p className="text-xl font-semibold tabular-nums text-forest">{value}</p>{hint && <p className="text-xs text-muted">{hint}</p>}</div>
}

function Overview() {
  const [days, setDays] = useState(30)
  const q = useQuery({ queryKey: ['delivery-ops', days], queryFn: () => deliveryOperations(days) })
  const e = q.data?.economics
  return (
    <QueryBoundary query={q} skeleton="detail">
      {q.data && e && (
        <div className="space-y-5">
          <div className="flex items-center gap-2"><label htmlFor="ops-days" className="text-sm">Period</label>
            <Select id="ops-days" value={String(days)} onChange={(ev) => setDays(Number(ev.target.value))} className="w-40"><option value="7">Last 7 days</option><option value="30">Last 30 days</option><option value="90">Last 90 days</option></Select></div>
          <Card className="p-4 sm:p-6">
            <h2 className="mb-1 text-lg font-semibold text-forest">Delivery money</h2>
            <p className="mb-4 text-sm text-muted">{e.priced_deliveries as number} priced deliveries. Each figure is reported separately; the customer fee is not profit.</p>
            <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-5">
              <Stat label="Fees before discounts" value={formatMoney(String(e.customer_fee_before_discount))} />
              <Stat label="Customers paid" value={formatMoney(String(e.customer_fee))} hint={`Tax collected ${formatMoney(String(e.delivery_tax))}`} />
              <Stat label="Zuuvi-funded offers" value={formatMoney(String(e.platform_funded_promotion))} />
              <Stat label="Store-funded offers" value={formatMoney(String(e.store_funded_promotion))} />
              <Stat label="Rider payouts (estimated)" value={formatMoney(String(e.partner_payout))} hint={`Recorded ${formatMoney(String(e.partner_earnings_recorded))}, unpaid ${formatMoney(String(e.partner_earnings_unpaid))}`} />
              <Stat label="Estimated delivery cost" value={formatMoney(String(e.estimated_cost))} />
              <Stat label="Zuuvi subsidy" value={formatMoney(String(e.platform_subsidy))} hint="Cost not recovered" />
              <Stat label="Delivery contribution" value={formatMoney(String(e.delivery_contribution))} hint="Fee above cost" />
              <Stat label="Estimated km" value={String(e.estimated_km)} />
            </div>
            <p className="mt-3 text-xs text-muted">{String(e.note)}</p>
          </Card>
          <div className="grid gap-5 lg:grid-cols-2">
            <Card className="p-4 sm:p-6">
              <h2 className="mb-3 text-lg font-semibold text-forest">Riders and deliveries</h2>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                <Stat label="Riders online" value={`${q.data.partners.online} / ${q.data.partners.approved}`} />
                <Stat label="Active deliveries" value={q.data.deliveries.active} />
                <Stat label="Waiting for a rider" value={q.data.deliveries.waiting_for_partner} />
                <Stat label="Need attention" value={q.data.deliveries.needs_attention} />
                <Stat label="Failed attempts" value={q.data.deliveries.failed_attempts} />
              </div>
              {q.data.deliveries.failure_reasons.length > 0 && <ul className="mt-3 text-sm">{q.data.deliveries.failure_reasons.map((r) => <li key={r.failure_reason} className="flex justify-between"><span>{REASONS[r.failure_reason] ?? r.failure_reason}</span><span className="tabular-nums">{r.n}</span></li>)}</ul>}
              <Link to="/admin/deliveries" className="mt-3 inline-flex min-h-11 items-center text-sm font-medium text-forest hover:underline">Open deliveries</Link>
            </Card>
            <Card className="p-4 sm:p-6">
              <h2 className="mb-3 text-lg font-semibold text-forest">Needs fixing</h2>
              {q.data.stores_with_location_problems.length === 0 && q.data.orders_with_invalid_destination.length === 0 ? <p className="text-sm text-muted">Nothing to fix.</p> : (
                <ul className="space-y-2 text-sm">
                  {q.data.stores_with_location_problems.map((s) => <li key={s.id}><Link className="font-medium text-forest hover:underline" to={`/admin/stores/${s.id}`}>{s.name}</Link> <span className="text-muted">({s.store_code})</span><br /><span className="text-warn">{s.problems.join(' ')}</span></li>)}
                  {q.data.orders_with_invalid_destination.map((o) => <li key={o.order_number}>Order {o.order_number}: delivery address has no map pin ({formatDateTime(o.placed_at)})</li>)}
                </ul>
              )}
              {q.data.needs_review.length > 0 && (<>
                <h3 className="mb-1 mt-4 font-semibold">Fees to review</h3>
                <ul className="text-sm">{q.data.needs_review.map((r) => <li key={r.store_order} className="flex justify-between gap-2"><span>{r.store_order} · {r.why}</span><span className="tabular-nums">{formatMoney(r.customer_fee)} / cost {formatMoney(r.estimated_cost)}</span></li>)}</ul>
              </>)}
            </Card>
          </div>
        </div>
      )}
    </QueryBoundary>
  )
}

function ZoneEditor({ zone, onClose }: { zone: Zone | null; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [v, setV] = useState({ name: zone?.name ?? '', district: zone?.district ?? '', locality: zone?.locality ?? '', service_area_surcharge: zone?.service_area_surcharge ?? '0', is_active: zone?.is_active ?? true })
  const [points, setPoints] = useState<[number, number][]>(zone?.polygon ?? [])
  const save = useMutation({
    mutationFn: () => (zone ? updateZone(zone.id, { ...v, polygon: points }) : createZone({ ...v, polygon: points })),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ['delivery-zones'] }); toast('success', 'Zone saved.'); onClose() },
  })
  const errs = fieldErrors(save.error)
  return (
    <Modal open onClose={onClose} title={zone ? `Edit ${zone.name}` : 'New delivery zone'}
      footer={<><Button variant="outline" onClick={onClose}>Cancel</Button><Button loading={save.isPending} disabled={!v.name.trim() || (points.length > 0 && points.length < 3)} onClick={() => save.mutate()}>Save zone</Button></>}>
      <div className="space-y-3">
        {save.isError && Object.keys(errs).length === 0 && <Alert tone="error">{errorMessage(save.error)}</Alert>}
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Name" required error={errs.name}>{(p) => <Input {...p} value={v.name} onChange={(e) => setV({ ...v, name: e.target.value })} />}</Field>
          <Field label="District">{(p) => <Input {...p} value={v.district} onChange={(e) => setV({ ...v, district: e.target.value })} />}</Field>
          <Field label="Locality">{(p) => <Input {...p} value={v.locality} onChange={(e) => setV({ ...v, locality: e.target.value })} />}</Field>
          <Field label="Hard-to-reach surcharge (₹)" hint="Added to the customer fee for addresses inside">{(p) => <Input {...p} inputMode="decimal" value={v.service_area_surcharge} onChange={(e) => setV({ ...v, service_area_surcharge: e.target.value })} />}</Field>
        </div>
        <label className="flex min-h-11 items-center gap-2 text-sm"><input type="checkbox" className="size-4 accent-forest" checked={v.is_active} onChange={(e) => setV({ ...v, is_active: e.target.checked })} />Active</label>
        <p className="text-sm">Area: tap the map to add corner points ({points.length} so far{points.length > 0 && points.length < 3 ? ', need at least 3' : ''}).</p>
        <MapView polygon={points} onMapClick={(lat, lon) => setPoints((p) => [...p, [Number(lat.toFixed(6)), Number(lon.toFixed(6))]])} height={300} label="Tap to add zone corners" />
        {errs.polygon && <p className="text-sm text-danger">{errs.polygon}</p>}
        <div className="flex gap-2"><Button size="sm" variant="outline" disabled={!points.length} onClick={() => setPoints((p) => p.slice(0, -1))}>Undo last point</Button><Button size="sm" variant="ghost" disabled={!points.length} onClick={() => setPoints([])}>Clear area</Button></div>
      </div>
    </Modal>
  )
}

function Zones() {
  const q = useQuery({ queryKey: ['delivery-zones'], queryFn: zones })
  const [editing, setEditing] = useState<Zone | 'new' | null>(null)
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted">Zones can carry their own pricing version or a hard-to-reach surcharge, and stores can use a drawn zone instead of a radius as their delivery area.</p>
      <Button onClick={() => setEditing('new')}>Add zone</Button>
      <QueryBoundary query={q} isEmpty={q.data?.length === 0} empty={{ icon: MapIcon, title: 'No zones', text: 'Stores use their delivery radius until you draw zones.' }}>
        <ul className="divide-y divide-line rounded-control ring-1 ring-line">{q.data?.map((z) => (
          <li key={z.id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-3 text-sm">
            <span><b>{z.name}</b> {!z.is_active && <span className="ml-1 text-xs text-muted">(inactive)</span>}<br /><span className="text-muted">{[z.locality, z.district, z.state].filter(Boolean).join(', ')} · {z.polygon.length ? `${z.polygon.length} corners` : 'no area drawn'} · {z.store_count} stores · surcharge {formatMoney(z.service_area_surcharge)}</span></span>
            <Button size="sm" variant="outline" onClick={() => setEditing(z)}>Edit</Button>
          </li>))}</ul>
      </QueryBoundary>
      {editing && <ZoneEditor zone={editing === 'new' ? null : editing} onClose={() => setEditing(null)} />}
    </div>
  )
}

function Earnings() {
  const qc = useQueryClient()
  const toast = useToast()
  const [status, setStatus] = useState('UNPAID')
  const [sel, setSel] = useState<Set<number>>(new Set())
  const [ref, setRef] = useState('')
  const q = useQuery({ queryKey: ['admin-earnings', status], queryFn: () => adminEarnings(status) })
  const pay = useMutation({ mutationFn: () => markEarningsPaid([...sel], ref), onSuccess: (r) => { toast('success', `${r.updated} marked paid.`); setSel(new Set()); setRef(''); void qc.invalidateQueries({ queryKey: ['admin-earnings'] }) } })
  const total = (q.data ?? []).filter((e) => sel.has(e.id)).reduce((s, e) => s + Number(e.amount), 0)
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Show">{(p) => <Select {...p} value={status} onChange={(e) => { setStatus(e.target.value); setSel(new Set()) }}><option value="UNPAID">Unpaid</option><option value="PAID">Paid</option></Select>}</Field>
        {status === 'UNPAID' && sel.size > 0 && <>
          <Field label="Payout reference" hint="UPI / bank reference">{(p) => <Input {...p} value={ref} onChange={(e) => setRef(e.target.value)} />}</Field>
          <Button loading={pay.isPending} disabled={!ref.trim()} onClick={() => pay.mutate()}>Mark {sel.size} paid ({formatMoney(total)})</Button>
        </>}
      </div>
      {pay.isError && <Alert tone="error">{errorMessage(pay.error)}</Alert>}
      <QueryBoundary query={q} isEmpty={q.data?.length === 0} empty={{ icon: Wallet, title: status === 'UNPAID' ? 'Nothing to pay' : 'No paid earnings yet', text: 'Earnings are created when riders complete deliveries.' }}>
        <ul className="divide-y divide-line rounded-control ring-1 ring-line">{q.data?.map((e) => (
          <li key={e.id} className="flex items-center gap-3 px-4 py-3 text-sm">
            {status === 'UNPAID' && <SelectCheckbox label={`Select earning ${e.id}`} checked={sel.has(e.id)} onChange={(on) => setSel((s) => { const n = new Set(s); if (on) n.add(e.id); else n.delete(e.id); return n })} />}
            <span className="min-w-0 flex-1"><b>{e.partner}</b> · {e.kind_label} · {e.store_order ?? '—'}<br /><span className="text-xs text-muted">{formatDateTime(e.created_at)}{e.payout_reference ? ` · paid ${e.payout_reference}` : ''} · {String(e.breakdown.source ?? '')}</span></span>
            <span className="tabular-nums font-semibold">{formatMoney(e.amount)}</span>
          </li>))}</ul>
      </QueryBoundary>
    </div>
  )
}

export default function DeliveryOperationsPage() {
  const [tab, setTab] = useState('overview')
  return (
    <>
      <PageHeader title="Delivery operations" subtitle="Costs, subsidies, riders, failed deliveries, zones and payouts." />
      <Tabs label="Delivery operations" active={tab} onChange={setTab} tabs={[{ id: 'overview', label: 'Overview' }, { id: 'zones', label: 'Zones' }, { id: 'earnings', label: 'Rider payouts' }]} />
      {tab === 'overview' && <TabPanel id="ops-overview"><Overview /></TabPanel>}
      {tab === 'zones' && <TabPanel id="ops-zones"><Zones /></TabPanel>}
      {tab === 'earnings' && <TabPanel id="ops-earnings"><Earnings /></TabPanel>}
    </>
  )
}
