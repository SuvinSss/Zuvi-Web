import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, Crosshair, Loader2, MapPin, Plus } from 'lucide-react'
import { createContext, useContext, useMemo, useState, type ReactNode } from 'react'
import { Modal } from '@/components/kit'
import { MapView } from '@/components/location/MapView'
import { Alert, Button } from '@/components/ui'
import { useAuth } from '@/features/auth/AuthProvider'
import { errorMessage } from '@/lib/api'
import { currentPosition } from '@/lib/geo'
import { AddressDialog } from '@/components/location/AddressDialog'
import { reversePlace } from '@/services/delivery'
import { listAddresses } from '@/services/platform'
import type { Address } from '@/types/platform'

export interface DeliveryPoint { kind: 'saved' | 'point'; addressId?: number; label: string; summary: string; lat: string; lon: string }

interface Ctx {
  selected: DeliveryPoint | null
  selectAddress: (a: Address) => void
  selectPoint: (p: Omit<DeliveryPoint, 'kind'>) => void
  addresses: Address[]
}

const KEY = 'zuuvi.selectedAddressId' // only the id of one of the customer's own saved addresses; never coordinates
const DeliveryLocationContext = createContext<Ctx>({ selected: null, selectAddress: () => {}, selectPoint: () => {}, addresses: [] })

function readId(): number | null {
  try { const v = localStorage.getItem(KEY); return v ? Number(v) : null } catch { return null }
}
function writeId(id: number | null) {
  try { if (id) localStorage.setItem(KEY, String(id)); else localStorage.removeItem(KEY) } catch { /* storage unavailable: selection lasts this visit only */ }
}

export const toPoint = (a: Address): DeliveryPoint => ({
  kind: 'saved', addressId: a.id, label: a.short_label ?? a.label, lat: a.latitude, lon: a.longitude,
  summary: a.summary ?? [a.line2 || a.line1, a.city, a.state].filter(Boolean).join(', '),
})

/** The customer's chosen delivery point, shared by the header, stores list and checkout. */
export function DeliveryLocationProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  const isCustomer = user?.role === 'CUSTOMER'
  const list = useQuery({ queryKey: ['addresses'], queryFn: listAddresses, enabled: isCustomer, staleTime: 60_000 })
  const [chosenId, setChosenId] = useState<number | null>(readId)
  const [point, setPoint] = useState<DeliveryPoint | null>(null)
  const addresses = useMemo(() => list.data ?? [], [list.data])

  const selected = useMemo<DeliveryPoint | null>(() => {
    if (point) return point
    if (!isCustomer || addresses.length === 0) return null
    const usable = addresses.filter((a) => Number(a.latitude) || Number(a.longitude))
    const a = usable.find((x) => x.id === chosenId) ?? usable.find((x) => x.is_default) ?? usable[0]
    return a ? toPoint(a) : null
  }, [point, isCustomer, addresses, chosenId])

  const value = useMemo<Ctx>(() => ({
    selected, addresses,
    selectAddress: (a) => { setPoint(null); setChosenId(a.id); writeId(a.id) },
    selectPoint: (p) => setPoint({ ...p, kind: 'point' }),
  }), [selected, addresses])
  return <DeliveryLocationContext.Provider value={value}>{children}</DeliveryLocationContext.Provider>
}

export const useDeliveryLocation = () => useContext(DeliveryLocationContext)

/** Header control: "Delivering to ▾  Home · Locality, Town". */
export function DeliveryLocationButton({ className = '' }: { className?: string }) {
  const { selected } = useDeliveryLocation()
  const [open, setOpen] = useState(false)
  return (
    <>
      <button type="button" onClick={() => setOpen(true)} aria-haspopup="dialog"
        className={`flex min-h-11 min-w-0 items-center gap-2 rounded-control px-2 text-left hover:bg-pale ${className}`}>
        <MapPin className="size-5 shrink-0 text-emerald" aria-hidden="true" />
        <span className="min-w-0">
          <span className="flex items-center gap-1 text-xs font-semibold text-forest">Delivering to <ChevronDown className="size-3.5" aria-hidden="true" /></span>
          <span className="block truncate text-sm text-ink">{selected ? `${selected.label} · ${selected.summary}` : 'Choose your location'}</span>
        </span>
      </button>
      {open && <LocationDialog onClose={() => setOpen(false)} />}
    </>
  )
}

