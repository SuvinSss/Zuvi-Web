import { AlertCircle, Check, ChevronLeft, ChevronRight, ImagePlus, Star, X } from 'lucide-react'
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type ReactNode,
} from 'react'
import { Button, Card, EmptyState, ErrorState, Skeleton } from '@/components/ui'
import { errorMessage } from '@/lib/api'
import { formatBytes } from '@/lib/format'
import type { LucideIcon } from 'lucide-react'

const cx = (...parts: (string | false | null | undefined)[]) => parts.filter(Boolean).join(' ')

/* ------------------------------------------------------------------ status badge */

type Tone = 'good' | 'warn' | 'bad' | 'info' | 'neutral'
const TONES: Record<Tone, string> = {
  good: 'bg-mint text-deep',
  warn: 'bg-warn-bg text-warn',
  bad: 'bg-danger-bg text-danger',
  info: 'bg-sky-50 text-sky-800',
  neutral: 'bg-canvas text-muted ring-1 ring-line',
}
const TONE_OF: Record<string, Tone> = {
  COMPLETED: 'good', DELIVERED: 'good', APPROVED: 'good', ACTIVE: 'good', RESOLVED: 'good', PUBLISHED: 'good', REPLIED: 'good', SENT: 'good', PAID: 'good', COLLECTED: 'good', READY: 'good',
  PENDING: 'warn', PENDING_ASSIGNMENT: 'warn', OFFERED: 'warn', INFO_REQUESTED: 'warn', WAITING_CUSTOMER: 'warn', ESCALATED: 'warn', PLACED: 'warn', UNPAID: 'warn', SUBMITTED: 'warn', NEW: 'warn', OPEN: 'warn',
  CANCELLED: 'bad', REJECTED: 'bad', FAILED: 'bad', SUSPENDED: 'bad', HIDDEN: 'bad', EXPIRED: 'bad', REVOKED: 'bad', INACTIVE: 'neutral', DRAFT: 'neutral', CLOSED: 'neutral',
  ACCEPTED: 'info', PROCESSING: 'info', AT_STORE: 'info', IN_TRANSIT: 'info', ARRIVED: 'info', IN_PROGRESS: 'info', IN_REVIEW: 'info', UNDER_REVIEW: 'info',
}
export function humanize(value: string): string {
  const text = value.replace(/_/g, ' ').toLowerCase()
  return text.charAt(0).toUpperCase() + text.slice(1)
}
/** Status shown as text (never colour alone) with a small shape marker. */
export function Status({ value, label }: { value: string; label?: string }) {
  const tone = TONE_OF[value] ?? 'neutral'
  const Marker = tone === 'good' ? Check : tone === 'bad' ? X : tone === 'warn' ? AlertCircle : null
  return (
    <span className={cx('inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold', TONES[tone])}>
      {Marker ? <Marker className="size-3" aria-hidden="true" /> : <span aria-hidden="true" className="size-1.5 rounded-full bg-current" />}
      {label ?? humanize(value)}
    </span>
  )
}

/* ------------------------------------------------------------------ toasts */

interface Toast { id: number; tone: 'success' | 'error' | 'info'; text: string }
const ToastContext = createContext<(tone: Toast['tone'], text: string) => void>(() => undefined)
export const useToast = () => useContext(ToastContext)

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const nextId = useRef(1)
  const push = useCallback((tone: Toast['tone'], text: string) => {
    const id = nextId.current++
    setToasts((all) => [...all.slice(-3), { id, tone, text }])
    window.setTimeout(() => setToasts((all) => all.filter((t) => t.id !== id)), tone === 'error' ? 8000 : 4500)
  }, [])
  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed inset-x-0 bottom-20 z-[60] flex flex-col items-center gap-2 px-4 lg:bottom-6" aria-live="polite">
        {toasts.map((t) => (
          <div
            key={t.id}
            role={t.tone === 'error' ? 'alert' : 'status'}
            className={cx(
              'rise pointer-events-auto flex max-w-md items-start gap-2 rounded-control px-4 py-3 text-sm shadow-pop',
              t.tone === 'error' ? 'bg-danger text-white' : t.tone === 'success' ? 'bg-forest text-white' : 'bg-ink text-white',
            )}
          >
            <span className="min-w-0 break-words">{t.text}</span>
            <button type="button" aria-label="Dismiss" className="-mr-1 grid size-6 shrink-0 place-items-center rounded hover:bg-white/15" onClick={() => setToasts((all) => all.filter((x) => x.id !== t.id))}>
              <X className="size-4" aria-hidden="true" />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

/* ------------------------------------------------------------------ dialogs (native <dialog>: focus trap + Esc for free) */

export function Modal({ open, onClose, title, children, footer }: { open: boolean; onClose: () => void; title: string; children: ReactNode; footer?: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null)
  const titleId = useId()
  useEffect(() => {
    const dialog = ref.current
    if (!dialog) return
    if (open && !dialog.open) dialog.showModal()
    if (!open && dialog.open) dialog.close()
  }, [open])
  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onClose={onClose}
      onClick={(event) => event.target === ref.current && onClose()}
      className="m-auto w-[min(32rem,calc(100vw-1.5rem))] max-h-[calc(100dvh-1.5rem)] overflow-y-auto rounded-card p-0 shadow-pop backdrop:bg-black/45"
    >
      {open && (
        <div className="flex flex-col">
          <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-4">
            <h2 id={titleId} className="text-lg font-semibold text-forest">{title}</h2>
            <button type="button" aria-label="Close" onClick={onClose} className="-mr-2 grid size-10 place-items-center rounded-control hover:bg-canvas">
              <X className="size-5" aria-hidden="true" />
            </button>
          </div>
          <div className="px-5 py-4">{children}</div>
          {footer && <div className="flex flex-wrap justify-end gap-2 border-t border-line px-5 py-3">{footer}</div>}
        </div>
      )}
    </dialog>
  )
}

export function ConfirmDialog({
  open, onClose, onConfirm, title, message, confirmLabel = 'Confirm', danger = false, busy = false, children,
}: {
  open: boolean; onClose: () => void; onConfirm: () => void; title: string; message?: string; confirmLabel?: string; danger?: boolean; busy?: boolean; children?: ReactNode
}) {
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button variant={danger ? 'danger' : 'primary'} onClick={onConfirm} loading={busy}>{confirmLabel}</Button>
        </>
      }
    >
      {message && <p className="text-sm text-ink">{message}</p>}
      {children}
    </Modal>
  )
}

