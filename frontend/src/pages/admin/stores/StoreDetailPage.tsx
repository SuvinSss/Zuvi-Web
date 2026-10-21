import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, Pencil, Plus, ShieldCheck } from 'lucide-react'
import { useState } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { BulkDialog, Tabs, TabPanel, type BulkActionDef } from '@/components/management'
import { FilePicker, KeyValue, Modal, QueryBoundary, Section, Stat, Status, Timeline, useToast } from '@/components/kit'
import { Alert, Button, ButtonLink, Card, Field, Input, PageHeader, Select } from '@/components/ui'
import { errorMessage, fieldErrors } from '@/lib/api'
import { formatDateTime } from '@/lib/format'
import { addStoreStaff, getStore, storeDocuments, storeMeta, storeStaff, uploadStoreDocument, verifyStore } from '@/services/management'
import type { StoreDetail } from '@/types/management'

const TABS = [
  { id: 'overview', label: 'Overview' }, { id: 'business', label: 'Business info' }, { id: 'address', label: 'Address' }, { id: 'staff', label: 'Owner & staff' },
  { id: 'products', label: 'Products & inventory' }, { id: 'orders', label: 'Orders' }, { id: 'hours', label: 'Operating hours' }, { id: 'delivery', label: 'Delivery & serviceability' },
  { id: 'documents', label: 'Documents & verification' }, { id: 'commercial', label: 'Commercial' }, { id: 'activity', label: 'Activity' },
]
const DAY: Record<string, string> = { mon: 'Monday', tue: 'Tuesday', wed: 'Wednesday', thu: 'Thursday', fri: 'Friday', sat: 'Saturday', sun: 'Sunday' }
const ACTIONS: Record<string, BulkActionDef> = {
  ACTIVE: { action: 'approve', label: 'Approve' }, REJECTED: { action: 'reject', label: 'Reject', needsReason: true, danger: true },
  SUSPENDED: { action: 'suspend', label: 'Suspend', needsReason: true, danger: true },
}
const money = (v: string | null) => (v === null ? 'Not set' : `₹${Number(v).toLocaleString('en-IN')}`)

function StaffTab({ store, canChange }: { store: StoreDetail; canChange: boolean }) {
  const qc = useQueryClient()
  const toast = useToast()
  const staff = useQuery({ queryKey: ['store-staff', store.id], queryFn: () => storeStaff(store.id) })
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState({ username: '', email: '', first_name: '', last_name: '', phone_number: '', password: '', designation: '' })
  const [primary, setPrimary] = useState(false)
  const add = useMutation({
    mutationFn: () => addStoreStaff(store.id, { ...form, phone_number: form.phone_number || null, is_primary: primary }),
    onSuccess: () => { toast('success', 'Staff account created.'); setOpen(false); setForm({ username: '', email: '', first_name: '', last_name: '', phone_number: '', password: '', designation: '' }); void qc.invalidateQueries({ queryKey: ['store-staff', store.id] }); void qc.invalidateQueries({ queryKey: ['admin-store', store.id] }) },
  })
  const errs = fieldErrors(add.error)
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value })
  return (
    <Section title="Owner & staff" actions={canChange && <Button icon={Plus} onClick={() => { add.reset(); setOpen(true) }}>Add staff</Button>}>
      <QueryBoundary query={staff} isEmpty={staff.data?.length === 0} empty={{ icon: ShieldCheck, title: 'No owner yet', text: 'A store needs an owner account before it can be approved.' }}>
        <ul className="divide-y divide-line rounded-control ring-1 ring-line">
          {staff.data?.map((m) => (
            <li key={m.id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-3">
              <div><p className="font-medium">{m.name || m.username} {m.is_primary && <span className="ml-1 rounded-full bg-mint px-2 text-xs text-deep">Owner</span>}</p><p className="text-xs text-muted">{m.username} · {m.email}{m.designation ? ` · ${m.designation}` : ''}</p></div>
              <Status value={m.is_active ? 'ACTIVE' : 'INACTIVE'} />
            </li>
          ))}
        </ul>
      </QueryBoundary>
      <Modal open={open} onClose={() => setOpen(false)} title="Add staff account"
        footer={<><Button variant="outline" onClick={() => setOpen(false)} disabled={add.isPending}>Cancel</Button><Button loading={add.isPending} disabled={!form.username || !form.email || !form.password} onClick={() => add.mutate()}>Create account</Button></>}>
        <div className="space-y-3">
          {add.isError && Object.keys(errs).length === 0 && <Alert tone="error">{errorMessage(add.error)}</Alert>}
          <Field label="Username" required error={errs.username}>{(p) => <Input {...p} autoComplete="off" value={form.username} onChange={set('username')} />}</Field>
          <Field label="Email" required error={errs.email}>{(p) => <Input {...p} type="email" autoComplete="off" value={form.email} onChange={set('email')} />}</Field>
          <Field label="Designation">{(p) => <Input {...p} value={form.designation} onChange={set('designation')} />}</Field>
          <Field label="Temporary password" required error={errs.password} hint="Share it securely. It is never shown again.">{(p) => <Input {...p} type="password" autoComplete="new-password" value={form.password} onChange={set('password')} />}</Field>
          <label className="flex min-h-11 items-center gap-2 text-sm"><input type="checkbox" className="size-4 accent-forest" checked={primary} onChange={(e) => setPrimary(e.target.checked)} />Make this the store owner (primary contact)</label>
        </div>
      </Modal>
    </Section>
  )
}

