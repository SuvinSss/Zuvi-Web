import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { QueryBoundary, useToast } from '@/components/kit'
import { TabPanel, Tabs, useBeforeUnload } from '@/components/management'
import { Alert, Button, Card, Field, Input, PageHeader, Select, Textarea } from '@/components/ui'
import { errorMessage, fieldErrors } from '@/lib/api'
import { formatDateTime } from '@/lib/format'
import { createPricingVersion, pricingVersions } from '@/services/delivery'
import type { PricingSettings, PricingVersion, PricingVersions } from '@/types/delivery'
import { Simulator } from './Simulator'

type Kind = 'money' | 'number' | 'ratio' | 'bool' | 'text' | 'choice' | 'datetime'
interface Def { key: string; label: string; kind: Kind; hint?: string; unit?: string; choices?: keyof PricingVersions['choices']; optional?: boolean }

export const SECTIONS: { title: string; intro: string; fields: Def[] }[] = [
  { title: 'Fuel and vehicle', intro: 'What it costs to run the vehicle for one kilometre.', fields: [
    { key: 'fuel_type', label: 'Fuel / energy', kind: 'choice', choices: 'fuel_type' },
    { key: 'energy_price', label: 'Price per litre / kWh / kg', kind: 'money', unit: '₹', hint: 'Use the verified local price, not a statewide average.' },
    { key: 'energy_price_source', label: 'Where this price came from', kind: 'text', hint: 'e.g. "IOCL pump, Paravur, checked by Anu"' },
    { key: 'energy_price_verified_at', label: 'Price last verified', kind: 'datetime', optional: true },
    { key: 'efficiency_km_per_unit', label: 'Mileage (km per litre / kWh / kg)', kind: 'number', hint: 'Must be above zero. A typical delivery motorcycle does 35–50 km/litre.' },
    { key: 'maintenance_per_km', label: 'Maintenance and tyre wear', kind: 'money', unit: '₹/km' },
  ] },
  { title: 'Rider pay', intro: 'What the delivery partner earns. Each part is counted once.', fields: [
    { key: 'rider_pay_per_order', label: 'Per delivered order', kind: 'money', unit: '₹' },
    { key: 'rider_pay_per_km', label: 'Per km (store → customer)', kind: 'money', unit: '₹/km' },
    { key: 'rider_fixed_daily_pay', label: 'Fixed daily pay', kind: 'money', unit: '₹/day', hint: 'Spread over the expected orders below.' },
    { key: 'rider_expected_orders_per_day', label: 'Expected orders per rider per day', kind: 'number' },
    { key: 'rider_pay_per_failed_attempt', label: 'Per failed attempt (not rider\'s fault)', kind: 'money', unit: '₹' },
  ] },
  { title: 'Operations', intro: 'Extra distance and overheads behind each delivery.', fields: [
    { key: 'operational_multiplier', label: 'Operational distance factor', kind: 'number', unit: '×', hint: 'Operational km = road km × this. 1.6 typical; 2.0 = full return trip for an isolated order.' },
    { key: 'overhead_per_order', label: 'Overhead per order', kind: 'money', unit: '₹', hint: 'Dispatch, support, software.' },
    { key: 'overhead_per_km', label: 'Overhead per km', kind: 'money', unit: '₹/km' },
    { key: 'failure_cost_rate', label: 'Failed-delivery allowance', kind: 'ratio', unit: '%', hint: 'Share of direct cost set aside for failures and reattempts. Replace with your real rate when you have it.' },
    { key: 'special_handling_cost', label: 'Extra cost for heavy / bulky orders', kind: 'money', unit: '₹' },
    { key: 'road_fallback_factor', label: 'Road-distance estimate factor', kind: 'number', unit: '×', hint: 'Only used when the road route is unavailable: straight line × this.' },
    { key: 'allow_estimated_distance', label: 'Allow orders when the road distance is only estimated', kind: 'bool' },
    { key: 'max_service_km', label: 'Maximum delivery distance', kind: 'number', unit: 'km', optional: true },
  ] },
  { title: 'Customer delivery fee', intro: 'What the customer pays. This is separate from cost and rider pay.', fields: [
    { key: 'pricing_mode', label: 'Pricing method', kind: 'choice', choices: 'pricing_mode' },
    { key: 'base_fee', label: 'Base fee', kind: 'money', unit: '₹' },
    { key: 'included_km', label: 'Distance included in base fee', kind: 'number', unit: 'km' },
    { key: 'per_km_rate', label: 'Each extra km', kind: 'money', unit: '₹/km' },
    { key: 'distance_bands', label: 'Distance bands (for "Distance bands")', kind: 'text', hint: 'One per line: up-to-km = fee, e.g. "2 = 25". Beyond the last band, each extra km is charged.' },
    { key: 'customer_recovery_ratio', label: 'Cost recovered from customer (cost-aware)', kind: 'ratio', unit: '%' },
    { key: 'max_platform_subsidy_per_order', label: 'Most Zuuvi pays towards one delivery (hybrid)', kind: 'money', unit: '₹' },
    { key: 'min_fee', label: 'Minimum fee', kind: 'money', unit: '₹' },
    { key: 'max_fee', label: 'Maximum fee', kind: 'money', unit: '₹', hint: 'Cost above this is recorded as platform subsidy.' },
    { key: 'allow_above_max_fee', label: 'Allow fees above the maximum', kind: 'bool' },
    { key: 'rounding', label: 'Rounding', kind: 'choice', choices: 'rounding' },
  ] },
  { title: 'Offers', intro: 'Every discount says who pays for it.', fields: [
    { key: 'free_delivery_threshold', label: 'Free delivery when a store\'s items reach', kind: 'money', unit: '₹', optional: true, hint: 'Empty = no free delivery.' },
    { key: 'free_delivery_funded_by', label: 'Free delivery paid by', kind: 'choice', choices: 'funder' },
    { key: 'delivery_discount_amount', label: 'Flat delivery discount', kind: 'money', unit: '₹' },
    { key: 'delivery_discount_min_order', label: '…on orders of at least', kind: 'money', unit: '₹' },
    { key: 'delivery_discount_funded_by', label: 'Delivery discount paid by', kind: 'choice', choices: 'funder' },
  ] },
  { title: 'Surcharges and tax', intro: 'Only charged when they apply.', fields: [
    { key: 'peak_surcharge', label: 'Busy-hour surcharge', kind: 'money', unit: '₹' },
    { key: 'peak_windows', label: 'Busy hours (India time)', kind: 'text', hint: 'One per line: days start-end, e.g. "0-6 18:00-21:00" (0 = Monday).' },
    { key: 'heavy_surcharge', label: 'Heavy / bulky surcharge', kind: 'money', unit: '₹' },
    { key: 'delivery_tax_rate', label: 'Tax on delivery fee', kind: 'ratio', unit: '%', hint: 'Keep 0 until your accountant confirms the tax treatment.' },
    { key: 'tax_treatment_confirmed', label: 'Tax treatment confirmed by accountant', kind: 'bool' },
  ] },
  { title: 'Status', intro: '', fields: [
    { key: 'is_illustrative', label: 'These are example numbers, not verified costs', kind: 'bool' },
    { key: 'notes', label: 'Notes', kind: 'text' },
  ] },
]

