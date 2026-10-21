import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Alert, Button, Card, Field, Input, Select } from '@/components/ui'
import { errorMessage, fieldErrors } from '@/lib/api'
import { formatMoney } from '@/lib/format'
import { simulate } from '@/services/delivery'
import { listStores } from '@/services/management'
import type { PricingSettings, PricingVersion, PricingVersions } from '@/types/delivery'
import { SECTIONS, toForm, toSettings } from './DeliveryPricingPage'

function Row({ label, value, hint, strong }: { label: string; value: string; hint?: string; strong?: boolean }) {
  return <div className="flex items-baseline justify-between gap-3 py-1"><dt className="text-sm text-muted">{label}{hint && <span className="block text-xs">{hint}</span>}</dt><dd className={`tabular-nums ${strong ? 'font-semibold text-forest' : 'text-sm'}`}>{value}</dd></div>
}

const QUICK = ['energy_price', 'efficiency_km_per_unit', 'operational_multiplier', 'maintenance_per_km', 'rider_pay_per_order', 'overhead_per_order', 'failure_cost_rate', 'pricing_mode', 'base_fee', 'included_km', 'per_km_rate', 'min_fee', 'max_fee', 'customer_recovery_ratio']

/** Calls the same server engine as checkout. Inputs here are simulated; nothing is saved. */
export function Simulator({ active, choices }: { active: PricingVersion; choices: PricingVersions['choices'] }) {
  const [form, setForm] = useState(() => toForm(active))
  const [mode, setMode] = useState<'distance' | 'store'>('distance')
  const [km, setKm] = useState('5')
  const [store, setStore] = useState('')
  const [lat, setLat] = useState('')
  const [lon, setLon] = useState('')
  const [subtotal, setSubtotal] = useState('300')
  const [peak, setPeak] = useState(false)
  const [heavy, setHeavy] = useState(false)
  const stores = useQuery({ queryKey: ['sim-stores'], queryFn: () => listStores({ status: 'ACTIVE' }), enabled: mode === 'store' })
  const run = useMutation({
    mutationFn: () => {
      const all = toSettings(form)
      const overrides: PricingSettings = {}
      for (const k of QUICK) { const v = all[k]; if (v !== undefined) overrides[k] = v }
      return simulate({ ...(mode === 'store' ? { store: Number(store), lat, lon } : { distance_km: km }), items_subtotal: subtotal, is_peak: peak, heavy, overrides })
    },
  })
  const r = run.data?.result
  const defs = SECTIONS.flatMap((s) => s.fields).filter((f) => QUICK.includes(f.key))
  const errs = fieldErrors(run.error)
  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_24rem]">
      <Card className="space-y-4 p-4 sm:p-6">
        <Alert tone="info">Simulated inputs. Change any number to see its effect; nothing is saved and checkout is not affected.</Alert>
        <div className="flex gap-4 text-sm" role="radiogroup" aria-label="Trip">
          <label className="flex min-h-11 items-center gap-2"><input type="radio" checked={mode === 'distance'} onChange={() => setMode('distance')} className="accent-forest" />Enter a road distance</label>
          <label className="flex min-h-11 items-center gap-2"><input type="radio" checked={mode === 'store'} onChange={() => setMode('store')} className="accent-forest" />Store and destination</label>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          {mode === 'distance' ? <Field label="Road distance (km)" error={errs.distance_km}>{(p) => <Input {...p} inputMode="decimal" value={km} onChange={(e) => setKm(e.target.value)} />}</Field> : <>
            <Field label="Store">{(p) => <Select {...p} value={store} onChange={(e) => setStore(e.target.value)}><option value="">Choose…</option>{stores.data?.results.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</Select>}</Field>
            <div className="grid grid-cols-2 gap-2"><Field label="Latitude">{(p) => <Input {...p} inputMode="decimal" value={lat} onChange={(e) => setLat(e.target.value)} />}</Field><Field label="Longitude">{(p) => <Input {...p} inputMode="decimal" value={lon} onChange={(e) => setLon(e.target.value)} />}</Field></div>
          </>}
          <Field label="Items subtotal (₹)" hint="For free-delivery and discount rules">{(p) => <Input {...p} inputMode="decimal" value={subtotal} onChange={(e) => setSubtotal(e.target.value)} />}</Field>
          <div className="flex flex-col justify-end gap-1 text-sm">
            <label className="flex min-h-9 items-center gap-2"><input type="checkbox" className="accent-forest" checked={peak} onChange={(e) => setPeak(e.target.checked)} />Busy hours</label>
            <label className="flex min-h-9 items-center gap-2"><input type="checkbox" className="accent-forest" checked={heavy} onChange={(e) => setHeavy(e.target.checked)} />Heavy / bulky order</label>
          </div>
        </div>
        <details className="rounded-control border border-line p-3" open>
          <summary className="cursor-pointer text-sm font-medium text-forest">Assumptions (from the current version; edit to test)</summary>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            {defs.map((f) => (
              <Field key={f.key} label={`${f.label}${f.unit ? ` (${f.unit})` : ''}`} error={errs[f.key]}>
                {(p) => f.kind === 'choice'
                  ? <Select {...p} value={String(form[f.key])} onChange={(e) => setForm((v) => ({ ...v, [f.key]: e.target.value }))}>{choices[f.choices!].map(([v, l]) => <option key={v} value={v}>{l}</option>)}</Select>
                  : <Input {...p} inputMode="decimal" value={String(form[f.key])} onChange={(e) => setForm((v) => ({ ...v, [f.key]: e.target.value }))} />}
              </Field>
            ))}
          </div>
        </details>
        <Button onClick={() => run.mutate()} loading={run.isPending} disabled={mode === 'store' && (!store || !lat || !lon)}>Calculate</Button>
        {run.isError && Object.keys(errs).length === 0 && <Alert tone="error">{errorMessage(run.error)}</Alert>}
      </Card>
      <Card className="h-fit space-y-3 p-4 sm:p-6 lg:sticky lg:top-20" aria-live="polite">
        <h2 className="text-lg font-semibold text-forest">Estimated result</h2>
        {!r ? <p className="text-sm text-muted">Press Calculate.</p> : (
          <>
            <dl className="divide-y divide-line">
              <Row label="Road distance" value={`${r.distance_km} km${r.distance_source === 'estimated' ? ' (estimated)' : ''}`} />
              <Row label="Operational distance" value={`${Number(r.cost.operational_km).toFixed(2)} km`} hint="Road km × distance factor" />
              <Row label="Fuel cost per km" value={`₹${Number(r.cost.fuel_cost_per_km).toFixed(3)}`} />
              <Row label="Fuel" value={formatMoney(r.cost.fuel_cost)} />
              <Row label="Maintenance" value={formatMoney(r.cost.maintenance_cost)} />
              <Row label="Rider pay" value={formatMoney(r.cost.rider_compensation)} />
              <Row label="Overhead" value={formatMoney(r.cost.overhead)} />
              <Row label="Failed-delivery allowance" value={formatMoney(r.cost.failure_allowance)} />
              <Row label="Estimated cost" value={formatMoney(r.estimated_cost)} strong />
            </dl>
            <dl className="divide-y divide-line">
              <Row label="Customer fee before discount" value={formatMoney(r.customer_fee_before_discount)} hint={Number(r.capped_by_max_fee) > 0 ? `Capped: ${formatMoney(r.capped_by_max_fee)} above the maximum` : undefined} />
              {Number(r.delivery_discount) > 0 && <Row label={`Discount (paid by ${r.discount_funded_by === 'STORE' ? 'store' : 'Zuuvi'})`} value={`−${formatMoney(r.delivery_discount)}`} />}
              <Row label="Customer pays for delivery" value={formatMoney(r.customer_total)} strong />
              <Row label="Rider payout" value={formatMoney(r.partner_payout)} />
              <Row label={Number(r.platform_subsidy) > 0 ? 'Zuuvi subsidy (unrecovered cost)' : 'Delivery contribution'} value={formatMoney(Number(r.platform_subsidy) > 0 ? r.platform_subsidy : r.delivery_contribution)} strong />
            </dl>
            {r.notes.map((n) => <p key={n} className="text-xs text-muted">{n}</p>)}
            <p className="text-xs text-muted">Based on {run.data?.based_on}{run.data?.overridden.length ? ` with ${run.data.overridden.length} simulated assumptions` : ''}.</p>
          </>
        )}
      </Card>
    </div>
  )
}
