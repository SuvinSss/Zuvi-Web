import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { MapPin, Plus } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { ConfirmDialog, Modal, QueryBoundary, useToast } from '@/components/kit'
import { Alert, Button, Card, Field, Input, PageHeader, Select, Textarea } from '@/components/ui'
import { errorMessage, fieldErrors } from '@/lib/api'
import { createAddress, deleteAddress, listAddresses, setDefaultAddress, updateAddress } from '@/services/platform'
import type { Address, AddressInput } from '@/types/platform'

const EMPTY: AddressInput = { label: 'HOME', recipient_name: '', phone_number: '', line1: '', line2: '', landmark: '', city: '', district: '', state: '', postal_code: '', latitude: '', longitude: '', delivery_instructions: '' }

export default function AddressesPage() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const toast = useToast()
  const list = useQuery({ queryKey: ['addresses'], queryFn: listAddresses })
  const [editing, setEditing] = useState<Address | 'new' | null>(params.get('add') ? 'new' : null)
  const [removing, setRemoving] = useState<Address | null>(null)
  const refresh = () => { void qc.invalidateQueries({ queryKey: ['addresses'] }); void qc.invalidateQueries({ queryKey: ['checkout-preview'] }) }
  const def = useMutation({ mutationFn: (id: number) => setDefaultAddress(id), onSuccess: () => { refresh(); toast('success', 'Default address updated.') }, onError: (e) => toast('error', errorMessage(e)) })
  const del = useMutation({ mutationFn: (id: number) => deleteAddress(id), onSuccess: () => { refresh(); setRemoving(null); toast('success', 'Address removed.') }, onError: (e) => toast('error', errorMessage(e)) })
  const close = (saved?: boolean) => {
    setEditing(null)
    if (saved && params.get('next') === 'checkout') navigate('/checkout')
  }
  return (
    <>
      <PageHeader title="Saved addresses" actions={<Button icon={Plus} onClick={() => setEditing('new')}>Add address</Button>} />
      <QueryBoundary query={list} isEmpty={list.data?.length === 0} empty={{ icon: MapPin, title: 'No saved addresses', text: 'Add an address to check out for delivery.', action: <Button onClick={() => setEditing('new')}>Add address</Button> }}>
        <ul className="grid gap-3 md:grid-cols-2">
          {list.data?.map((a) => (
            <li key={a.id}><Card className="p-4">
              <p className="font-semibold">{a.recipient_name} {a.is_default && <span className="ml-2 rounded-full bg-pale px-2 py-0.5 text-xs text-forest">Default</span>}</p>
              <p className="text-xs uppercase tracking-wide text-muted">{a.label}</p>
              <address className="mt-2 text-sm not-italic">{a.line1}{a.line2 ? `, ${a.line2}` : ''}{a.landmark ? ` (${a.landmark})` : ''}<br />{a.city}, {a.state} {a.postal_code}<br />{a.phone_number}</address>
              <div className="mt-3 flex flex-wrap gap-2">
                <Button variant="outline" onClick={() => setEditing(a)}>Edit</Button>
                {!a.is_default && <Button variant="outline" onClick={() => def.mutate(a.id)} loading={def.isPending && def.variables === a.id}>Make default</Button>}
                <Button variant="ghost" onClick={() => setRemoving(a)}>Remove</Button>
              </div>
            </Card></li>
          ))}
        </ul>
      </QueryBoundary>
      {editing && <AddressDialog address={editing === 'new' ? null : editing} onClose={close} onSaved={refresh} />}
      <ConfirmDialog open={!!removing} onClose={() => setRemoving(null)} onConfirm={() => removing && del.mutate(removing.id)} busy={del.isPending} danger confirmLabel="Remove" title="Remove this address?" message="Past orders keep their own copy of the address." />
    </>
  )
}