type Form = Record<string, string | boolean>

const bandsToText = (b: unknown) => (Array.isArray(b) ? b.map((x: { up_to_km: number; fee: number }) => `${x.up_to_km} = ${x.fee}`).join('\n') : '')
const textToBands = (t: string) => t.split('\n').map((l) => l.trim()).filter(Boolean).map((l) => { const [k, f] = l.split('=').map((x) => x.trim()); return { up_to_km: Number(k), fee: Number(f) } })
const windowsToText = (w: unknown) => (Array.isArray(w) ? w.map((x: { days: number[]; start: string; end: string }) => `${Math.min(...x.days)}-${Math.max(...x.days)} ${x.start}-${x.end}`).join('\n') : '')
const textToWindows = (t: string) => t.split('\n').map((l) => l.trim()).filter(Boolean).map((l) => {
  const [days = '', times = ''] = l.split(/\s+/)
  const [a = 0, b = a] = days.split('-').map(Number)
  const [start = '', end = ''] = times.split('-')
  return { days: Array.from({ length: Math.max(0, b - a + 1) }, (_, i) => a + i), start, end }
})
const toLocal = (iso: unknown) => (typeof iso === 'string' && iso ? new Date(new Date(iso).getTime() - new Date(iso).getTimezoneOffset() * 60000).toISOString().slice(0, 16) : '')

