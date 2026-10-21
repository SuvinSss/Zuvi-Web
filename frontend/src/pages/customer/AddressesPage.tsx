import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { MapPin, Plus } from 'lucide-react'
import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { ConfirmDialog, QueryBoundary, useToast } from '@/components/kit'
import { AddressDialog } from '@/components/location/AddressDialog'
import { useDeliveryLocation } from '@/features/location/DeliveryLocation'
import { Button, Card, PageHeader } from '@/components/ui'
import { errorMessage } from '@/lib/api'
import { deleteAddress, listAddresses, setDefaultAddress } from '@/services/platform'
import type { Address } from '@/types/platform'

export default function AddressesPage() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const toast = useToast()
  const location = useDeliveryLocation()
  const list = useQuery({ queryKey: ['addresses'], queryFn: listAddresses })
  const [editing, setEditing] = useState<Address | 'new' | null>(params.get('add') ? 'new' : null)
  const [removing, setRemoving] = useState<Address | null>(null)
  const refresh = () => { void qc.invalidateQueries({ queryKey: ['addresses'] }); void qc.invalidateQueries({ queryKey: ['checkout-preview'] }) }
  const def = useMutation({ mutationFn: (id: number) => setDefaultAddress(id), onSuccess: () => { refresh(); toast('success', 'Default address updated.') }, onError: (e) => toast('error', errorMessage(e)) })
  const del = useMutation({ mutationFn: (id: number) => deleteAddress(id), onSuccess: () => { refresh(); setRemoving(null); toast('success', 'Address removed.') }, onError: (e) => toast('error', errorMessage(e)) })
  const close = (saved?: Address) => {
    setEditing(null)
    if (saved) location.selectAddress(saved)
    if (saved && params.get('next') === 'checkout') navigate('/checkout')
  }
  return (
    <>
      <PageHeader title="Saved addresses" subtitle="Pin each address on the map so riders find you and delivery is priced correctly." actions={<Button icon={Plus} onClick={() => setEditing('new')}>Add address</Button>} />
      <QueryBoundary query={list} isEmpty={list.data?.length === 0} empty={{ icon: MapPin, title: 'No saved addresses', text: 'Add an address to check out for delivery.', action: <Button onClick={() => setEditing('new')}>Add address</Button> }}>
        <ul className="grid gap-3 md:grid-cols-2">
          {list.data?.map((a) => (
            <li key={a.id}><Card className="p-4">
              <p className="flex flex-wrap items-center gap-2 font-semibold">{a.short_label ?? a.label}
                {a.is_default && <span className="rounded-full bg-pale px-2 py-0.5 text-xs text-forest">Default</span>}
                {!a.location_confirmed && <span className="rounded-full bg-warn-bg px-2 py-0.5 text-xs text-warn">Pin not confirmed</span>}
              </p>
              <address className="mt-2 text-sm not-italic">{a.recipient_name} · {a.phone_number}<br />{a.line1}{a.line2 ? `, ${a.line2}` : ''}{a.landmark ? ` (near ${a.landmark})` : ''}<br />{[a.city, a.district, a.state, a.postal_code].filter(Boolean).join(', ')}</address>
              {a.delivery_instructions && <p className="mt-1 text-xs text-muted">Instructions: {a.delivery_instructions}</p>}
              <div className="mt-3 flex flex-wrap gap-2">
                <Button size="sm" variant="outline" onClick={() => setEditing(a)}>{a.location_confirmed ? 'Edit' : 'Confirm pin'}</Button>
                {!a.is_default && <Button size="sm" variant="outline" onClick={() => def.mutate(a.id)} loading={def.isPending && def.variables === a.id}>Make default</Button>}
                <Button size="sm" variant="ghost" onClick={() => setRemoving(a)}>Remove</Button>
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
