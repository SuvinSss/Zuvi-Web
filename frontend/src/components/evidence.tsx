import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { Card } from '@/components/ui'
import { formatBytes } from '@/lib/format'

export interface EvidenceRecord {
  id: number; kind: string; attempt_number: number; latitude: string | null; longitude: string | null; accuracy_m: number | null
  distance_from_target_m: number | null; within_tolerance: boolean | null; notes: string; recipient_name: string; captured_by_name: string
  store_confirmed_at: string | null; created_at: string; photos: { id: number; url: string; content_type: string; size: number; width: number; height: number }[]
}
const KIND: Record<string, string> = { PICKUP: 'Pickup proof', DELIVERY: 'Delivery proof', FAILED: 'Failed attempt' }

/** Photos are private: the browser fetches them with the session cookie, and the API refuses anyone who may not see them. */
export function EvidencePanel({ deliveryId, emptyText = 'No proof has been recorded yet.' }: { deliveryId: number; emptyText?: string }) {
  const q = useQuery({ queryKey: ['evidence', deliveryId], queryFn: async () => (await api.get<EvidenceRecord[]>(`/deliveries/${deliveryId}/evidence/`)).data })
  if (q.isPending) return <p className="text-sm text-muted" aria-busy="true">Loading proof…</p>
  if (q.isError) return <p className="text-sm text-muted">Proof is not available to you for this delivery.</p>
  if (!q.data.length) return <p className="text-sm text-muted">{emptyText}</p>
  return (
    <div className="space-y-3">
      {q.data.map((e) => (
        <Card key={e.id} className="p-3">
          <p className="text-sm font-semibold">{KIND[e.kind] ?? e.kind}{e.attempt_number > 1 ? ` · attempt ${e.attempt_number}` : ''}</p>
          <p className="text-xs text-muted">{new Date(e.created_at).toLocaleString('en-IN')}{e.captured_by_name ? ` · ${e.captured_by_name}` : ''}</p>
          {e.recipient_name && <p className="mt-1 text-sm">Received by {e.recipient_name}</p>}
          {e.notes && <p className="mt-1 whitespace-pre-line text-sm">{e.notes}</p>}
          {e.within_tolerance === false && <p className="mt-1 text-sm text-warn">Captured about {Math.round(e.distance_from_target_m ?? 0)} m from the delivery address.</p>}
          {e.store_confirmed_at && <p className="mt-1 text-sm">Store confirmed handover.</p>}
          {e.photos.length > 0 && (
            <ul className="mt-2 flex flex-wrap gap-2">
              {e.photos.map((p, i) => (
                <li key={p.id}><a href={p.url} target="_blank" rel="noreferrer" aria-label={`Open photo ${i + 1} (${formatBytes(p.size)})`}>
                  <img src={p.url} alt={`${KIND[e.kind] ?? 'Proof'} photo ${i + 1}`} loading="lazy" width={96} height={96} className="size-24 rounded-md border border-line object-cover" />
                </a></li>
              ))}
            </ul>
          )}
        </Card>
      ))}
    </div>
  )
}