export function toForm(v: PricingVersion): Form {
  const out: Form = {}
  for (const s of SECTIONS) for (const f of s.fields) {
    const raw = v[f.key]
    if (f.key === 'distance_bands') out[f.key] = bandsToText(raw)
    else if (f.key === 'peak_windows') out[f.key] = windowsToText(raw)
    else if (f.kind === 'bool') out[f.key] = Boolean(raw)
    else if (f.kind === 'ratio') out[f.key] = raw == null ? '' : String(Number((Number(raw) * 100).toFixed(2)))
    else if (f.kind === 'datetime') out[f.key] = toLocal(raw)
    else out[f.key] = raw == null ? '' : String(raw)
  }
  return out
}

export function toSettings(form: Form): PricingSettings {
  const out: PricingSettings = {}
  for (const s of SECTIONS) for (const f of s.fields) {
    const val = form[f.key]
    if (f.key === 'distance_bands') out[f.key] = textToBands(String(val))
    else if (f.key === 'peak_windows') out[f.key] = textToWindows(String(val))
    else if (f.kind === 'bool') out[f.key] = Boolean(val)
    else if (f.kind === 'ratio') out[f.key] = val === '' ? '0' : String(Number(val) / 100)
    else if (f.kind === 'datetime') out[f.key] = val ? new Date(String(val)).toISOString() : null
    else if (f.optional && val === '') out[f.key] = null
    else out[f.key] = String(val)
  }
  return out
}

function SettingsForm({ data }: { data: PricingVersions }) {
  const qc = useQueryClient()
  const toast = useToast()
  const active = data.active!
  const [form, setForm] = useState<Form>(() => toForm(active))
  const [reason, setReason] = useState('')
  const [when, setWhen] = useState('')
  const [dirty, setDirty] = useState(false)
  useBeforeUnload(dirty)
  const save = useMutation({
    mutationFn: () => createPricingVersion({ settings: toSettings(form), reason, effective_from: when ? new Date(when).toISOString() : null }),
    onSuccess: (v) => { setDirty(false); setReason(''); void qc.invalidateQueries({ queryKey: ['delivery-pricing'] }); toast('success', `Saved as version ${v.version}${when ? ', scheduled' : ''}. Placed orders keep their old price.`) },
  })
  const errs = fieldErrors(save.error)
  const set = (k: string, v: string | boolean) => { setForm((f) => ({ ...f, [k]: v })); setDirty(true) }
  const ro = !data.can_edit
  const verified = active.energy_price_verified_at
  const [now] = useState(() => Date.now())
  const stale = !verified || now - new Date(verified).getTime() > 7 * 86400000

  return (
    <div className="space-y-5">
      {active.is_illustrative && <Alert tone="warn" title="Example numbers">These settings are planning assumptions, not verified business costs. Replace them with your real fuel price, mileage, rider pay and overheads before relying on the reports.</Alert>}
      <Alert tone={stale ? 'warn' : 'info'} title="Fuel price">
        ₹{active.energy_price as string} per unit → ₹{active.fuel_cost_per_km}/km. {verified ? `Last verified ${formatDateTime(verified)}.` : 'Never verified.'} This price is entered by an administrator; it is not fetched live.
      </Alert>
      {SECTIONS.map((s) => (
        <Card key={s.title} className="p-4 sm:p-6">
          <h2 className="text-lg font-semibold text-forest">{s.title}</h2>
          {s.intro && <p className="mb-4 text-sm text-muted">{s.intro}</p>}
          <fieldset disabled={ro} className="grid gap-4 sm:grid-cols-2">
            {s.fields.map((f) => f.kind === 'bool' ? (
              <label key={f.key} className="flex min-h-11 items-center gap-2 text-sm sm:col-span-2"><input type="checkbox" className="size-4 accent-forest" checked={Boolean(form[f.key])} onChange={(e) => set(f.key, e.target.checked)} />{f.label}</label>
            ) : (
              <Field key={f.key} label={`${f.label}${f.unit ? ` (${f.unit})` : ''}`} hint={f.hint} error={errs[f.key]} className={f.key === 'distance_bands' || f.key === 'peak_windows' || f.key === 'notes' || f.key === 'energy_price_source' ? 'sm:col-span-2' : ''}>
                {(p) => f.kind === 'choice' ? (
                  <Select {...p} value={String(form[f.key])} onChange={(e) => set(f.key, e.target.value)}>{data.choices[f.choices!].map(([v, l]) => <option key={v} value={v}>{l}</option>)}</Select>
                ) : f.key === 'distance_bands' || f.key === 'peak_windows' || f.key === 'notes' ? (
                  <Textarea {...p} rows={3} value={String(form[f.key])} onChange={(e) => set(f.key, e.target.value)} />
                ) : (
                  <Input {...p} type={f.kind === 'datetime' ? 'datetime-local' : 'text'} inputMode={f.kind === 'text' || f.kind === 'datetime' ? undefined : 'decimal'} value={String(form[f.key])} onChange={(e) => set(f.key, e.target.value)} />
                )}
              </Field>
            ))}
          </fieldset>
        </Card>
      ))}
      {!ro && (
        <Card className="space-y-3 p-4 sm:p-6">
          <h2 className="text-lg font-semibold text-forest">Save as a new version</h2>
          <p className="text-sm text-muted">Settings are never edited in place. Saving creates version {data.history.length ? Math.max(...data.history.map((h) => h.version)) + 1 : 1}; orders already placed keep the price they were charged.</p>
          {Object.keys(errs).length > 0 && <Alert tone="error" title="Please fix">{Object.entries(errs).map(([k, v]) => <span key={k} className="block">{k.replace(/_/g, ' ')}: {v}</span>)}</Alert>}
          {save.isError && Object.keys(errs).length === 0 && <Alert tone="error">{errorMessage(save.error)}</Alert>}
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Reason for the change" required hint="Recorded in the audit history.">{(p) => <Input {...p} maxLength={255} value={reason} onChange={(e) => setReason(e.target.value)} />}</Field>
            <Field label="Takes effect" hint="Empty = now.">{(p) => <Input {...p} type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} />}</Field>
          </div>
          <Button disabled={!reason.trim() || !dirty} loading={save.isPending} onClick={() => save.mutate()}>Save new version</Button>
        </Card>
      )}
    </div>
  )
}

