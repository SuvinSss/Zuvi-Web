import { useMutation } from '@tanstack/react-query'
import { MoreHorizontal } from 'lucide-react'
import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'
import { Alert, Button, Textarea } from '@/components/ui'
import { Modal } from '@/components/kit'
import { errorMessage } from '@/lib/api'
import { bulkApply, bulkPreview } from '@/services/management'
import type { BulkEntry, BulkModule, BulkPreview, BulkRequest, BulkResult } from '@/types/management'

/* ------------------------------------------------------------------ tabs (sections of one record) */

export interface TabDef { id: string; label: string; badge?: number | string }
export function Tabs({ tabs, active, onChange, label }: { tabs: TabDef[]; active: string; onChange: (id: string) => void; label: string }) {
  const base = useId()
  const move = (event: KeyboardEvent, index: number) => {
    const next = event.key === 'ArrowRight' ? index + 1 : event.key === 'ArrowLeft' ? index - 1 : event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : null
    if (next === null) return
    event.preventDefault()
    const target = tabs[(next + tabs.length) % tabs.length]
    if (target) { onChange(target.id); document.getElementById(`${base}-${target.id}`)?.focus() }
  }
  return (
    <div role="tablist" aria-label={label} className="-mx-1 mb-5 flex gap-1 overflow-x-auto border-b border-line px-1">
      {tabs.map((tab, index) => (
        <button key={tab.id} id={`${base}-${tab.id}`} type="button" role="tab" aria-selected={active === tab.id} aria-controls={`${base}-panel`}
          tabIndex={active === tab.id ? 0 : -1} onKeyDown={(e) => move(e, index)} onClick={() => onChange(tab.id)}
          className={`-mb-px inline-flex min-h-11 shrink-0 items-center gap-2 border-b-2 px-3 text-sm font-medium focus-visible:outline-2 focus-visible:outline-emerald ${active === tab.id ? 'border-forest text-forest' : 'border-transparent text-muted hover:text-forest'}`}>
          {tab.label}
          {tab.badge !== undefined && tab.badge !== 0 && <span className="rounded-full bg-canvas px-2 text-xs tabular-nums ring-1 ring-line">{tab.badge}</span>}
        </button>
      ))}
    </div>
  )
}
export const TabPanel = ({ children, id }: { children: ReactNode; id: string }) => <div role="tabpanel" id={`${id}-panel`} tabIndex={0}>{children}</div>

/* ------------------------------------------------------------------ row-action menu */