function LocationDialog({ onClose }: { onClose: () => void }) {
  const { user } = useAuth()
  const isCustomer = user?.role === 'CUSTOMER'
  const { selected, addresses, selectAddress, selectPoint } = useDeliveryLocation()
  const qc = useQueryClient()
  const [adding, setAdding] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [warn, setWarn] = useState('')
  const [pin, setPin] = useState<{ lat: number; lon: number } | null>(selected ? { lat: Number(selected.lat), lon: Number(selected.lon) } : null)

  const choosePoint = async (lat: number, lon: number, label: string) => {
    let summary = `${lat.toFixed(4)}, ${lon.toFixed(4)}`
    try {
      const r = await reversePlace(lat.toFixed(6), lon.toFixed(6))
      if (r.result) summary = [r.result.locality, r.result.city, r.result.state].filter(Boolean).join(', ') || r.result.label
    } catch { /* label falls back to coordinates */ }
    selectPoint({ label, summary, lat: lat.toFixed(6), lon: lon.toFixed(6) })
  }

  const locate = async () => {
    setError(''); setWarn(''); setBusy(true)
    try {
      const fix = await currentPosition()
      setPin({ lat: Number(fix.latitude), lon: Number(fix.longitude) })
      if (fix.accuracy_m !== null && fix.accuracy_m > 100) setWarn(`Accurate to about ${fix.accuracy_m} m. Drag the pin if it is not where you are.`)
      await choosePoint(Number(fix.latitude), Number(fix.longitude), 'Current location')
    } catch (e) { setError(`${e instanceof Error ? e.message : errorMessage(e)} You can tap the map instead.`) } finally { setBusy(false) }
  }

  if (adding) {
    return <AddressDialog address={null} onSaved={() => void qc.invalidateQueries({ queryKey: ['addresses'] })}
      onClose={(saved) => { setAdding(false); if (saved) { selectAddress(saved); onClose() } }} />
  }
  return (
    <Modal open onClose={onClose} title="Choose a delivery location">
      <div className="space-y-4">
        {isCustomer && addresses.length > 0 && (
          <fieldset>
            <legend className="mb-2 text-sm font-semibold text-forest">Saved addresses</legend>
            <div className="space-y-2">{addresses.map((a) => (
              <label key={a.id} className={`flex cursor-pointer gap-3 rounded-control border p-3 text-sm ${selected?.addressId === a.id ? 'border-emerald bg-pale' : 'border-line'}`}>
                <input type="radio" name="deliver-to" className="mt-1" checked={selected?.addressId === a.id} onChange={() => { selectAddress(a); onClose() }} />
                <span><span className="font-semibold">{a.short_label ?? a.label}</span>{a.is_default && <span className="ml-2 text-xs text-emerald">Default</span>}<br />
                  <span className="text-muted">{a.summary ?? [a.line1, a.city].join(', ')}</span>
                  {!a.location_confirmed && <span className="block text-xs text-warn">Pin not confirmed. Open Saved addresses to fix.</span>}</span>
              </label>))}</div>
          </fieldset>
        )}
        {isCustomer && <Button variant="outline" icon={Plus} onClick={() => setAdding(true)}>Add a new address</Button>}
        <div className="space-y-2 border-t border-line pt-4">
          <p className="text-sm font-semibold text-forest">{isCustomer ? 'Or browse for another place' : 'See stores that deliver to you'}</p>
          <p className="text-xs text-muted">We ask for your location only when you tap the button, to show nearby stores. It is not saved or tracked.</p>
          <Button variant="secondary" icon={busy ? Loader2 : Crosshair} loading={busy} onClick={() => void locate()}>Use my current location</Button>
          {error && <Alert tone="error">{error}</Alert>}
          {warn && <Alert tone="warn">{warn}</Alert>}
          <MapView value={pin} height={220} label="Tap or drag the pin to choose a place" onPinChange={(lat, lon) => { setPin({ lat, lon }); void choosePoint(lat, lon, 'Pinned location') }} />
          {pin && <Button onClick={onClose}>Done</Button>}
        </div>
      </div>
    </Modal>
  )
}
