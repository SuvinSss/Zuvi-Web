import { useQuery } from '@tanstack/react-query'
import { Crosshair, Loader2, MapPin, Search } from 'lucide-react'
import { useRef, useState } from 'react'
import { Alert, Button, Field, Input, Select, Textarea } from '@/components/ui'
import { useDebounced } from '@/hooks/useDebounced'
import { errorMessage } from '@/lib/api'
import { currentPosition } from '@/lib/geo'
import { placeDetails, reversePlace, searchPlaces } from '@/services/delivery'
import type { Place } from '@/types/delivery'
import type { Address, AddressInput } from '@/types/platform'
import { MapView } from './MapView'

const POOR_ACCURACY_M = 100

export const emptyAddress = (): AddressInput => ({
  label: 'HOME', custom_label: '', recipient_name: '', phone_number: '', line1: '', line2: '', landmark: '', city: '', district: '',
  state: 'Kerala', postal_code: '', latitude: '', longitude: '', delivery_instructions: '', place_id: '', location_source: '', location_accuracy_m: null,
})

export function fromAddress(a: Address): AddressInput {
  const keys = Object.keys(emptyAddress()) as (keyof AddressInput)[]
  const out = emptyAddress()
  for (const k of keys) if (a[k as keyof Address] !== undefined && a[k as keyof Address] !== null) (out as Record<string, unknown>)[k] = a[k as keyof Address]
  return out
}

type Step = 'locate' | 'details'

/**
 * Swiggy-style address flow: find the place (current location, search or pin), check the pin on the map,
 * add house/landmark details, confirm. Location permission is requested only when the person taps the button.
 */
