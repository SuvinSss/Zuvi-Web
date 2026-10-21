import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import axios from 'axios'
import { CheckCircle2, Download, FileSpreadsheet, FileArchive, UploadCloud, XCircle } from 'lucide-react'
import { useRef, useState, type DragEvent } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Alert, Button, ButtonLink, Card, Field, Input, PageHeader, Select } from '@/components/ui'
import { useAuth } from '@/features/auth/AuthProvider'
import { errorMessage } from '@/lib/api'
import { formatBytes } from '@/lib/format'
import { commitImport, errorReportUrl, MappingRequired, previewImport, templateUrl } from '@/services/imports'
import { correctImportRow, importDetail, retryImport } from '@/services/management'
import { Modal } from '@/components/kit'
import type { NeedsMapping } from '@/types/management'
import type { ImportBatch, ImportMode, ImportRow } from '@/types/api'

export const MAX_SHEET_BYTES = 5 * 1024 * 1024
export const MAX_ZIP_BYTES = 50 * 1024 * 1024

export function checkSheet(file: File): string | null {
  if (!/\.(xlsx|csv)$/i.test(file.name)) return 'Upload an .xlsx or .csv file. Download the template to start.'
  if (file.size > MAX_SHEET_BYTES) return `That file is ${formatBytes(file.size)}; the limit is ${formatBytes(MAX_SHEET_BYTES)}.`
  return null
}

const MODES: { value: ImportMode; title: string; text: string }[] = [
  { value: 'create', title: 'Create new only', text: 'Rows whose SKU already exists in the store are reported as errors.' },
  { value: 'skip', title: 'Create new, skip existing', text: 'Existing SKUs are left untouched and counted as skipped.' },
  { value: 'update', title: 'Create new and update existing', text: 'Existing SKUs are updated. Changes are counted and logged.' },
]

function Tile({ label, value, tone = 'neutral' }: { label: string; value: number | string; tone?: 'neutral' | 'good' | 'bad' | 'warn' }) {
  const color = { neutral: 'text-forest', good: 'text-emerald', bad: 'text-danger', warn: 'text-warn' }[tone]
  return (
    <div className="rounded-control bg-canvas p-3 ring-1 ring-line">
      <p className={`text-2xl font-semibold tabular-nums ${color}`}>{value}</p>
      <p className="text-xs text-muted">{label}</p>
    </div>
  )
}

function ReportLinks({ id }: { id: string }) {
  return (
    <div className="flex flex-wrap gap-2">
      <ButtonLink href={errorReportUrl(id, 'xlsx')} variant="outline" icon={Download}>Error report (Excel)</ButtonLink>
      <ButtonLink href={errorReportUrl(id, 'csv')} variant="ghost" icon={Download}>CSV</ButtonLink>
    </div>
  )
}

function Dropzone({ file, onFile, error }: { file: File | null; onFile: (file: File | null) => void; error: string }) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [over, setOver] = useState(false)
  const onDrop = (event: DragEvent) => { event.preventDefault(); setOver(false); onFile(event.dataTransfer.files[0] ?? null) }
  return (
    <div>
      <div
        onDragOver={(event) => { event.preventDefault(); setOver(true) }}
        onDragLeave={() => setOver(false)}
        onDrop={onDrop}
        className={`flex flex-col items-center gap-2 rounded-card border-2 border-dashed p-6 text-center transition-colors sm:p-10 ${over ? 'border-emerald bg-pale' : 'border-line bg-white'}`}
      >
        <UploadCloud className="size-9 text-emerald" aria-hidden="true" />
        {file ? (
          <p className="font-medium text-ink"><FileSpreadsheet className="mr-1 inline size-4 text-emerald" aria-hidden="true" />{file.name} <span className="text-muted">({formatBytes(file.size)})</span></p>
        ) : (
          <p className="text-sm text-muted">Drag your Excel or CSV file here, or</p>
        )}
        <Button variant="outline" onClick={() => inputRef.current?.click()}>{file ? 'Choose a different file' : 'Choose file'}</Button>
        <input ref={inputRef} type="file" aria-label="Product spreadsheet" accept=".xlsx,.csv" className="sr-only" onChange={(event) => onFile(event.target.files?.[0] ?? null)} />
      </div>
      {error && <p role="alert" className="mt-2 text-sm text-danger">{error}</p>}
    </div>
  )
}