/* ------------------------------------------------------------------ pagination */

export function Pagination({ page, count, pageSize = 20, onPage }: { page: number; count: number; pageSize?: number; onPage: (page: number) => void }) {
  const pages = Math.max(1, Math.ceil(count / pageSize))
  if (pages <= 1) return null
  return (
    <nav aria-label="Pagination" className="mt-4 flex items-center justify-between gap-3">
      <p className="text-sm text-muted" aria-live="polite">Page {page} of {pages} · {count} total</p>
      <div className="flex gap-2">
        <Button variant="secondary" icon={ChevronLeft} disabled={page <= 1} onClick={() => onPage(page - 1)} aria-label="Previous page">Prev</Button>
        <Button variant="secondary" disabled={page >= pages} onClick={() => onPage(page + 1)} aria-label="Next page">
          Next<ChevronRight className="size-4" aria-hidden="true" />
        </Button>
      </div>
    </nav>
  )
}

/* ------------------------------------------------------------------ ratings */

export function Stars({ value, count, size = 'size-4' }: { value: number; count?: number; size?: string }) {
  const rounded = Math.round(value * 2) / 2
  return (
    <span className="inline-flex items-center gap-1" role="img" aria-label={count === 0 ? 'No ratings yet' : `Rated ${value.toFixed(1)} out of 5${count !== undefined ? ` from ${count} reviews` : ''}`}>
      <span className="inline-flex" aria-hidden="true">
        {[1, 2, 3, 4, 5].map((n) => (
          <Star key={n} className={cx(size, n <= rounded ? 'fill-amber-400 text-amber-400' : 'text-line')} />
        ))}
      </span>
      {count !== undefined && <span className="text-xs text-muted">{count === 0 ? 'No ratings' : `${value.toFixed(1)} (${count})`}</span>}
    </span>
  )
}

export function RatingInput({ value, onChange, label = 'Rating' }: { value: number; onChange: (n: number) => void; label?: string }) {
  return (
    <fieldset>
      <legend className="mb-1 text-sm font-medium text-ink">{label}</legend>
      <div className="flex gap-1">
        {[1, 2, 3, 4, 5].map((n) => (
          <label key={n} className="grid size-11 cursor-pointer place-items-center rounded-control has-[:focus-visible]:outline has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-emerald">
            <input type="radio" name={`rating-${label}`} className="sr-only" checked={value === n} onChange={() => onChange(n)} />
            <Star className={cx('size-7', n <= value ? 'fill-amber-400 text-amber-400' : 'text-line')} aria-hidden="true" />
            <span className="sr-only">{n} out of 5</span>
          </label>
        ))}
      </div>
    </fieldset>
  )
}

/* ------------------------------------------------------------------ timeline */