function DocumentsTab({ store, canChange, canApprove }: { store: StoreDetail; canChange: boolean; canApprove: boolean }) {
  const qc = useQueryClient()
  const toast = useToast()
  const docs = useQuery({ queryKey: ['store-docs', store.id], queryFn: () => storeDocuments(store.id) })
  const [kind, setKind] = useState('GST')
  const [file, setFile] = useState<File | null>(null)
  const upload = useMutation({
    mutationFn: () => uploadStoreDocument(store.id, kind, file as File),
    onSuccess: () => { toast('success', 'Document uploaded. The store is still unverified.'); setFile(null); void qc.invalidateQueries({ queryKey: ['store-docs', store.id] }); void qc.invalidateQueries({ queryKey: ['admin-store', store.id] }) },
    onError: (e) => toast('error', errorMessage(e)),
  })
  const verify = useMutation({
    mutationFn: (s: 'VERIFIED' | 'REJECTED') => verifyStore(store.id, s),
    onSuccess: () => { toast('success', 'Verification recorded.'); void qc.invalidateQueries({ queryKey: ['admin-store', store.id] }) },
    onError: (e) => toast('error', errorMessage(e)),
  })
  return (
    <div className="space-y-6">
      <Section title="Verification" actions={canApprove && <span className="flex gap-2">
        <Button variant="secondary" loading={verify.isPending && verify.variables === 'VERIFIED'} disabled={store.verification_status === 'VERIFIED'} onClick={() => verify.mutate('VERIFIED')}>Mark verified</Button>
        <Button variant="destructive" loading={verify.isPending && verify.variables === 'REJECTED'} onClick={() => verify.mutate('REJECTED')}>Reject verification</Button></span>}>
        <KeyValue rows={[['Status', <Status key="v" value={store.verification_status} />], ['GSTIN', store.gstin || 'Not provided'], ['Verified by', store.verified_by ? `${store.verified_by} · ${formatDateTime(store.verified_at ?? '')}` : '—']]} />
        <p className="mt-2 text-xs text-muted">Uploading documents or entering a GSTIN never verifies a store; a person with approval rights must do it here.</p>
      </Section>
      <Section title="Documents">
        <QueryBoundary query={docs} isEmpty={docs.data?.length === 0} empty={{ icon: Download, title: 'No documents uploaded' }}>
          <ul className="divide-y divide-line rounded-control ring-1 ring-line">
            {docs.data?.map((d) => <li key={d.id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-3 text-sm"><span>{d.kind} · <a className="font-medium text-forest underline" href={d.url} target="_blank" rel="noreferrer">{d.title || 'Open document'}</a></span><span className="text-xs text-muted">{d.uploaded_by} · {formatDateTime(d.uploaded_at)}</span></li>)}
          </ul>
        </QueryBoundary>
        {canChange && (
          <div className="mt-4 flex flex-wrap items-end gap-3">
            <Field label="Type">{(p) => <Select {...p} value={kind} onChange={(e) => setKind(e.target.value)}><option value="GST">GST certificate</option><option value="FSSAI">FSSAI licence</option><option value="TRADE">Trade licence</option><option value="ID">Owner identity proof</option><option value="OTHER">Other</option></Select>}</Field>
            <FilePicker label="File" accept="application/pdf,image/jpeg,image/png,image/webp" maxBytes={8 * 1024 * 1024} hint="PDF or image, up to 8 MB" file={file} onFile={setFile} />
            <Button disabled={!file} loading={upload.isPending} onClick={() => upload.mutate()}>Upload</Button>
          </div>
        )}
      </Section>
    </div>
  )
}

export default function StoreDetailPage() {
  const { id } = useParams()
  const storeId = Number(id)
  const qc = useQueryClient()
  const [params, setParams] = useSearchParams()
  const tab = params.get('tab') ?? 'overview'
  const meta = useQuery({ queryKey: ['store-meta'], queryFn: storeMeta, staleTime: 5 * 60_000 })
  const q = useQuery({ queryKey: ['admin-store', storeId], queryFn: () => getStore(storeId) })
  const [action, setAction] = useState<BulkActionDef | null>(null)
  const s = q.data
  const can = { change: Boolean(meta.data?.can_change), approve: Boolean(meta.data?.can_approve) }
  return (
    <QueryBoundary query={q}>
      {s && <>
        <PageHeader title={s.name} subtitle={`${s.store_code} · ${s.city || 'No city'}`}
          actions={<>
            {can.approve && s.next_statuses.filter((n) => ACTIONS[n]).map((n) => <Button key={n} variant={ACTIONS[n]!.danger ? 'destructive' : 'secondary'} onClick={() => setAction(ACTIONS[n]!)}>{ACTIONS[n]!.label}</Button>)}
            {can.approve && s.status === 'SUSPENDED' && <Button variant="secondary" onClick={() => setAction({ action: 'reactivate', label: 'Reactivate' })}>Reactivate</Button>}
            {can.change && <ButtonLink icon={Pencil} to={`/admin/stores/${s.id}/edit`}>Edit</ButtonLink>}
          </>} />
        <Tabs label="Store sections" tabs={TABS.map((t) => (t.id === 'staff' ? { ...t, badge: s.counts.staff } : t.id === 'documents' ? { ...t, badge: s.counts.documents } : t))} active={tab}
          onChange={(t) => setParams((c) => { const n = new URLSearchParams(c); n.set('tab', t); return n }, { replace: true })} />
        <TabPanel id="store">
          {tab === 'overview' && (
            <div className="space-y-5">
              <div className="flex flex-wrap items-center gap-2"><Status value={s.status} /><Status value={s.verification_status} label={`Verification: ${s.verification_status.toLowerCase()}`} />{s.status === 'ACTIVE' && !s.ordering_enabled && <Status value="PENDING" label="Not taking orders" />}</div>
              {s.missing_requirements.length > 0 && <Alert tone="warn" title="Needed before approval">{s.missing_requirements.join(', ')}</Alert>}
              {s.status === 'ACTIVE' && s.operational_gaps.length > 0 && <Alert tone="warn" title="Approved, but not taking orders yet">Add: {s.operational_gaps.join(', ')}.</Alert>}
              <div className="grid gap-3 sm:grid-cols-3"><Stat label="Products" value={s.counts.products} /><Stat label="Orders" value={s.counts.orders} /><Stat label="Staff accounts" value={s.counts.staff} /></div>
              <KeyValue rows={[['Approved by', s.approved_by ? `${s.approved_by} · ${formatDateTime(s.approved_at ?? '')}` : '—'], ['Created by', `${s.created_by ?? '—'} (${s.creation_source === 'ADMIN' ? 'management' : 'earlier record'})`], ['Rating', s.rating.count ? `${s.rating.average.toFixed(1)} (${s.rating.count})` : 'No ratings yet']]} />
            </div>
          )}
          {tab === 'business' && <Card className="p-4"><KeyValue rows={[['Store type', s.store_type.replace('_', ' ').toLowerCase()], ['Category', s.category], ['Business name', s.business_name || '—'], ['GSTIN', s.gstin || '—'], ['Phone', s.contact_phone || '—'], ['Alternative phone', s.alternative_phone || '—'], ['Email', s.email || '—'], ['Description', s.description || '—']]} /></Card>}
          {tab === 'address' && <Card className="p-4"><KeyValue rows={[['Address', [s.address.line1, s.address.line2, s.address.landmark].filter(Boolean).join(', ')], ['City', s.address.city], ['District', s.address.district || '—'], ['State', s.address.state], ['Postal code', s.address.postal_code], ['Country', s.address.country], ['Coordinates', Number(s.address.latitude) || Number(s.address.longitude) ? `${s.address.latitude}, ${s.address.longitude}` : 'Not set']]} /></Card>}
          {tab === 'staff' && <StaffTab store={s} canChange={can.change} />}
          {tab === 'products' && (
            <Section title="Products & inventory" actions={<ButtonLink variant="outline" to={`/admin/products?store=${s.id}`}>Open product list</ButtonLink>}>
              <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-5">{Object.entries(s.counts.products_by_status).map(([k, v]) => <Stat key={k} label={k.charAt(0) + k.slice(1).toLowerCase()} value={v} />)}{s.counts.products === 0 && <p className="text-sm text-muted">This store has no products yet.</p>}</div>
            </Section>
          )}
          {tab === 'orders' && <Section title="Orders" actions={<ButtonLink variant="outline" to={`/admin/orders?store=${s.id}`}>Open orders for this store</ButtonLink>}><Stat label="Orders received" value={s.counts.orders} /></Section>}
          {tab === 'hours' && (
            <Card className="p-4">
              <table className="w-full max-w-md text-sm"><caption className="sr-only">Weekly opening hours</caption><tbody>
                {Object.keys(DAY).map((d) => <tr key={d} className="border-b border-line last:border-0"><th scope="row" className="py-2 pr-4 text-left font-medium">{DAY[d]}</th><td className="py-2">{s.opening_hours[d]?.length ? s.opening_hours[d].map((x) => `${x.open}–${x.close}`).join(', ') : <span className="text-muted">Closed</span>}</td></tr>)}
              </tbody></table>
              {s.closures.length > 0 && <p className="mt-3 text-sm">Closures: {s.closures.map((c) => `${c.date}${c.reason ? ` (${c.reason})` : ''}`).join(', ')}</p>}
            </Card>
          )}
          {tab === 'delivery' && <Card className="p-4"><KeyValue rows={[['Delivery', s.offers_delivery ? 'Yes' : 'No'], ['Pickup', s.offers_pickup ? 'Yes' : 'No'], ['Delivery radius', s.service_radius_km ? `${s.service_radius_km} km` : 'Not set'], ['Minimum order', money(s.min_order_amount)], ['Accepting orders', s.accepts_orders ? 'Yes' : 'No'], ['Ready to take orders', s.ordering_enabled ? 'Yes' : `No${s.operational_gaps.length ? ` — missing ${s.operational_gaps.join(', ')}` : ''}`]]} /></Card>}
          {tab === 'documents' && <DocumentsTab store={s} canChange={can.change} canApprove={can.approve} />}
          {tab === 'commercial' && <Card className="p-4"><KeyValue rows={[['Commission', `${s.commission_percentage}%`], ['Minimum order', money(s.min_order_amount)], ['Tax and payout settings', 'Not configured on the platform yet']]} /></Card>}
          {tab === 'activity' && <Section title="Status history">{s.history.length === 0 ? <p className="text-sm text-muted">No changes recorded.</p> : <Timeline items={s.history.map((h, i) => ({ key: String(i), title: `${h.old ? `${h.old} → ` : ''}${h.new}`, at: h.at, note: `${h.by}${h.reason ? ` — ${h.reason}` : ''}`, tone: i === 0 ? 'current' : 'done' }))} />}</Section>}
        </TabPanel>
        <BulkDialog module="stores" def={action} selection={{ ids: new Set([s.id]), selectAll: false }} filters={{}} total={1} onClose={() => setAction(null)}
          onDone={() => { void qc.invalidateQueries({ queryKey: ['admin-store', storeId] }); void qc.invalidateQueries({ queryKey: ['admin-stores'] }); void qc.invalidateQueries({ queryKey: ['admin-counts'] }) }} />
      </>}
    </QueryBoundary>
  )
}
