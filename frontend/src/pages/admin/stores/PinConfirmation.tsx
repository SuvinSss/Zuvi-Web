import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useToast } from '@/components/kit'
import { Alert, Button } from '@/components/ui'
import { errorMessage } from '@/lib/api'
import { formatDateTime } from '@/lib/format'
import { confirmStorePin } from '@/services/delivery'
import type { StoreDetail } from '@/types/management'

/** Shows whether a manager has checked the store's map pin, and lets one confirm it. */
export function PinConfirmation({ store, canChange }: { store: StoreDetail; canChange: boolean }) {
  const qc = useQueryClient()
  const toast = useToast()
  const hasPin = Boolean(Number(store.address.latitude) || Number(store.address.longitude))
  const confirm = useMutation({
    mutationFn: () => confirmStorePin(store.id),
    onSuccess: () => { toast('success', 'Pin confirmed.'); void qc.invalidateQueries({ queryKey: ['admin-store', store.id] }) },
    onError: (e) => toast('error', errorMessage(e)),
  })
  const loc = store.location
  if (!loc || !hasPin) return null
  if (loc.confirmed) {
    return <p className="text-sm text-muted">Pin confirmed by {loc.confirmed_by ?? 'a manager'} on {formatDateTime(loc.confirmed_at ?? '')}. Moving the pin clears this.</p>
  }
  return (
    <Alert tone="warn" title="Pin not confirmed yet">
      <p>Open the pin in Google Maps and check it sits at the store's pickup door, then confirm it.</p>
      {canChange && <Button className="mt-2" onClick={() => confirm.mutate()} disabled={confirm.isPending}>{confirm.isPending ? 'Confirming…' : 'Confirm this pin'}</Button>}
    </Alert>
  )
}
