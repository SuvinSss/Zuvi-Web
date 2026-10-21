import { Paperclip } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { FilePicker, Status } from '@/components/kit'
import { formatBytes } from '@/lib/format'
import type { Attachment, Sla } from '@/types/platform'

export const PRIORITIES = ['LOW', 'NORMAL', 'HIGH', 'URGENT'] as const
export const TICKET_STATUSES = ['OPEN', 'IN_PROGRESS', 'WAITING_CUSTOMER', 'RESOLVED', 'CLOSED'] as const
export const COMPLAINT_STATUSES = ['SUBMITTED', 'UNDER_REVIEW', 'INFO_REQUESTED', 'ESCALATED', 'RESOLVED', 'REJECTED', 'CLOSED'] as const

const SLA_TEXT: Record<string, string> = { ok: 'On track', due_soon: 'Due soon', breached: 'Overdue', met: 'Met', missed: 'Missed', none: '' }
export function SlaBadges({ sla }: { sla: Sla | null }) {
  if (!sla) return null
  const entries = Object.entries(sla).filter(([, v]) => SLA_TEXT[v])
  if (!entries.length) return null
  return (
    <span className="flex flex-wrap gap-1">
      {entries.map(([k, v]) => (
        <span key={k} className={`rounded-full px-2 py-0.5 text-xs ${v === 'breached' || v === 'missed' ? 'bg-danger/10 text-danger' : v === 'due_soon' ? 'bg-warn/15 text-warn' : 'bg-pale text-forest'}`}>
          {k.replace(/_/g, ' ')}: {SLA_TEXT[v]}
        </span>
      ))}
    </span>
  )
}

export function Attachments({ items }: { items: Attachment[] }) {
  if (!items.length) return null
  return (
    <ul className="mt-2 space-y-1">
      {items.map((a) => (
        <li key={a.id}>
          <a className="inline-flex min-h-9 items-center gap-2 text-sm font-medium text-forest underline" href={a.url} target="_blank" rel="noreferrer">
            <Paperclip className="size-4" aria-hidden="true" />{a.original_name} <span className="font-normal text-muted">({formatBytes(a.size)})</span>
            {a.is_internal && <span className="text-xs text-muted">internal</span>}
          </a>
        </li>
      ))}
    </ul>
  )
}

/** Up to three attachments (images or PDF). The backend re-validates by content. */
export function MultiFilePicker({ files, onChange }: { files: File[]; onChange: (f: File[]) => void }) {
  const [slot, setSlot] = useState<File | null>(null)
  return (
    <div className="space-y-2">
      <FilePicker label="Attach a file (optional)" accept="image/jpeg,image/png,image/webp,application/pdf" file={slot} hint="JPEG, PNG, WebP or PDF, up to 5 MB each, max 3 files"
        onFile={(f) => { if (f && files.length < 3) { onChange([...files, f]) } setSlot(null) }} />
      {files.length > 0 && (
        <ul className="space-y-1 text-sm">
          {files.map((f, i) => (
            <li key={i} className="flex items-center justify-between gap-2 rounded-control bg-canvas px-3 py-1.5">
              <span className="truncate">{f.name} ({formatBytes(f.size)})</span>
              <button type="button" className="min-h-9 px-2 text-danger underline" onClick={() => onChange(files.filter((_, j) => j !== i))}>Remove</button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export function StatusLine({ status, children }: { status: string; children?: ReactNode }) {
  return <div className="flex flex-wrap items-center gap-2"><Status value={status} />{children}</div>
}