export function AddressPicker({ initial, saving, errors = {}, onSave, onCancel, submitLabel = 'Save address' }: {
  initial?: AddressInput | null; saving?: boolean; errors?: Record<string, string>; onSave: (input: AddressInput) => void; onCancel?: () => void; submitLabel?: string
}) {
  const [v, setV] = useState<AddressInput>(initial ?? emptyAddress())
  const [step, setStep] = useState<Step>(initial?.latitude ? 'details' : 'locate')
  const [query, setQuery] = useState('')
  const [locating, setLocating] = useState(false)
  const [message, setMessage] = useState<{ tone: 'info' | 'warn' | 'error'; text: string } | null>(null)
  const [confirmed, setConfirmed] = useState(Boolean(initial?.latitude))
  const [touched, setTouched] = useState<Set<string>>(new Set())
  const lookupSeq = useRef(0)
  // One autocomplete session per search (typing + one selection), so the provider bills it once. Same token on web and apps.
  const [session, setSession] = useState(() => crypto.randomUUID())
  const [opening, setOpening] = useState(false)

  const q = useDebounced(query.trim(), 400)
  const results = useQuery({ queryKey: ['geo-search', q, session], queryFn: () => searchPlaces(q, session, v.latitude && v.longitude ? { lat: v.latitude, lon: v.longitude } : null), enabled: q.length >= 3 && query.trim() === q, staleTime: 5 * 60_000, retry: false })
  const pin = v.latitude && v.longitude ? { lat: Number(v.latitude), lon: Number(v.longitude) } : null

  const set = (changes: Partial<AddressInput>) => setV((cur) => ({ ...cur, ...changes }))
  const typed = (key: keyof AddressInput) => (e: { target: { value: string } }) => { setTouched((t) => new Set(t).add(key)); set({ [key]: e.target.value } as Partial<AddressInput>) }

  /** Fill the address fields from a place, but never overwrite what the person typed themselves. */
  const applyPlace = (p: Place) => setV((cur) => {
    const keep = (key: keyof AddressInput, value: string) => (touched.has(key) && cur[key] ? cur[key] : value || cur[key]) as string
    return { ...cur, line2: keep('line2', [p.line1, p.locality].filter(Boolean).join(', ')), city: keep('city', p.city), district: keep('district', p.district),
      state: keep('state', p.state || 'Kerala'), postal_code: keep('postal_code', /^\d{6}$/.test(p.postal_code) ? p.postal_code : ''), place_id: p.place_id || cur.place_id }
  })

  const lookup = async (lat: number, lon: number) => {
    const seq = ++lookupSeq.current
    try {
      const r = await reversePlace(lat.toFixed(6), lon.toFixed(6))
      if (seq !== lookupSeq.current) return
      if (r.result) applyPlace(r.result)
      else setMessage({ tone: 'info', text: r.detail ?? 'We could not look up this point. Type the address below.' })
    } catch { if (seq === lookupSeq.current) setMessage({ tone: 'info', text: 'Address lookup failed. Type the address below.' }) }
  }

  const movePin = (lat: number, lon: number, source: AddressInput['location_source']) => {
    set({ latitude: lat.toFixed(6), longitude: lon.toFixed(6), location_source: source, ...(source !== 'GPS' ? { location_accuracy_m: null } : {}) })
    setConfirmed(false)
    void lookup(lat, lon)
  }

  const locateMe = async () => {
    setMessage(null); setLocating(true)
    try {
      const fix = await currentPosition()
      set({ location_accuracy_m: fix.accuracy_m })
      movePin(Number(fix.latitude), Number(fix.longitude), 'GPS')
      setStep('details')
      if (fix.accuracy_m !== null && fix.accuracy_m > POOR_ACCURACY_M) {
        setMessage({ tone: 'warn', text: `Your location is only accurate to about ${fix.accuracy_m} m. Drag the pin to your exact gate or building, or search for the address.` })
      }
    } catch (e) {
      setMessage({ tone: 'error', text: `${e instanceof Error ? e.message : errorMessage(e)} You can search for your address or tap the map instead.` })
    } finally { setLocating(false) }
  }

  const choose = async (picked: Place) => {
    let p = picked
    setQuery('')  // close suggestions first so a new session token never triggers another (billed) search
    if (p.needs_details || !p.latitude) {
      // Google suggestions carry no coordinates: fetch them with the same session token.
      setOpening(true)
      try {
        const r = await placeDetails(p.place_id, session)
        if (!r.result) { setMessage({ tone: 'info', text: r.detail ?? "We couldn't open that suggestion. Tap the map instead." }); return }
        p = r.result
      } catch { setMessage({ tone: 'info', text: "We couldn't open that suggestion. Tap the map instead." }); return } finally { setOpening(false); setSession(crypto.randomUUID()) }
    }
    set({ latitude: p.latitude, longitude: p.longitude, location_source: 'SEARCH', location_accuracy_m: null })
    applyPlace(p); setConfirmed(false); setQuery(''); setStep('details')
  }

  const searchDown = results.data && !results.data.available ? (results.data.detail ?? 'Search is unavailable. Tap the map to place the pin.') : ''

  const err = (k: string) => errors[k]
  const canSave = Boolean(pin && confirmed && v.line1.trim() && v.city.trim() && v.recipient_name.trim() && v.phone_number.trim())

  return (
    <div className="space-y-4">
      {step === 'locate' && (
        <div className="space-y-3">
          <div className="rounded-control bg-pale p-3 text-sm">
            <p className="font-medium text-forest">Where should we deliver?</p>
            <p className="text-muted">We use your location only to place the pin once, when you tap the button. It is not tracked.</p>
          </div>
          <Button variant="outline" icon={Crosshair} loading={locating} onClick={() => void locateMe()} className="w-full sm:w-auto">Use my current location</Button>
          <div className="relative">
            <label htmlFor="addr-search" className="mb-1 block text-sm font-medium">Search for your area, street or building</label>
            <Search className="pointer-events-none absolute left-3 top-[2.6rem] size-4 text-muted" aria-hidden="true" />
            <input id="addr-search" type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="e.g. Paravur market, Kollam"
              className="min-h-11 w-full rounded-control border border-line bg-white pl-9 pr-3 text-base focus:border-emerald focus:outline-none focus:ring-2 focus:ring-emerald/30 sm:text-sm"
              aria-describedby="addr-search-status" autoComplete="off" />
            <div id="addr-search-status" aria-live="polite" className="mt-1 text-xs text-muted">
              {results.isFetching ? <span className="inline-flex items-center gap-1"><Loader2 className="size-3 animate-spin" aria-hidden="true" />Searching…</span>
                : q.length >= 3 && results.data?.available && results.data.results.length === 0 ? 'No matches. Try a nearby landmark, or tap the map.' : null}
            </div>
            {results.data?.results && results.data.results.length > 0 && (
              <ul role="listbox" aria-label="Address suggestions" className="mt-1 divide-y divide-line rounded-control border border-line bg-white">
                {results.data.results.map((p) => (
                  <li key={`${p.place_id}-${p.latitude}`} role="option" aria-selected="false">
                    <button type="button" disabled={opening} onClick={() => void choose(p)} className="flex min-h-11 w-full items-start gap-2 px-3 py-2 text-left text-sm hover:bg-pale disabled:opacity-60">
                      <MapPin className="mt-0.5 size-4 shrink-0 text-emerald" aria-hidden="true" />
                      <span>{p.secondary ? <><span className="font-medium">{p.line1}</span><span className="block text-xs text-muted">{p.secondary}</span></> : p.label}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {results.data?.attribution && results.data.results.length > 0 && <p className="mt-1 text-right text-[0.7rem] text-muted">{results.data.attribution}</p>}
            {opening && <p className="mt-1 text-xs text-muted" role="status">Opening place…</p>}
          </div>
          <p className="text-sm text-muted">Or tap the map where you are:</p>
          <MapView value={pin} onPinChange={(lat, lon) => { movePin(lat, lon, 'PIN'); setStep('details') }} label="Tap to place your delivery pin" />
        </div>
      )}

      {searchDown && step === 'locate' && <Alert tone="info">{searchDown}</Alert>}
      {message && <Alert tone={message.tone === 'error' ? 'error' : message.tone === 'warn' ? 'warn' : 'info'}>{message.text}</Alert>}

      {step === 'details' && (
        <div className="space-y-4">
          <div>
            <div className="mb-1 flex items-center justify-between gap-2">
              <p className="text-sm font-medium">Check the pin. Drag it to your exact gate or building.</p>
              <Button size="sm" variant="ghost" onClick={() => setStep('locate')}>Change location</Button>
            </div>
            <MapView value={pin} onPinChange={(lat, lon) => movePin(lat, lon, 'PIN')} label="Delivery pin. Drag to adjust." />
            {pin && <p className="mt-1 text-xs text-muted">Pin at {v.latitude}, {v.longitude}{v.location_accuracy_m ? ` · device accuracy about ${v.location_accuracy_m} m` : ''}</p>}
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="House / flat / building" required error={err('line1')} hint="e.g. 12B, Rose Villa">{(p) => <Input {...p} value={v.line1} onChange={typed('line1')} autoComplete="address-line1" />}</Field>
            <Field label="Street and locality" error={err('line2')}>{(p) => <Input {...p} value={v.line2} onChange={typed('line2')} autoComplete="address-line2" />}</Field>
            <Field label="Landmark" error={err('landmark')} hint="Helps the rider find you">{(p) => <Input {...p} value={v.landmark} onChange={typed('landmark')} />}</Field>
            <Field label="Town / city" required error={err('city')}>{(p) => <Input {...p} value={v.city} onChange={typed('city')} autoComplete="address-level2" />}</Field>
            <Field label="District" error={err('district')}>{(p) => <Input {...p} value={v.district} onChange={typed('district')} />}</Field>
            <Field label="State" required error={err('state')}>{(p) => <Input {...p} value={v.state} onChange={typed('state')} autoComplete="address-level1" />}</Field>
            <Field label="PIN code" error={err('postal_code')} hint="Optional, 6 digits">{(p) => <Input {...p} inputMode="numeric" maxLength={6} value={v.postal_code} onChange={typed('postal_code')} autoComplete="postal-code" />}</Field>
            <Field label="Save as">{(p) => (
              <div className="flex gap-2">
                <Select {...p} value={v.label} onChange={(e) => set({ label: e.target.value })}><option value="HOME">Home</option><option value="WORK">Work</option><option value="OTHER">Other</option></Select>
                {v.label === 'OTHER' && <Input aria-label="Custom name" placeholder="e.g. Amma's house" maxLength={32} value={v.custom_label ?? ''} onChange={(e) => set({ custom_label: e.target.value })} />}
              </div>)}</Field>
            <Field label="Receiver's name" required error={err('recipient_name')}>{(p) => <Input {...p} value={v.recipient_name} onChange={typed('recipient_name')} autoComplete="name" />}</Field>
            <Field label="Phone" required error={err('phone_number')}>{(p) => <Input {...p} type="tel" value={v.phone_number} onChange={typed('phone_number')} autoComplete="tel" />}</Field>
            <Field label="Delivery instructions" className="sm:col-span-2" error={err('delivery_instructions')} hint="e.g. Ring the bell, second floor, dog at the gate">{(p) => <Textarea {...p} rows={2} maxLength={500} value={v.delivery_instructions} onChange={typed('delivery_instructions')} />}</Field>
          </div>
          {err('latitude') && <Alert tone="error">{err('latitude')}</Alert>}
          <label className="flex min-h-11 items-start gap-2 rounded-control border border-line p-3 text-sm">
            <input type="checkbox" className="mt-0.5 size-4 accent-forest" checked={confirmed} disabled={!pin} onChange={(e) => setConfirmed(e.target.checked)} />
            <span>The pin is at the right place for delivery.</span>
          </label>
          <div className="flex flex-wrap gap-2">
            <Button disabled={!canSave} loading={saving} onClick={() => onSave({ ...v, location_confirmed: true } as AddressInput)}>{submitLabel}</Button>
            {onCancel && <Button variant="ghost" onClick={onCancel}>Cancel</Button>}
          </div>
          {!canSave && <p className="text-xs text-muted">{!pin ? 'Place the pin first.' : !confirmed ? 'Confirm the pin location to continue.' : 'Fill in the required fields.'}</p>}
        </div>
      )}
    </div>
  )
}