const STATUS_FILTERS = [['all', 'All rows'], ['incomplete', 'Needs a value'], ['invalid', 'Errors'], ['duplicates', 'Duplicates']] as const
const FIX_FIELDS: [string, string][] = [['store_code', 'Store code'], ['sku', 'SKU'], ['name', 'Name'], ['category', 'Category'], ['store_price', 'Store price'], ['brand', 'Brand'], ['unit', 'Unit'], ['unit_value', 'Unit value'], ['description', 'Description']]

function RowStatus({ row }: { row: ImportRow }) {
  if (row.status === 'valid' || row.status === 'skip') {
    return <span className="inline-flex items-center gap-1 text-deep"><CheckCircle2 className="size-4" aria-hidden="true" />{row.action === 'create' ? 'Will create' : row.action === 'update' ? 'Will update' : 'Will skip'}</span>
  }
  return (
    <div>
      <p className={`mb-0.5 text-xs font-semibold uppercase tracking-wide ${row.status === 'incomplete' ? 'text-warn' : 'text-danger'}`}>{row.status === 'incomplete' ? 'Needs a value' : 'Has an error'}</p>
      <ul className={`space-y-0.5 ${row.status === 'incomplete' ? 'text-warn' : 'text-danger'}`}>{row.errors.map((error, index) => <li key={index}><span className="font-medium">{error.column}:</span> {error.message}</li>)}</ul>
    </div>
  )
}

function FixDialog({ batchId, row, onClose, onSaved }: { batchId: string; row: ImportRow | null; onClose: () => void; onSaved: (row: ImportRow, counts: ImportBatch['counts']) => void }) {
  const [values, setValues] = useState<Record<string, string>>({})
  const [loadedFor, setLoadedFor] = useState<number | null>(null)
  if (row && loadedFor !== row.row) { setLoadedFor(row.row); setValues({ ...(row.values ?? {}) }) }
  const save = useMutation({
    mutationFn: () => correctImportRow(batchId, (row as ImportRow).row, values),
    onSuccess: (data) => { onSaved(data.row as unknown as ImportRow, data.counts as ImportBatch['counts']); onClose() },
  })
  return (
    <Modal open={row !== null} onClose={onClose} title={`Fix row ${row?.row ?? ''}`}
      footer={<><Button variant="outline" onClick={onClose} disabled={save.isPending}>Cancel</Button><Button loading={save.isPending} onClick={() => save.mutate()}>Save and re-check</Button></>}>
      <div className="space-y-3">
        <p className="text-sm text-muted">Only the values you enter here are used. Nothing is guessed: prices, stock and tax are never filled in for you.</p>
        {save.isError && <Alert tone="error">{errorMessage(save.error)}</Alert>}
        {row?.errors.map((e, i) => <p key={i} className="text-sm text-danger"><b>{e.column}:</b> {e.message}</p>)}
        {FIX_FIELDS.map(([key, label]) => (
          <Field key={key} label={label}>{(p) => <Input {...p} value={values[key] ?? ''} onChange={(e) => setValues({ ...values, [key]: e.target.value })} />}</Field>
        ))}
      </div>
    </Modal>
  )
}

