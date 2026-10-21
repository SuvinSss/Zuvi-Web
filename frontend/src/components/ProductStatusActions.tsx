import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Modal, useToast } from '@/components/kit'
import { Alert, Button, Textarea } from '@/components/ui'
import { errorMessage } from '@/lib/api'
import { changeProductStatus } from '@/services/management'
import type { ProductDetail } from '@/types/api'

interface ActionDef { status: string; label: string; note?: 'reason' | 'missing'; variant?: 'primary' | 'outline' | 'destructive'; needs: 'approve' | 'change' }

function actionsFor(p: ProductDetail): ActionDef[] {
  const next = new Set(p.next_statuses ?? [])
  const out: ActionDef[] = []
  if (next.has('APPROVED')) out.push({ status: 'APPROVED', label: p.status === 'INACTIVE' ? 'Reactivate' : 'Approve', variant: 'primary', needs: 'approve' })
  if (next.has('PENDING')) out.push({ status: 'PENDING', label: p.status === 'APPROVED' || p.status === 'INACTIVE' ? 'Send back for review' : 'Submit for approval', variant: 'outline', needs: 'change' })
  if (next.has('NEEDS_INFO')) out.push({ status: 'NEEDS_INFO', label: 'Request information', note: 'missing', variant: 'outline', needs: 'approve' })
  if (next.has('REJECTED')) out.push({ status: 'REJECTED', label: 'Reject', note: 'reason', variant: 'destructive', needs: 'approve' })
  if (next.has('INACTIVE')) out.push({ status: 'INACTIVE', label: 'Deactivate', variant: 'outline', needs: 'change' })
  return out
}

/** Only the transitions the server allows for this product and this person are offered. */
export function ProductStatusActions({ product, canApprove, canChange }: { product: ProductDetail; canApprove: boolean; canChange: boolean }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [pending, setPending] = useState<ActionDef | null>(null)
  const [note, setNote] = useState('')
  const run = useMutation({
    mutationFn: (a: ActionDef) => changeProductStatus(product.id, a.status, note),
    onSuccess: (data, a) => {
      qc.setQueryData(['product', 'admin', product.id], data)
      void qc.invalidateQueries({ queryKey: ['products'] }); void qc.invalidateQueries({ queryKey: ['admin-counts'] })
      toast('success', `${a.label}: done.`); setPending(null); setNote('')
    },
  })
  const actions = actionsFor(product).filter((a) => (a.needs === 'approve' ? canApprove : canChange))
  if (!actions.length) return null
  const start = (a: ActionDef) => { run.reset(); if (a.note) setPending(a); else run.mutate(a) }
  return (
    <div className="flex flex-wrap gap-2" aria-label="Product status actions">
      {actions.map((a) => <Button key={a.status} size="sm" variant={a.variant} loading={run.isPending && run.variables?.status === a.status} onClick={() => start(a)}>{a.label}</Button>)}
      {run.isError && !pending && <Alert tone="error">{errorMessage(run.error)}</Alert>}
      <Modal open={pending !== null} onClose={() => setPending(null)} title={pending?.label ?? ''}
        footer={<><Button variant="outline" onClick={() => setPending(null)}>Cancel</Button><Button variant={pending?.variant === 'destructive' ? 'destructive' : 'primary'} disabled={!note.trim()} loading={run.isPending} onClick={() => pending && run.mutate(pending)}>{pending?.label}</Button></>}>
        <label className="block text-sm font-medium">{pending?.note === 'missing' ? 'What needs to be added or fixed? The store sees this note.' : 'Reason (the store sees this)'}
          <Textarea rows={3} maxLength={500} className="mt-1" value={note} onChange={(e) => setNote(e.target.value)} />
        </label>
        {run.isError && <Alert tone="error">{errorMessage(run.error)}</Alert>}
      </Modal>
    </div>
  )
}