function AddressDialog({ address, onClose, onSaved }: { address: Address | null; onClose: (saved?: boolean) => void; onSaved: () => void }) {
  const toast = useToast()
  const [v, setV] = useState<AddressInput>(address ? { ...EMPTY, ...address } : EMPTY)
  const save = useMutation({
    mutationFn: () => {
      const body = { ...v, latitude: v.latitude || '', longitude: v.longitude || '' } as AddressInput
      return address ? updateAddress(address.id, body) : createAddress(body)
    },
    onSuccess: () => { onSaved(); toast('success', 'Address saved.'); onClose(true) },
  })
  const fe = fieldErrors(save.error)
  const bind = (k: keyof AddressInput) => ({ value: String(v[k] ?? ''), onChange: (e: { target: { value: string } }) => setV({ ...v, [k]: e.target.value }) })
  const [geoMessage, setGeoMessage] = useState('')
  const locate = () => {
    if (!navigator.geolocation) { setGeoMessage('This device cannot share its location. Enter the coordinates by hand.'); return }
    setGeoMessage('Finding your location…')
    navigator.geolocation.getCurrentPosition(
      (pos) => { setV((cur) => ({ ...cur, latitude: pos.coords.latitude.toFixed(6), longitude: pos.coords.longitude.toFixed(6) })); setGeoMessage('Location filled in.') },
      () => setGeoMessage('We could not get your location. Allow location access or enter the coordinates by hand.'),
      { enableHighAccuracy: true, timeout: 10000 },
    )
  }
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate() }
  return (
    <Modal open onClose={() => onClose()} title={address ? 'Edit address' : 'New address'}>
      <form onSubmit={submit} className="space-y-3" noValidate>
        {save.isError && !Object.keys(fe).length && <Alert>{errorMessage(save.error)}</Alert>}
        <Field label="Label" error={fe.label}>{(p) => <Select {...p} {...bind('label')}><option value="HOME">Home</option><option value="WORK">Work</option><option value="OTHER">Other</option></Select>}</Field>
        <Field label="Recipient name" required error={fe.recipient_name}>{(p) => <Input {...p} autoComplete="name" {...bind('recipient_name')} />}</Field>
        <Field label="Phone number" required error={fe.phone_number}>{(p) => <Input {...p} type="tel" autoComplete="tel" {...bind('phone_number')} />}</Field>
        <Field label="Address line 1" required error={fe.line1}>{(p) => <Input {...p} autoComplete="address-line1" {...bind('line1')} />}</Field>
        <Field label="Address line 2" error={fe.line2}>{(p) => <Input {...p} autoComplete="address-line2" {...bind('line2')} />}</Field>
        <Field label="Landmark" error={fe.landmark}>{(p) => <Input {...p} {...bind('landmark')} />}</Field>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="City" required error={fe.city}>{(p) => <Input {...p} autoComplete="address-level2" {...bind('city')} />}</Field>
          <Field label="District" error={fe.district}>{(p) => <Input {...p} {...bind('district')} />}</Field>
          <Field label="State" required error={fe.state}>{(p) => <Input {...p} autoComplete="address-level1" {...bind('state')} />}</Field>
          <Field label="PIN code" required error={fe.postal_code}>{(p) => <Input {...p} inputMode="numeric" autoComplete="postal-code" {...bind('postal_code')} />}</Field>
        </div>
        <fieldset className="rounded-control border border-line p-3">
          <legend className="px-1 text-sm font-medium">Map location <span className="text-danger" aria-hidden="true">*</span></legend>
          <p className="mb-2 text-xs text-muted">Delivery partners navigate to these coordinates. There is no address search yet, so use your current location or enter them by hand.</p>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Latitude" required error={fe.latitude}>{(p) => <Input {...p} inputMode="decimal" {...bind('latitude')} />}</Field>
            <Field label="Longitude" required error={fe.longitude}>{(p) => <Input {...p} inputMode="decimal" {...bind('longitude')} />}</Field>
          </div>
          <Button variant="outline" className="mt-2" onClick={locate}>Use my current location</Button>
          {geoMessage && <p role="status" className="mt-2 text-sm text-muted">{geoMessage}</p>}
        </fieldset>
        <Field label="Delivery instructions" error={fe.delivery_instructions}>{(p) => <Textarea {...p} rows={2} maxLength={500} {...bind('delivery_instructions')} />}</Field>
        <div className="flex justify-end gap-2 pt-2"><Button variant="outline" onClick={() => onClose()}>Cancel</Button><Button type="submit" loading={save.isPending}>Save address</Button></div>
      </form>
    </Modal>
  )
}