function HistoryList({ data }: { data: PricingVersions }) {
  return (
    <div className="space-y-3">
      {data.scheduled.length > 0 && <Alert tone="info" title="Scheduled">{data.scheduled.map((v) => <p key={v.id}>Version {v.version} takes effect {formatDateTime(v.effective_from)}: {v.reason}</p>)}</Alert>}
      <ul className="divide-y divide-line rounded-control ring-1 ring-line">
        {data.history.map((v) => (
          <li key={v.id} className="flex flex-wrap items-baseline justify-between gap-2 px-4 py-3 text-sm">
            <span><b>Version {v.version}</b>{v.id === data.active?.id && <span className="ml-2 rounded-full bg-mint px-2 text-xs text-deep">In use</span>}{v.is_illustrative && <span className="ml-2 rounded-full bg-warn-bg px-2 text-xs text-warn">Example numbers</span>}<br /><span className="text-muted">{v.reason}</span></span>
            <span className="text-right text-xs text-muted">From {formatDateTime(v.effective_from)}<br />by {v.created_by ?? 'system'} · fuel ₹{v.energy_price as string}, {v.pricing_mode as string}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

export default function DeliveryPricingPage() {
  const q = useQuery({ queryKey: ['delivery-pricing'], queryFn: () => pricingVersions() })
  const [tab, setTab] = useState('settings')
  return (
    <>
      <PageHeader title="Delivery pricing & operations settings" subtitle="Costs, rider pay and the customer fee are calculated separately by the server. Changes create a new, audited version." />
      <Tabs label="Delivery pricing sections" active={tab} onChange={setTab} tabs={[{ id: 'settings', label: 'Settings' }, { id: 'simulator', label: 'Simulator' }, { id: 'history', label: 'History' }]} />
      <QueryBoundary query={q} skeleton="detail">
        {q.data && !q.data.active && <Alert tone="error">No delivery pricing is configured. Checkout cannot price deliveries.</Alert>}
        {q.data?.active && (
          <>
            {tab === 'settings' && <TabPanel id="settings"><SettingsForm key={q.data.active.id} data={q.data} /></TabPanel>}
            {tab === 'simulator' && <TabPanel id="simulator"><Simulator active={q.data.active} choices={q.data.choices} /></TabPanel>}
            {tab === 'history' && <TabPanel id="history"><HistoryList data={q.data} /></TabPanel>}
          </>
        )}
      </QueryBoundary>
    </>
  )
}