function RowsTable({ batchId, rows, canFix, onRowFixed }: { batchId: string; rows: ImportRow[]; canFix: boolean; onRowFixed: (row: ImportRow, counts: ImportBatch['counts']) => void }) {
  const [filter, setFilter] = useState<(typeof STATUS_FILTERS)[number][0]>('all')
  const [page, setPage] = useState(0)
  const [fixing, setFixing] = useState<ImportRow | null>(null)
  const shown = rows.filter((row) => filter === 'all' || (filter === 'duplicates' ? row.duplicate : row.status === filter))
  const pages = Math.max(1, Math.ceil(shown.length / 25))
  const slice = shown.slice(page * 25, page * 25 + 25)
  return (
    <div>
      <div className="mb-3 flex flex-wrap gap-2" role="group" aria-label="Filter rows">
        {STATUS_FILTERS.map(([value, label]) => (
          <button key={value} type="button" aria-pressed={filter === value} onClick={() => { setFilter(value); setPage(0) }}
            className={`min-h-11 rounded-full px-4 text-sm font-medium ring-1 ring-inset ${filter === value ? 'bg-forest text-white ring-forest' : 'bg-white text-forest ring-line hover:bg-pale'}`}>{label}</button>
        ))}
      </div>
      <div className="overflow-x-auto rounded-control ring-1 ring-line">
        <table className="w-full min-w-[44rem] text-left text-sm">
          <thead className="bg-canvas text-xs uppercase tracking-wide text-muted">
            <tr><th scope="col" className="px-3 py-2">Row</th><th scope="col" className="px-3 py-2">SKU</th><th scope="col" className="px-3 py-2">Name</th><th scope="col" className="px-3 py-2">Result</th><th scope="col" className="px-3 py-2">Image</th>{canFix && <th scope="col" className="px-3 py-2"><span className="sr-only">Actions</span></th>}</tr>
          </thead>
          <tbody className="divide-y divide-line">
            {slice.length === 0 && <tr><td colSpan={6} className="px-3 py-6 text-center text-muted">No rows to show.</td></tr>}
            {slice.map((row) => (
              <tr key={row.row} className={row.status === 'invalid' ? 'bg-danger-bg/50' : row.status === 'incomplete' ? 'bg-warn-bg/50' : ''}>
                <td className="px-3 py-2 tabular-nums">{row.row}</td>
                <td className="px-3 py-2 font-mono text-xs">{row.sku || '—'}{row.generated?.includes('sku') && <span className="ml-1 rounded bg-warn-bg px-1 font-sans text-warn" title="Created from the product name because the file had no SKU">auto</span>}</td>
                <td className="max-w-[16rem] truncate px-3 py-2">{row.name || '—'}</td>
                <td className="px-3 py-2"><RowStatus row={row} />{row.normalized && Object.entries(row.normalized).map(([k, [from, to]]) => <p key={k} className="text-xs text-muted">Cleaned {k}: “{from}” → “{to}”</p>)}</td>
                <td className="px-3 py-2 text-muted">{row.image === 'none' ? 'Placeholder' : row.image === 'zip' ? 'From ZIP' : 'From URL'}</td>
                {canFix && <td className="px-3 py-2">{row.status !== 'valid' && row.status !== 'skip' && <Button size="sm" variant="outline" onClick={() => setFixing(row)}>Fix</Button>}</td>}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {pages > 1 && (
        <div className="mt-3 flex items-center justify-between text-sm text-muted">
          <span>Page {page + 1} of {pages}</span>
          <div className="flex gap-2">
            <Button variant="outline" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</Button>
            <Button variant="outline" disabled={page + 1 >= pages} onClick={() => setPage(page + 1)}>Next</Button>
          </div>
        </div>
      )}
      <FixDialog batchId={batchId} row={fixing} onClose={() => setFixing(null)} onSaved={onRowFixed} />
    </div>
  )
}

function MappingStep({ info, mapping, onChange, defaultStore, onDefaultStore, busy, onSubmit, onBack }: {
  info: NeedsMapping; mapping: Record<string, string>; onChange: (source: string, key: string) => void; defaultStore: string; onDefaultStore: (v: string) => void; busy: boolean; onSubmit: () => void; onBack: () => void
}) {
  const chosen = new Set(Object.values(mapping).filter(Boolean))
  const missing = info.columns.filter((c) => c.required && !chosen.has(c.key) && !(c.key === 'store_code' && defaultStore.trim()))
  return (
    <Card className="space-y-4 p-4 sm:p-6">
      <div className="flex flex-wrap items-center justify-between gap-2"><h2 className="text-lg font-semibold text-forest">Match your columns</h2><Button variant="ghost" onClick={onBack}>Choose a different file</Button></div>
      <Alert tone="info" title="We could not tell every column apart">Say what each column in your file means. Columns set to “Ignore” are not imported. Stock quantity is never imported: use stock entry for that.</Alert>
      <div className="overflow-x-auto rounded-control ring-1 ring-line">
        <table className="w-full min-w-[30rem] text-left text-sm">
          <thead className="bg-canvas text-xs uppercase tracking-wide text-muted"><tr><th scope="col" className="px-3 py-2">Column in your file</th><th scope="col" className="px-3 py-2">Treat it as</th></tr></thead>
          <tbody className="divide-y divide-line">
            {info.headers.map((h) => (
              <tr key={h}><th scope="row" className="px-3 py-2 font-medium">{h}</th>
                <td className="px-3 py-2"><Select aria-label={`What is “${h}”?`} value={mapping[h] ?? ''} onChange={(e) => onChange(h, e.target.value)}>
                  <option value="">Ignore this column</option>
                  {info.columns.map((c) => <option key={c.key} value={c.key} disabled={chosen.has(c.key) && mapping[h] !== c.key}>{c.key}{c.required ? ' (required)' : ''}</option>)}
                </Select></td></tr>
            ))}
          </tbody>
        </table>
      </div>
      <Field label="Store code for every row" hint="Only needed if your file has no store column. The store must already exist.">{(p) => <Input {...p} value={defaultStore} onChange={(e) => onDefaultStore(e.target.value)} />}</Field>
      {missing.length > 0 && <Alert tone="warn" title="Still missing">{missing.map((c) => `${c.key} — ${c.description}`).join(' · ')}</Alert>}
      <Button disabled={missing.length > 0} loading={busy} onClick={onSubmit}>Check file with this mapping</Button>
    </Card>
  )
}

export default function ImportPage() {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const zipRef = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [zip, setZip] = useState<File | null>(null)
  const [fileError, setFileError] = useState('')
  const [mode, setMode] = useState<ImportMode>('create')
  const [initialStatus, setInitialStatus] = useState<'DRAFT' | 'PENDING'>('DRAFT')
  const [validOnly, setValidOnly] = useState(false)
  const [allowUrls, setAllowUrls] = useState(false)
  const [batch, setBatch] = useState<ImportBatch | null>(null)
  const [confirming, setConfirming] = useState(false)
  const [commitError, setCommitError] = useState('')
  const [mappingInfo, setMappingInfo] = useState<NeedsMapping | null>(null)
  const [mapping, setMapping] = useState<Record<string, string>>({})
  const [defaultStore, setDefaultStore] = useState('')
  const [params, setParams] = useSearchParams()
  const job = params.get('job')

  // Re-open a saved import (from the jobs list) to correct rows or retry.
  const saved = useQuery({ queryKey: ['import-job', job], queryFn: () => importDetail(job as string), enabled: Boolean(job) && !batch })
  const [loadedJob, setLoadedJob] = useState<string | null>(null)
  if (saved.data && !batch && loadedJob !== saved.data.id) { setLoadedJob(saved.data.id); setBatch(saved.data as unknown as ImportBatch) }

  const preview = useMutation({
    mutationFn: () => previewImport({ file: file as File, imagesZip: zip, mode, allOrNothing: !validOnly, initialStatus, allowImageUrls: allowUrls, mapping, defaultStoreCode: defaultStore }),
    onSuccess: (data) => { setBatch(data); setMappingInfo(null); setConfirming(false); setCommitError('') },
    onError: (error) => {
      if (error instanceof MappingRequired) {
        setMappingInfo(error.info)
        setMapping(Object.fromEntries(error.info.proposal.filter((p) => p.key).map((p) => [p.source, p.key as string])))
      }
    },
  })
  const retry = useMutation({
    mutationFn: (id: string) => retryImport(id),
    onSuccess: async (data) => { setBatch(data as unknown as ImportBatch); await queryClient.invalidateQueries({ queryKey: ['products'] }) },
    onError: (error) => setCommitError(errorMessage(error)),
  })
  const onRowFixed = (row: ImportRow, counts: ImportBatch['counts']) =>
    setBatch((b) => (b ? { ...b, counts: { ...b.counts, ...counts }, rows: b.rows?.map((r) => (r.row === row.row ? row : r)) } : b))
  const commit = useMutation({
    mutationFn: (id: string) => commitImport(id),
    onSuccess: async (data) => { setBatch(data); setConfirming(false); await queryClient.invalidateQueries({ queryKey: ['products'] }) },
    onError: (error) => {
      setConfirming(false)
      setCommitError(errorMessage(error))
      if (axios.isAxiosError(error) && error.response?.status === 409 && error.response.data?.import) setBatch(error.response.data.import as ImportBatch)
    },
  })

  const pickFile = (chosen: File | null) => {
    const problem = chosen ? checkSheet(chosen) : null
    setFileError(problem ?? '')
    setFile(problem ? null : chosen)
  }
  const reset = () => { setBatch(null); setFile(null); setZip(null); setConfirming(false); setCommitError(''); setMappingInfo(null); setMapping({}); setDefaultStore(''); if (job) setParams({}); preview.reset(); commit.reset(); retry.reset() }

  const committed = batch && batch.status !== 'PREVIEWED'
  const canChange = Boolean(user?.permissions.change)

  return (
    <>
      <PageHeader title="Import products from Excel" subtitle="Download the template, fill it in, then review everything before anything is saved." />

      {!batch && mappingInfo && (
        <MappingStep info={mappingInfo} mapping={mapping} onChange={(source, key) => setMapping((m) => ({ ...m, [source]: key }))} defaultStore={defaultStore} onDefaultStore={setDefaultStore}
          busy={preview.isPending} onSubmit={() => preview.mutate()} onBack={reset} />
      )}

      {!batch && !mappingInfo && (
        <div className="space-y-6">
          <Card className="space-y-4 p-4 sm:p-6">
            <h2 className="text-lg font-semibold text-forest">1 · Get the template</h2>
            <p className="text-sm text-muted">Dark-green columns are required. The Instructions sheet explains each column, and the Reference sheet lists your store codes, categories, brands and tags.</p>
            <ButtonLink href={templateUrl()} variant="outline" icon={Download}>Download Excel template</ButtonLink>
          </Card>

          <Card className="space-y-4 p-4 sm:p-6">
            <h2 className="text-lg font-semibold text-forest">2 · Upload your file</h2>
            <Dropzone file={file} onFile={pickFile} error={fileError} />
            <div className="rounded-control bg-canvas p-3 text-sm">
              <p className="font-medium">Product photos (optional)</p>
              <p className="mt-0.5 text-muted">Put photos in a ZIP and write each file name in the <code>image_file</code> column. Photos are optimized like manual uploads.</p>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <Button variant="outline" icon={FileArchive} onClick={() => zipRef.current?.click()}>{zip ? 'Change ZIP' : 'Add images ZIP'}</Button>
                {zip && <span className="text-sm">{zip.name} ({formatBytes(zip.size)}) <button type="button" className="ml-1 text-danger underline" onClick={() => setZip(null)}>remove</button></span>}
                <input ref={zipRef} type="file" aria-label="Images ZIP" accept=".zip" className="sr-only" onChange={(event) => {
                  const chosen = event.target.files?.[0] ?? null
                  setZip(chosen && chosen.size > MAX_ZIP_BYTES ? null : chosen)
                  if (chosen && chosen.size > MAX_ZIP_BYTES) setFileError(`The images ZIP is larger than ${formatBytes(MAX_ZIP_BYTES)}.`)
                }} />
              </div>
            </div>
          </Card>

          <Card className="space-y-4 p-4 sm:p-6">
            <h2 className="text-lg font-semibold text-forest">3 · Choose how to import</h2>
            <fieldset className="space-y-2">
              <legend className="sr-only">Import mode</legend>
              {MODES.filter((option) => option.value !== 'update' || canChange).map((option) => (
                <label key={option.value} className={`flex min-h-11 cursor-pointer gap-3 rounded-control p-3 ring-1 ring-inset has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-emerald ${mode === option.value ? 'bg-pale ring-emerald/50' : 'ring-line'}`}>
                  <input type="radio" name="mode" className="mt-1 size-4 accent-forest" checked={mode === option.value} onChange={() => setMode(option.value)} />
                  <span><span className="block text-sm font-medium">{option.title}</span><span className="block text-xs text-muted">{option.text}</span></span>
                </label>
              ))}
            </fieldset>
            <Field label="New products start as">
              {(props) => <Select {...props} value={initialStatus} onChange={(event) => setInitialStatus(event.target.value as 'DRAFT' | 'PENDING')}>
                <option value="DRAFT">Draft (not submitted)</option><option value="PENDING">Pending (submitted for review)</option>
              </Select>}
            </Field>
            <label className="flex min-h-11 items-start gap-3 text-sm"><input type="checkbox" className="mt-1 size-4 accent-forest" checked={validOnly} onChange={(event) => setValidOnly(event.target.checked)} />
              <span><span className="font-medium">Import valid rows only</span><span className="block text-xs text-muted">By default nothing is imported if any row has an error.</span></span></label>
            {canChange && (
              <label className="flex min-h-11 items-start gap-3 text-sm"><input type="checkbox" className="mt-1 size-4 accent-forest" checked={allowUrls} onChange={(event) => setAllowUrls(event.target.checked)} />
                <span><span className="font-medium">Allow image URLs</span><span className="block text-xs text-muted">Downloads from public web addresses in <code>image_url</code> only. Use images you are allowed to reuse.</span></span></label>
            )}
            {preview.isError && !(preview.error instanceof MappingRequired) && <Alert tone="error" title="We couldn’t read that file">{errorMessage(preview.error)}</Alert>}
            <Button disabled={!file} loading={preview.isPending} onClick={() => preview.mutate()}>{preview.isPending ? 'Checking your file…' : 'Check file'}</Button>
          </Card>
        </div>
      )}

      {batch && !committed && (
        <div className="space-y-6">
          <Card className="space-y-5 p-4 sm:p-6">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-lg font-semibold text-forest">Review · {batch.source_name}</h2>
              <Button variant="ghost" onClick={reset}>Choose a different file</Button>
            </div>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
              <Tile label="Rows" value={batch.counts.total} />
              <Tile label="Valid" value={batch.counts.valid} tone="good" />
              <Tile label="Need a value" value={batch.counts.incomplete ?? 0} tone={batch.counts.incomplete ? 'warn' : 'neutral'} />
              <Tile label="Errors" value={batch.counts.hard_invalid ?? batch.counts.invalid} tone={(batch.counts.hard_invalid ?? batch.counts.invalid) ? 'bad' : 'neutral'} />
              <Tile label="Duplicates" value={batch.counts.duplicates} tone={batch.counts.duplicates ? 'warn' : 'neutral'} />
            </div>
            {batch.already_imported && <Alert tone="warn" title="This file was already imported">Importing it again could duplicate products. Change the data first.</Alert>}
            {(batch.ignored_columns?.length ?? 0) > 0 && <Alert tone="info">Ignored columns: {batch.ignored_columns?.join(', ')}</Alert>}
            {commitError && <Alert tone="error" title="Nothing was imported">{commitError}</Alert>}
            {batch.counts.invalid > 0 && (
              <Alert tone="warn" title={`${batch.counts.invalid} row${batch.counts.invalid === 1 ? ' needs' : 's need'} attention`}>
                {batch.all_or_nothing ? 'Use Fix on each row to supply the missing value, or go back and choose “Import valid rows only”.' : 'Rows with errors will be skipped and listed in the result.'}
              </Alert>
            )}
            {batch.counts.invalid > 0 && <ReportLinks id={batch.id} />}
            {batch.rows && <RowsTable batchId={batch.id} rows={batch.rows} canFix onRowFixed={onRowFixed} />}
          </Card>

          <Card className="p-4 sm:p-6">
            {confirming ? (
              <div role="alertdialog" aria-labelledby="confirm-title" className="space-y-3">
                <h2 id="confirm-title" className="text-lg font-semibold text-forest">Confirm import</h2>
                <p className="text-sm">This will create <b>{batch.counts.create ?? 0}</b>{(batch.counts.update ?? 0) > 0 && <>, update <b>{batch.counts.update}</b></>}{(batch.counts.skip ?? 0) > 0 && <>, and skip <b>{batch.counts.skip}</b></>} product(s).{batch.counts.invalid > 0 && !batch.all_or_nothing && <> {batch.counts.invalid} row(s) with errors will be left out.</>}</p>
                <div className="flex flex-wrap gap-2">
                  <Button loading={commit.isPending} onClick={() => commit.mutate(batch.id)}>{commit.isPending ? 'Importing… keep this page open' : 'Yes, import now'}</Button>
                  <Button variant="outline" disabled={commit.isPending} onClick={() => setConfirming(false)}>Cancel</Button>
                </div>
              </div>
            ) : (
              <div className="flex flex-wrap items-center gap-3">
                <Button disabled={batch.counts.valid === 0 || batch.already_imported || (batch.all_or_nothing && batch.counts.invalid > 0)} onClick={() => setConfirming(true)}>Import {batch.counts.valid} product{batch.counts.valid === 1 ? '' : 's'}…</Button>
                <p className="text-sm text-muted">Nothing is saved until you confirm.</p>
              </div>
            )}
          </Card>
        </div>
      )}

      {batch && committed && (
        <Card className="space-y-5 p-4 sm:p-6">
          {batch.summary.outcome === 'complete' ? (
            <div className="flex items-center gap-3 text-deep"><CheckCircle2 className="size-8" aria-hidden="true" /><h2 className="text-xl font-semibold">Import complete</h2></div>
          ) : (
            <div className="flex items-center gap-3 text-warn"><XCircle className="size-8" aria-hidden="true" /><h2 className="text-xl font-semibold">{batch.summary.outcome === 'rolled_back' ? 'Import rolled back — nothing was saved' : 'Import finished — some rows were left out'}</h2></div>
          )}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            <Tile label="Created" value={batch.summary.created ?? 0} tone="good" />
            <Tile label="Updated" value={batch.summary.updated ?? 0} />
            <Tile label="Skipped" value={batch.summary.skipped ?? 0} />
            <Tile label="Failed" value={batch.summary.failed ?? 0} tone={batch.summary.failed ? 'bad' : 'neutral'} />
            <Tile label="Images processed" value={batch.summary.images_processed ?? 0} />
            <Tile label="Placeholders used" value={batch.summary.fallback_images ?? 0} />
          </div>
          {batch.errors.length > 0 && (
            <>
              <ul className="max-h-64 space-y-1 overflow-y-auto rounded-control bg-danger-bg/50 p-3 text-sm text-danger">
                {batch.errors.slice(0, 50).map((error, index) => <li key={index}>Row {error.row}{error.column ? ` · ${error.column}` : ''}: {error.message}</li>)}
              </ul>
              <ReportLinks id={batch.id} />
            </>
          )}
          {commitError && <Alert tone="error">{commitError}</Alert>}
          <div className="flex flex-wrap gap-2">
            {batch.retryable && <Button variant="secondary" loading={retry.isPending} onClick={() => retry.mutate(batch.id)}>Retry the {batch.summary.failed} left-out row{batch.summary.failed === 1 ? '' : 's'}</Button>}
            <ButtonLink to="/admin/products">View products</ButtonLink>
            <Button variant="outline" onClick={reset}>Import another file</Button>
          </div>
        </Card>
      )}
    </>
  )
}
