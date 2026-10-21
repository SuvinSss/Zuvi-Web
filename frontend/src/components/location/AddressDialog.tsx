import { useMutation } from '@tanstack/react-query'
import { Modal, useToast } from '@/components/kit'
import { errorMessage, fieldErrors } from '@/lib/api'
import { createAddress, updateAddress } from '@/services/platform'
import type { Address, AddressInput } from '@/types/platform'
import { AddressPicker, fromAddress } from './AddressPicker'

export function AddressDialog({ address, onClose, onSaved, seed }: { address: Address | null; onClose: (saved?: Address) => void; onSaved: () => void; seed?: AddressInput | null }) {
  const toast = useToast()
  const save = useMutation({
    mutationFn: (body: AddressInput) => (address ? updateAddress(address.id, body) : createAddress(body)),
    onSuccess: (saved) => { onSaved(); toast('success', address ? 'Address updated.' : 'Address saved.'); onClose(saved) },
  })
  const errors = fieldErrors(save.error)
  return (
    <Modal open onClose={() => onClose()} title={address ? 'Edit address' : 'Add a delivery address'}>
      {save.isError && Object.keys(errors).length === 0 && <p role="alert" className="mb-2 text-sm text-danger">{errorMessage(save.error)}</p>}
      <AddressPicker initial={address ? fromAddress(address) : seed ?? null} saving={save.isPending} errors={errors} onSave={(v) => save.mutate(v)} onCancel={() => onClose()} />
    </Modal>
  )
}