export interface MenuItem { label: string; onSelect: () => void; danger?: boolean; disabled?: boolean }
export function ActionMenu({ label, items }: { label: string; items: MenuItem[] }) {
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLSpanElement>(null)
  const id = useId()
  useEffect(() => {
    if (!open) return
    const close = (event: Event) => { if (!root.current?.contains(event.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', close)
    root.current?.querySelector<HTMLElement>('[role="menuitem"]:not([disabled])')?.focus()
    return () => document.removeEventListener('mousedown', close)
  }, [open])
  const onKey = (event: KeyboardEvent) => {
    if (event.key === 'Escape') { setOpen(false); root.current?.querySelector<HTMLElement>('button')?.focus(); return }
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return
    event.preventDefault()
    const entries = [...(root.current?.querySelectorAll<HTMLElement>('[role="menuitem"]:not([disabled])') ?? [])]
    const at = entries.indexOf(document.activeElement as HTMLElement)
    entries[(at + (event.key === 'ArrowDown' ? 1 : -1) + entries.length) % entries.length]?.focus()
  }
  return (
    <span ref={root} className="relative inline-block" onKeyDown={onKey}>
      <Button variant="ghost" size="sm" iconOnly icon={MoreHorizontal} aria-label={label} aria-haspopup="menu" aria-expanded={open} aria-controls={id} onClick={() => setOpen(!open)} />
      {open && (
        <div id={id} role="menu" aria-label={label} className="absolute right-0 z-20 mt-1 min-w-44 rounded-control bg-white p-1 shadow-pop ring-1 ring-line">
          {items.map((item) => (
            <button key={item.label} type="button" role="menuitem" disabled={item.disabled}
              onClick={() => { setOpen(false); item.onSelect() }}
              className={`flex min-h-10 w-full items-center rounded-control px-3 text-left text-sm hover:bg-pale focus-visible:bg-pale focus-visible:outline-none disabled:opacity-50 ${item.danger ? 'text-danger' : 'text-ink'}`}>
              {item.label}
            </button>
          ))}
        </div>
      )}
    </span>
  )
}

/* ------------------------------------------------------------------ bulk selection */

export interface Selection { ids: Set<number>; selectAll: boolean }
export const emptySelection = (): Selection => ({ ids: new Set(), selectAll: false })

export function SelectCheckbox({ checked, indeterminate, onChange, label }: { checked: boolean; indeterminate?: boolean; onChange: (checked: boolean) => void; label: string }) {
  const ref = useRef<HTMLInputElement>(null)
  useEffect(() => { if (ref.current) ref.current.indeterminate = Boolean(indeterminate) }, [indeterminate])
  return (
    <label className="inline-grid min-h-11 min-w-11 cursor-pointer place-items-center">
      <input ref={ref} type="checkbox" aria-label={label} checked={checked} onChange={(e) => onChange(e.target.checked)} className="size-4 accent-forest" />
    </label>
  )
}

export interface BulkField { key: string; label: string; options?: { value: string; label: string }[]; hint?: string }
export interface BulkActionDef { action: string; label: string; needsReason?: boolean; danger?: boolean; fields?: BulkField[] }

/** The toolbar that appears once rows are selected; offers "select everything that matches" across pages. */
export function BulkBar({ selection, pageCount, total, actions, onAction, onSelectAll, onClear }: {
  selection: Selection; pageCount: number; total: number; actions: BulkActionDef[]; onAction: (a: BulkActionDef) => void; onSelectAll: () => void; onClear: () => void
}) {
  const n = selection.selectAll ? total : selection.ids.size
  if (n === 0) return null
  return (
    <div role="region" aria-label="Bulk actions" className="sticky top-14 z-10 mb-3 flex flex-wrap items-center gap-2 rounded-control bg-forest px-3 py-2 text-white shadow-pop">
      <p className="text-sm font-medium" aria-live="polite">{selection.selectAll ? `All ${total} matching selected` : `${n} selected`}</p>
      {!selection.selectAll && n >= pageCount && total > n && (
        <Button size="sm" variant="secondary" onClick={onSelectAll}>Select all {total} matching</Button>
      )}
      <span className="mx-1 hidden h-5 w-px bg-white/30 sm:block" aria-hidden="true" />
      {actions.map((a) => <Button key={a.action} size="sm" variant={a.danger ? 'destructive' : 'secondary'} onClick={() => onAction(a)}>{a.label}</Button>)}
      <Button size="sm" variant="ghost" className="ml-auto !text-white hover:!bg-white/15" onClick={onClear}>Clear</Button>
    </div>
  )
}

function EntryList({ title, entries, tone, withReasons }: { title: string; entries: BulkEntry[]; tone: 'bad' | 'warn' | 'good'; withReasons?: boolean }) {
  if (entries.length === 0) return null
  const color = { bad: 'text-danger', warn: 'text-warn', good: 'text-deep' }[tone]
  return (
    <div className="mt-3">
      <h3 className={`text-sm font-semibold ${color}`}>{title} ({entries.length})</h3>
      <ul className="mt-1 max-h-40 space-y-1 overflow-y-auto rounded-control bg-canvas p-2 text-sm">
        {entries.map((e) => (
          <li key={e.id}><span className="font-medium">{e.label}</span>
            {withReasons && e.reasons?.map((r) => <span key={r} className="block pl-3 text-xs text-muted">· {r}</span>)}
            {e.warnings?.map((w) => <span key={w} className="block pl-3 text-xs text-warn">· {w}</span>)}
          </li>
        ))}
      </ul>
    </div>
  )
}

/**
 * Preview → explicit confirmation → result. Nothing changes until "Apply"; the server re-checks each record,
 * so the result can differ from the preview, and successful / skipped / failed are reported separately.
 */
export function BulkDialog({ module, def, selection, filters, total, onClose, onDone }: {
  module: BulkModule; def: BulkActionDef | null; selection: Selection; filters: Record<string, string>; total: number; onClose: () => void; onDone: () => void
}) {
  const [reason, setReason] = useState('')
  const [params, setParams] = useState<Record<string, string>>({})
  const [preview, setPreview] = useState<BulkPreview | null>(null)
  const [result, setResult] = useState<BulkResult | null>(null)
  const request = (): BulkRequest => ({
    action: def?.action ?? '', reason, ...(def?.fields ? { params } : {}), ...(selection.selectAll ? { select_all: true, filters } : { ids: [...selection.ids] }),
  })
  const run = useMutation({ mutationFn: () => bulkPreview(module, request()), onSuccess: setPreview })
  const apply = useMutation({
    mutationFn: () => bulkApply(module, { ...request(), ...(selection.selectAll ? { expected_count: preview?.total ?? total } : {}) }),
    onSuccess: (data) => { setResult(data); onDone() },
  })
  const open = def !== null
  const started = useRef<string | null>(null)
  useEffect(() => {
    if (!def) { started.current = null; return }
    if (def.needsReason || def.fields || started.current === def.action) return
    started.current = def.action
    run.mutate()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [def])
  const close = () => { setReason(''); setParams({}); setPreview(null); setResult(null); started.current = null; run.reset(); apply.reset(); onClose() }
  const count = selection.selectAll ? total : selection.ids.size
  const needsReason = Boolean(def?.needsReason)
  const needsInput = Boolean(def?.fields?.length)
  const reasonOk = (!needsReason || reason.trim().length > 0) && (!needsInput || def!.fields!.every((f) => (params[f.key] ?? '').trim() !== ''))

  let footer: ReactNode
  if (result) footer = <Button onClick={close}>Done</Button>
  else if (!preview) footer = <><Button variant="outline" onClick={close}>Cancel</Button>{(needsReason || needsInput) && <Button disabled={!reasonOk} loading={run.isPending} onClick={() => run.mutate()}>Check {count} selected</Button>}</>
  else footer = (
    <>
      <Button variant="outline" onClick={close} disabled={apply.isPending}>Cancel</Button>
      <Button variant={def?.danger ? 'destructive' : 'primary'} disabled={preview.eligible_count === 0 || !reasonOk} loading={apply.isPending} onClick={() => apply.mutate()}>
        {def?.label} {preview.eligible_count} {preview.eligible_count === 1 ? 'record' : 'records'}
      </Button>
    </>
  )
  return (
    <Modal open={open} onClose={close} title={result ? 'Result' : `${def?.label ?? ''} · ${count} selected`} footer={footer}>
      {!preview && !result && (
        <div className="space-y-3">
          {def?.fields?.map((f) => (
            <label key={f.key} className="block text-sm font-medium">{f.label}<span className="text-danger" aria-hidden="true"> *</span>
              {f.options ? (
                <select className="mt-1 block min-h-11 w-full rounded-control border border-line bg-white px-3 text-sm" value={params[f.key] ?? ''} onChange={(e) => setParams((p) => ({ ...p, [f.key]: e.target.value }))}>
                  <option value="">Choose…</option>{f.options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
              ) : (
                <input inputMode="decimal" className="mt-1 block min-h-11 w-full rounded-control border border-line bg-white px-3 text-sm" value={params[f.key] ?? ''} onChange={(e) => setParams((p) => ({ ...p, [f.key]: e.target.value }))} />
              )}
              {f.hint && <span className="mt-1 block text-xs font-normal text-muted">{f.hint}</span>}
            </label>
          ))}
          {needsReason && (
            <label className="block text-sm font-medium">Reason (recorded and shown to the owner)<span className="text-danger" aria-hidden="true"> *</span>
              <Textarea rows={3} maxLength={255} className="mt-1" value={reason} onChange={(e) => setReason(e.target.value)} />
            </label>
          )}
          {run.isPending && <p role="status" className="text-sm text-muted">Checking every selected record…</p>}
        </div>
      )}
      {run.isError && <Alert tone="error" title="Could not check the selection">{errorMessage(run.error)}</Alert>}
      {apply.isError && <Alert tone="error" title="Nothing was applied">{errorMessage(apply.error)}</Alert>}
      {preview && !result && (
        <div>
          <p className="text-sm"><b>{preview.eligible_count}</b> of {preview.total} can be changed.{preview.blocked_count > 0 && <> <b className="text-danger">{preview.blocked_count}</b> will be left out.</>}</p>
          {preview.warning_count > 0 && <p className="mt-1 text-sm text-warn">{preview.warning_count} contain values filled in automatically. Review them before approving.</p>}
          {needsReason && <p className="mt-1 text-sm text-muted">Reason: {reason}</p>}
          <EntryList title="Blocked" entries={preview.blocked} tone="bad" withReasons />
          <EntryList title="Will be changed" entries={preview.eligible} tone="good" />
          {preview.total > preview.eligible.length + preview.blocked.length && <p className="mt-2 text-xs text-muted">Lists show the first 100 of each.</p>}
        </div>
      )}
      {result && (
        <div>
          <p className="text-sm"><b className="text-deep">{result.counts.successful}</b> done · <b className={result.counts.skipped ? 'text-warn' : ''}>{result.counts.skipped}</b> skipped · <b className={result.counts.failed ? 'text-danger' : ''}>{result.counts.failed}</b> failed</p>
          <EntryList title="Skipped" entries={result.skipped} tone="warn" withReasons />
          <EntryList title="Failed" entries={result.failed} tone="bad" withReasons />
          <EntryList title="Done" entries={result.successful.slice(0, 50)} tone="good" />
        </div>
      )}
    </Modal>
  )
}

/* ------------------------------------------------------------------ unsaved changes */

/** Warns before the tab closes or the page reloads while a form has unsaved edits. In-app navigation is guarded by the caller. */
export function useBeforeUnload(dirty: boolean) {
  useEffect(() => {
    if (!dirty) return
    const handler = (event: BeforeUnloadEvent) => { event.preventDefault() }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [dirty])
}