export interface TimelineItem { key: string; title: string; at?: string | null; note?: string; tone?: 'done' | 'current' | 'bad' | 'todo' }
export function Timeline({ items }: { items: TimelineItem[] }) {
  return (
    <ol className="relative space-y-4 border-l-2 border-line pl-5">
      {items.map((item, index) => {
        const tone = item.tone ?? (index === items.length - 1 ? 'current' : 'done')
        return (
          <li key={item.key} className="relative">
            <span
              aria-hidden="true"
              className={cx('absolute -left-[1.72rem] top-0.5 grid size-4 place-items-center rounded-full ring-4 ring-white',
                tone === 'done' && 'bg-emerald', tone === 'current' && 'bg-forest', tone === 'bad' && 'bg-danger', tone === 'todo' && 'bg-line')}
            >
              {tone === 'done' && <Check className="size-3 text-white" />}
            </span>
            <p className={cx('text-sm font-semibold', tone === 'todo' ? 'text-muted' : 'text-ink')}>
              {item.title}
              {tone === 'current' && <span className="ml-2 text-xs font-medium text-emerald">Current</span>}
              {tone === 'bad' && <span className="ml-2 text-xs font-medium text-danger">Problem</span>}
            </p>
            {item.at && <p className="text-xs text-muted"><time dateTime={item.at}>{new Date(item.at).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' })}</time></p>}
            {item.note && <p className="mt-0.5 text-sm text-muted">{item.note}</p>}
          </li>
        )
      })}
    </ol>
  )
}

/* ------------------------------------------------------------------ data table: table on md+, stacked cards on phones */

export interface Column<T> { key: string; header: string; cell: (row: T) => ReactNode; primary?: boolean; className?: string }
export function DataTable<T>({ rows, columns, rowKey, onRowClick, caption }: { rows: T[]; columns: Column<T>[]; rowKey: (row: T) => string | number; onRowClick?: (row: T) => void; caption: string }) {
  return (
    <>
      <div className="hidden overflow-x-auto rounded-card border border-line bg-white shadow-card md:block">
        <table className="w-full min-w-full text-left text-sm">
          <caption className="sr-only">{caption}</caption>
          <thead className="border-b border-line bg-canvas text-xs uppercase tracking-wide text-muted">
            <tr>{columns.map((c) => <th key={c.key} scope="col" className={cx('px-4 py-3 font-semibold', c.className)}>{c.header}</th>)}</tr>
          </thead>
          <tbody className="divide-y divide-line">
            {rows.map((row) => (
              <tr key={rowKey(row)} className={cx(onRowClick && 'cursor-pointer hover:bg-pale/60')} onClick={onRowClick ? () => onRowClick(row) : undefined}>
                {columns.map((c) => <td key={c.key} className={cx('px-4 py-3 align-middle', c.className)}>{c.cell(row)}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul className="space-y-3 md:hidden" aria-label={caption}>
        {rows.map((row) => (
          <li key={rowKey(row)}>
            <Card className={cx('p-4', onRowClick && 'active:bg-pale/60')}>
              <div onClick={onRowClick ? () => onRowClick(row) : undefined} className="space-y-1.5">
                {columns.map((c) => (
                  <div key={c.key} className={cx('flex items-start justify-between gap-3 text-sm', c.primary && 'text-base font-semibold')}>
                    {!c.primary && <span className="shrink-0 text-muted">{c.header}</span>}
                    <span className={cx('min-w-0 break-words', !c.primary && 'text-right')}>{c.cell(row)}</span>
                  </div>
                ))}
              </div>
            </Card>
          </li>
        ))}
      </ul>
    </>
  )
}

/* ------------------------------------------------------------------ query state wrapper */

interface QueryLike { isPending: boolean; isError: boolean; refetch: () => unknown; error: unknown }
export function QueryBoundary({
  query, children, skeleton = 'list', empty, isEmpty,
}: { query: QueryLike; children: ReactNode; skeleton?: 'list' | 'cards' | 'detail'; empty?: { icon: LucideIcon; title: string; text?: string; action?: ReactNode }; isEmpty?: boolean }) {
  if (query.isPending) {
    return (
      <div aria-busy="true" aria-label="Loading" className={skeleton === 'cards' ? 'grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4' : 'space-y-3'}>
        {Array.from({ length: skeleton === 'cards' ? 8 : skeleton === 'detail' ? 3 : 5 }, (_, i) => (
          <Skeleton key={i} className={skeleton === 'cards' ? 'h-56' : skeleton === 'detail' ? 'h-32' : 'h-16'} />
        ))}
      </div>
    )
  }
  if (query.isError) return <ErrorState message={friendlyError(query.error)} onRetry={() => void query.refetch()} />
  if (isEmpty && empty) return <Card><EmptyState icon={empty.icon} title={empty.title} action={empty.action}>{empty.text}</EmptyState></Card>
  return <>{children}</>
}

export const friendlyError = (error: unknown) => errorMessage(error, 'We could not load this. Please try again.')

/* ------------------------------------------------------------------ file upload with preview */

export function FilePicker({
  label, accept = 'image/jpeg,image/png,image/webp', maxBytes = 5 * 1024 * 1024, onFile, file, capture, hint, error,
}: { label: string; accept?: string; maxBytes?: number; onFile: (file: File | null) => void; file: File | null; capture?: 'environment' | 'user'; hint?: string; error?: string }) {
  const id = useId()
  const [problem, setProblem] = useState('')
  const preview = useMemo(() => (file && file.type.startsWith('image/') ? URL.createObjectURL(file) : null), [file])
  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview) }, [preview])
  const choose = (event: ChangeEvent<HTMLInputElement>) => {
    const picked = event.target.files?.[0] ?? null
    event.target.value = ''
    if (picked && picked.size > maxBytes) { setProblem(`That file is ${formatBytes(picked.size)}. The limit is ${formatBytes(maxBytes)}.`); return }
    setProblem('')
    onFile(picked)
  }
  const shown = problem || error
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-sm font-medium text-ink">{label}</label>
      <div className="flex items-center gap-3 rounded-control border border-dashed border-line bg-white p-3">
        {preview ? <img src={preview} alt="Selected file preview" className="size-16 rounded-md object-cover" /> : <div className="grid size-16 place-items-center rounded-md bg-canvas text-muted"><ImagePlus className="size-6" aria-hidden="true" /></div>}
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm">{file ? file.name : 'No file chosen'}</p>
          <p className="text-xs text-muted">{hint ?? `JPEG, PNG or WebP, up to ${formatBytes(maxBytes)}`}</p>
        </div>
        <input id={id} type="file" accept={accept} capture={capture} onChange={choose} className="sr-only" aria-describedby={shown ? `${id}-err` : undefined} />
        <label htmlFor={id} className="inline-flex min-h-11 cursor-pointer items-center rounded-control px-4 text-sm font-semibold text-forest ring-1 ring-inset ring-line hover:bg-pale has-[:focus-visible]:outline">{file ? 'Change' : 'Choose'}</label>
        {file && <Button variant="ghost" onClick={() => { setProblem(''); onFile(null) }} aria-label="Remove file"><X className="size-4" aria-hidden="true" /></Button>}
      </div>
      {shown && <p id={`${id}-err`} role="alert" className="mt-1 text-sm text-danger">{shown}</p>}
    </div>
  )
}

/* ------------------------------------------------------------------ small layout helpers */

export function Section({ title, actions, children, className }: { title: string; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={className}>
      <div className="mb-3 flex min-h-11 items-center justify-between gap-3">
        <h2 className="text-lg font-semibold text-forest">{title}</h2>
        {actions}
      </div>
      {children}
    </section>
  )
}

export function Stat({ label, value, hint, to }: { label: string; value: ReactNode; hint?: string; to?: ReactNode }) {
  return (
    <Card className="p-4">
      <p className="text-sm text-muted">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums text-forest">{value}</p>
      {hint && <p className="mt-0.5 text-xs text-muted">{hint}</p>}
      {to}
    </Card>
  )
}

export function KeyValue({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-[auto_1fr]">
      {rows.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-muted">{k}</dt>
          <dd className="min-w-0 break-words font-medium text-ink">{v ?? '—'}</dd>
        </div>
      ))}
    </dl>
  )
}

/** Tab-like segmented filter that is a real set of buttons (keyboard + screen reader friendly). */
export function Segmented<T extends string>({ value, onChange, options, label }: { value: T; onChange: (v: T) => void; options: { value: T; label: string }[]; label: string }) {
  return (
    <div role="group" aria-label={label} className="flex gap-1 overflow-x-auto rounded-control bg-canvas p-1 ring-1 ring-line">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={value === o.value}
          onClick={() => onChange(o.value)}
          className={cx('min-h-9 shrink-0 rounded-md px-3 text-sm font-medium', value === o.value ? 'bg-white text-forest shadow-sm' : 'text-muted hover:text-ink')}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

/** Confirm dialog that collects a mandatory reason (used for rejections, suspensions, escalations). */
export function ReasonDialog({ open, title, field, onClose, onSubmit, busy, danger, confirm, optional, maxLength = 255 }: {
  open: boolean; title: string; field: string; onClose: () => void; onSubmit: (text: string) => void; busy: boolean; danger?: boolean; confirm: string; optional?: boolean; maxLength?: number
}) {
  const [text, setText] = useState('')
  return (
    <ConfirmDialog open={open} onClose={onClose} title={title} confirmLabel={confirm} danger={danger} busy={busy} onConfirm={() => (optional || text.trim()) && onSubmit(text.trim())}>
      <label className="block text-sm font-medium">{field}{!optional && <span className="text-danger" aria-hidden="true"> *</span>}
        <textarea rows={4} maxLength={maxLength} value={text} onChange={(e) => setText(e.target.value)} className="mt-1 block w-full rounded-control border border-line px-3 py-2 text-base" />
      </label>
    </ConfirmDialog>
  )
}
