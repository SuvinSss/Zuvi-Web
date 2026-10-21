import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { useBlocker, useNavigate, useParams } from 'react-router-dom'
import { FilePicker, Modal, QueryBoundary, useToast } from '@/components/kit'
import { useBeforeUnload } from '@/components/management'
import { Alert, Button, Card, Field, Input, PageHeader, Select, Textarea } from '@/components/ui'
import { errorMessage, fieldErrors } from '@/lib/api'
import { createStore, getStore, storeMeta, updateStore, uploadStoreDocument, uploadStoreImages } from '@/services/management'
import type { Hours, StoreDetail, StoreWrite } from '@/types/management'

const DAY_LABEL: Record<string, string> = { mon: 'Monday', tue: 'Tuesday', wed: 'Wednesday', thu: 'Thursday', fri: 'Friday', sat: 'Saturday', sun: 'Sunday' }
const DOC_KINDS = [['GST', 'GST certificate'], ['FSSAI', 'FSSAI licence'], ['TRADE', 'Trade licence'], ['ID', 'Owner identity proof'], ['OTHER', 'Other']] as const
const STEPS = ['Basics', 'Address & location', 'Business & documents', 'Hours & ordering', 'Owner', 'Commercial & review'] as const

const blank = (): StoreWrite => ({
  name: '', store_type: 'PARTNER_STORE', category: '', contact_phone: '', alternative_phone: '', email: '', description: '', business_name: '', gstin: '',
  commission_percentage: '0', accepts_orders: true, offers_delivery: true, offers_pickup: false, min_order_amount: '', service_radius_km: '',
  opening_hours: {}, closures: [], address: { line1: '', line2: '', landmark: '', city: '', district: '', state: '', postal_code: '', country: 'India', latitude: '', longitude: '' },
})
const blankOwner = () => ({ username: '', email: '', first_name: '', last_name: '', phone_number: '', password: '', designation: 'Owner' })

function fromDetail(d: StoreDetail): StoreWrite {
  return {
    name: d.name, store_type: d.store_type, category: d.category_id ?? '', contact_phone: d.contact_phone, alternative_phone: d.alternative_phone, email: d.email,
    description: d.description, business_name: d.business_name, gstin: d.gstin, commission_percentage: d.commission_percentage, accepts_orders: d.accepts_orders,
    offers_delivery: d.offers_delivery, offers_pickup: d.offers_pickup, min_order_amount: d.min_order_amount ?? '', service_radius_km: d.service_radius_km ?? '',
    opening_hours: d.opening_hours, closures: d.closures,
    address: { ...d.address, latitude: Number(d.address.latitude) ? d.address.latitude : '', longitude: Number(d.address.longitude) ? d.address.longitude : '' },
  }
}

/** Serialise the form; empty optional numbers are omitted instead of being sent as made-up values. */
function payload(form: StoreWrite, owner: ReturnType<typeof blankOwner> | null, draft: boolean, edit: boolean): Record<string, unknown> {
  const { address, ...rest } = form
  const body: Record<string, unknown> = { ...rest, category: form.category === '' ? undefined : form.category }
  for (const key of ['min_order_amount', 'service_radius_km'] as const) body[key] = rest[key] === '' ? null : rest[key]
  const addr: Record<string, unknown> = { ...address }
  for (const key of ['latitude', 'longitude'] as const) if (address[key] === '') delete addr[key]
  body.address = addr
  if (!edit) { body.save_draft = draft; if (owner && owner.username) body.owner = { ...owner, phone_number: owner.phone_number || null } }
  return body
}

function Grid({ children }: { children: ReactNode }) { return <div className="grid gap-4 sm:grid-cols-2">{children}</div> }
const flatten = (e: Record<string, string>, key: string) => e[key] ?? e[`address.${key}`] ?? e[`owner.${key}`]

export default function StoreWizard() {
  const { id } = useParams()
  const editId = id ? Number(id) : null
  const existing = useQuery({ queryKey: ['admin-store', editId], queryFn: () => getStore(editId as number), enabled: editId !== null })
  const meta = useQuery({ queryKey: ['store-meta'], queryFn: storeMeta, staleTime: 5 * 60_000 })
  if (editId !== null && !existing.data) return <QueryBoundary query={existing}>{null}</QueryBoundary>
  return <Wizard key={editId ?? 'new'} editId={editId} initial={existing.data ? fromDetail(existing.data) : blank()} metaQuery={meta} />
}

function Wizard({ editId, initial, metaQuery }: { editId: number | null; initial: StoreWrite; metaQuery: ReturnType<typeof useQuery<Awaited<ReturnType<typeof storeMeta>>>> }) {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const toast = useToast()
  const meta = metaQuery.data
  const edit = editId !== null
  const [step, setStep] = useState(0)
  const [form, setForm] = useState<StoreWrite>(initial)
  const [owner, setOwner] = useState(blankOwner)
  const [logo, setLogo] = useState<File | null>(null)
  const [banner, setBanner] = useState<File | null>(null)
  const [docs, setDocs] = useState<{ kind: string; file: File }[]>([])
  const [docKind, setDocKind] = useState('GST')
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [dirty, setDirty] = useState(false)
  const [done, setDone] = useState(false)

  useBeforeUnload(dirty && !done)
  const blocker = useBlocker(({ currentLocation, nextLocation }) => dirty && !done && currentLocation.pathname !== nextLocation.pathname)
  const patch = (changes: Partial<StoreWrite>) => { setForm((f) => ({ ...f, ...changes })); setDirty(true) }
  const patchAddr = (changes: Partial<StoreWrite['address']>) => { setForm((f) => ({ ...f, address: { ...f.address, ...changes } })); setDirty(true) }
  const patchOwner = (changes: Partial<typeof owner>) => { setOwner((o) => ({ ...o, ...changes })); setDirty(true) }

  const save = useMutation({
    mutationFn: async (draft: boolean) => {
      if (edit) { await updateStore(editId, payload(form, null, false, true) as Partial<StoreWrite>); return { id: editId, status: '', missing: [] as string[], store_code: '' } }
      const created = await createStore(payload(form, owner, draft, false) as unknown as StoreWrite)
      const problems: string[] = []
      if (logo || banner) await uploadStoreImages(created.id, { image: logo, banner }).catch((e) => problems.push(`Images: ${errorMessage(e)}`))
      for (const doc of docs) await uploadStoreDocument(created.id, doc.kind, doc.file).catch((e) => problems.push(`${doc.file.name}: ${errorMessage(e)}`))
      return { ...created, problems }
    },
    onSuccess: (result) => {
      setDone(true)
      void qc.invalidateQueries({ queryKey: ['admin-stores'] }); void qc.invalidateQueries({ queryKey: ['admin-counts'] })
      const problems = (result as { problems?: string[] }).problems ?? []
      toast(problems.length ? 'error' : 'success', edit ? 'Store updated.' : `Store saved as ${String(result.status).toLowerCase().replace('_', ' ')}.${problems.length ? ` Some files were not uploaded: ${problems.join('; ')}` : ''}`)
      navigate(`/admin/stores/${result.id}`)
    },
    onError: (error) => { setErrors(fieldErrors(error)); window.scrollTo({ top: 0 }) },
  })

  const err = (key: string) => flatten(errors, key)
  const gaps = [
    !form.name.trim() && 'Store name', form.category === '' && 'Category', !form.contact_phone.trim() && 'Contact phone', !form.address.line1.trim() && 'Address line 1',
    !form.address.city.trim() && 'City', !form.address.state.trim() && 'State', !form.address.postal_code.trim() && 'Postal code',
    (!form.address.latitude || !form.address.longitude) && 'Map location', !(form.offers_delivery || form.offers_pickup) && 'Delivery or pickup',
    !edit && !owner.username && 'Owner account',
  ].filter(Boolean) as string[]
  const opsGaps = [!Object.values(form.opening_hours).some((s) => s.length) && 'Opening hours', form.offers_delivery && !form.service_radius_km && 'Delivery service radius'].filter(Boolean) as string[]
  const canSubmit = Boolean(form.name.trim() && form.category !== '')
  const setDay = (day: string, slot: { open: string; close: string } | null) => patch({ opening_hours: { ...form.opening_hours, [day]: slot ? [slot] : [] } as Hours })
  const errorList = Object.entries(errors)

  const stepBody = [
    <Grid key="0">
      <Field label="Store name" required error={err('name')} className="sm:col-span-2">{(p) => <Input {...p} value={form.name} maxLength={200} onChange={(e) => patch({ name: e.target.value })} />}</Field>
      <Field label="Store type" required error={err('store_type')}>{(p) => <Select {...p} value={form.store_type} onChange={(e) => patch({ store_type: e.target.value })}>{meta?.types.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}</Select>}</Field>
      <Field label="Category" required error={err('category')}>{(p) => <Select {...p} value={form.category} onChange={(e) => patch({ category: e.target.value ? Number(e.target.value) : '' })}><option value="">Choose a category</option>{meta?.categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</Select>}</Field>
      <Field label="Contact phone" required error={err('contact_phone')}>{(p) => <Input {...p} type="tel" value={form.contact_phone} onChange={(e) => patch({ contact_phone: e.target.value })} />}</Field>
      <Field label="Alternative phone" error={err('alternative_phone')}>{(p) => <Input {...p} type="tel" value={form.alternative_phone} onChange={(e) => patch({ alternative_phone: e.target.value })} />}</Field>
      <Field label="Email" error={err('email')} className="sm:col-span-2">{(p) => <Input {...p} type="email" value={form.email} onChange={(e) => patch({ email: e.target.value })} />}</Field>
      <Field label="Description" className="sm:col-span-2" hint="Shown to customers on the store page.">{(p) => <Textarea {...p} rows={3} value={form.description} onChange={(e) => patch({ description: e.target.value })} />}</Field>
      {!edit && <>
        <FilePicker label="Logo" file={logo} onFile={(f) => { setLogo(f); setDirty(true) }} error={err('image')} />
        <FilePicker label="Banner" file={banner} onFile={(f) => { setBanner(f); setDirty(true) }} error={err('banner')} />
      </>}
      <p className="text-sm text-muted sm:col-span-2">The store link (slug) is created from the name automatically and kept unique.</p>
    </Grid>,
    <Grid key="1">
      <Field label="Address line 1" required error={err('line1')} className="sm:col-span-2">{(p) => <Input {...p} value={form.address.line1} onChange={(e) => patchAddr({ line1: e.target.value })} />}</Field>
      <Field label="Address line 2" error={err('line2')}>{(p) => <Input {...p} value={form.address.line2} onChange={(e) => patchAddr({ line2: e.target.value })} />}</Field>
      <Field label="Landmark" error={err('landmark')}>{(p) => <Input {...p} value={form.address.landmark} onChange={(e) => patchAddr({ landmark: e.target.value })} />}</Field>
      <Field label="City" required error={err('city')}>{(p) => <Input {...p} value={form.address.city} onChange={(e) => patchAddr({ city: e.target.value })} />}</Field>
      <Field label="District" error={err('district')}>{(p) => <Input {...p} value={form.address.district} onChange={(e) => patchAddr({ district: e.target.value })} />}</Field>
      <Field label="State" required error={err('state')}>{(p) => <Input {...p} value={form.address.state} onChange={(e) => patchAddr({ state: e.target.value })} />}</Field>
      <Field label="Postal code" required error={err('postal_code')}>{(p) => <Input {...p} inputMode="numeric" value={form.address.postal_code} onChange={(e) => patchAddr({ postal_code: e.target.value })} />}</Field>
      <Field label="Latitude" required error={err('latitude')} hint="Decimal degrees, e.g. 9.931233. Entered by hand; nothing is looked up for you.">{(p) => <Input {...p} inputMode="decimal" value={form.address.latitude} onChange={(e) => patchAddr({ latitude: e.target.value })} />}</Field>
      <Field label="Longitude" required error={err('longitude')} hint="Decimal degrees, e.g. 76.267303.">{(p) => <Input {...p} inputMode="decimal" value={form.address.longitude} onChange={(e) => patchAddr({ longitude: e.target.value })} />}</Field>
      <fieldset className="sm:col-span-2"><legend className="mb-1 text-sm font-medium">How customers receive orders</legend>
        <div className="flex flex-wrap gap-6">
          <label className="flex min-h-11 items-center gap-2 text-sm"><input type="checkbox" className="size-4 accent-forest" checked={form.offers_delivery} onChange={(e) => patch({ offers_delivery: e.target.checked })} />Delivery</label>
          <label className="flex min-h-11 items-center gap-2 text-sm"><input type="checkbox" className="size-4 accent-forest" checked={form.offers_pickup} onChange={(e) => patch({ offers_pickup: e.target.checked })} />Pickup</label>
        </div>
      </fieldset>
      <Field label="Delivery radius (km)" error={err('service_radius_km')} hint="Orders beyond this distance are not accepted. Required to take delivery orders.">{(p) => <Input {...p} inputMode="decimal" value={form.service_radius_km} onChange={(e) => patch({ service_radius_km: e.target.value })} />}</Field>
    </Grid>,
    <div key="2" className="space-y-4">
      <Grid>
        <Field label="Registered business name" error={err('business_name')}>{(p) => <Input {...p} value={form.business_name} onChange={(e) => patch({ business_name: e.target.value })} />}</Field>
        <Field label="GSTIN" error={err('gstin')} hint="15 characters. Entering it does not verify the store.">{(p) => <Input {...p} value={form.gstin} maxLength={15} className="uppercase" onChange={(e) => patch({ gstin: e.target.value.toUpperCase() })} />}</Field>
      </Grid>
      {edit ? <Alert tone="info">Upload and review documents from the store’s Documents tab.</Alert> : (
        <div>
          <Alert tone="info" title="Verification is separate">Documents are stored for review. A store is only marked verified when someone with approval rights verifies it.</Alert>
          <div className="mt-3 flex flex-wrap items-end gap-3">
            <Field label="Document type">{(p) => <Select {...p} value={docKind} onChange={(e) => setDocKind(e.target.value)}>{DOC_KINDS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</Select>}</Field>
            <FilePicker label="File (PDF or image, up to 8 MB)" accept="application/pdf,image/jpeg,image/png,image/webp" maxBytes={8 * 1024 * 1024} file={null} hint="PDF, JPG, PNG or WebP" onFile={(f) => { if (f) { setDocs((d) => [...d, { kind: docKind, file: f }]); setDirty(true) } }} />
          </div>
          {docs.length > 0 && <ul className="mt-3 space-y-1 text-sm">{docs.map((d, i) => <li key={i} className="flex items-center justify-between gap-2 rounded-control bg-canvas px-3 py-1"><span>{DOC_KINDS.find(([v]) => v === d.kind)?.[1]} · {d.file.name}</span><Button size="sm" variant="ghost" onClick={() => setDocs((all) => all.filter((_, j) => j !== i))}>Remove</Button></li>)}</ul>}
        </div>
      )}
    </div>,
    <div key="3" className="space-y-5">
      <fieldset><legend className="mb-2 text-sm font-medium">Weekly opening hours</legend>
        <ul className="space-y-2">
          {(meta?.days ?? Object.keys(DAY_LABEL)).map((day) => {
            const slot = form.opening_hours[day]?.[0]
            return (
              <li key={day} className="flex flex-wrap items-center gap-3">
                <label className="flex min-h-11 w-36 items-center gap-2 text-sm"><input type="checkbox" className="size-4 accent-forest" checked={Boolean(slot)} onChange={(e) => setDay(day, e.target.checked ? { open: '09:00', close: '21:00' } : null)} />{DAY_LABEL[day]}</label>
                {slot ? <>
                  <Input aria-label={`${DAY_LABEL[day]} opens`} type="time" className="!w-32" value={slot.open} onChange={(e) => setDay(day, { ...slot, open: e.target.value })} />
                  <span aria-hidden="true">to</span>
                  <Input aria-label={`${DAY_LABEL[day]} closes`} type="time" className="!w-32" value={slot.close} onChange={(e) => setDay(day, { ...slot, close: e.target.value })} />
                </> : <span className="text-sm text-muted">Closed</span>}
              </li>
            )
          })}
        </ul>
        <Button className="mt-2" size="sm" variant="outline" disabled={!form.opening_hours.mon?.[0]} onClick={() => patch({ opening_hours: Object.fromEntries(Object.keys(DAY_LABEL).map((d) => [d, form.opening_hours.mon ?? []])) })}>Copy Monday to all days</Button>
        {err('opening_hours') && <p role="alert" className="mt-2 text-sm text-danger">{err('opening_hours')}</p>}
      </fieldset>
      <Grid>
        <Field label="Minimum order amount (₹)" error={err('min_order_amount')} hint="Leave empty for no minimum.">{(p) => <Input {...p} inputMode="decimal" value={form.min_order_amount} onChange={(e) => patch({ min_order_amount: e.target.value })} />}</Field>
        <label className="flex min-h-11 items-center gap-2 self-end text-sm"><input type="checkbox" className="size-4 accent-forest" checked={form.accepts_orders} onChange={(e) => patch({ accepts_orders: e.target.checked })} />Accepting orders</label>
      </Grid>
    </div>,
    edit ? <Alert key="4" tone="info">Owner and staff accounts are managed from the store’s Owner &amp; Staff tab.</Alert> : (
      <div key="4" className="space-y-4">
        <Alert tone="info">The owner gets a store-portal account. Choose a strong temporary password and share it securely; it is never shown again.</Alert>
        <Grid>
          <Field label="Username" error={err('username')}>{(p) => <Input {...p} autoComplete="off" value={owner.username} onChange={(e) => patchOwner({ username: e.target.value })} />}</Field>
          <Field label="Email" error={err('email')}>{(p) => <Input {...p} type="email" autoComplete="off" value={owner.email} onChange={(e) => patchOwner({ email: e.target.value })} />}</Field>
          <Field label="First name">{(p) => <Input {...p} value={owner.first_name} onChange={(e) => patchOwner({ first_name: e.target.value })} />}</Field>
          <Field label="Last name">{(p) => <Input {...p} value={owner.last_name} onChange={(e) => patchOwner({ last_name: e.target.value })} />}</Field>
          <Field label="Phone" error={err('phone_number')}>{(p) => <Input {...p} type="tel" value={owner.phone_number} onChange={(e) => patchOwner({ phone_number: e.target.value })} />}</Field>
          <Field label="Temporary password" error={err('owner_password') ?? err('password')} hint="At least 8 characters, not common or numeric only.">{(p) => <Input {...p} type="password" autoComplete="new-password" value={owner.password} onChange={(e) => patchOwner({ password: e.target.value })} />}</Field>
        </Grid>
        <p className="text-sm text-muted">Skip this step to create the store without an owner; it will be marked “needs information” until an owner is added.</p>
      </div>
    ),
    <div key="5" className="space-y-4">
      <Field label="Commission (%)" error={err('commission_percentage')} hint={meta?.can_approve ? 'Applied to this store’s orders. Taxes and payouts are not configured here.' : 'Only people who can approve stores can set commercial terms. It starts at 0.'}>
        {(p) => <Input {...p} inputMode="decimal" disabled={!meta?.can_approve} value={form.commission_percentage} onChange={(e) => patch({ commission_percentage: e.target.value })} />}
      </Field>
      <div className="rounded-control bg-canvas p-4 text-sm">
        <h3 className="font-semibold text-forest">What will happen</h3>
        {gaps.length ? <p className="mt-1">Still needed before approval: <b>{gaps.join(', ')}</b>. You can save it now; it will be kept as “needs information” or as a draft.</p>
          : <p className="mt-1">{meta?.can_approve ? 'Everything required is filled in. Saving will approve this store.' : 'Everything required is filled in. Saving will send it for approval.'}</p>}
        {opsGaps.length > 0 && <p className="mt-2 text-warn">It will not take orders until you add: {opsGaps.join(', ')}.</p>}
        <p className="mt-2 text-muted">Verification stays “unverified” until it is explicitly verified.</p>
      </div>
    </div>,
  ]
  const last = step === STEPS.length - 1
  const visibleSteps = STEPS.map((label, i) => ({ label, i }))

  return (
    <>
      <PageHeader title={edit ? `Edit ${initial.name}` : 'Add store'} subtitle={edit ? 'Changes are saved together and recorded in the audit log.' : 'Fill in what you have. You can save a draft at any step.'} />
      {errorList.length > 0 && <div className="mb-4"><Alert tone="error" title="Please fix these before saving">
        <ul className="list-disc pl-5">{errorList.map(([k, v]) => <li key={k}>{k.replace(/_/g, ' ')}: {v}</li>)}</ul></Alert></div>}
      <nav aria-label="Steps" className="mb-5"><ol className="flex gap-1 overflow-x-auto">
        {visibleSteps.filter(({ i }) => !(edit && i === 4)).map(({ label, i }) => (
          <li key={label}><button type="button" aria-current={step === i ? 'step' : undefined} onClick={() => setStep(i)}
            className={`flex min-h-11 items-center gap-2 whitespace-nowrap rounded-control px-3 text-sm font-medium ${step === i ? 'bg-forest text-white' : 'text-forest ring-1 ring-inset ring-line hover:bg-pale'}`}>
            <span className={`grid size-5 place-items-center rounded-full text-xs ${step === i ? 'bg-white/20' : 'bg-pale'}`}>{i < step ? <Check className="size-3" aria-hidden="true" /> : i + 1}</span>{label}</button></li>
        ))}
      </ol></nav>
      <Card className="p-4 sm:p-6">
        <h2 className="mb-4 text-lg font-semibold text-forest">{STEPS[step]}</h2>
        {stepBody[step]}
      </Card>
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <Button variant="ghost" onClick={() => navigate('/admin/stores')} disabled={save.isPending}>Cancel</Button>
        <span className="flex-1" />
        {step > 0 && <Button variant="outline" onClick={() => setStep(step - 1)} disabled={save.isPending}>Back</Button>}
        {!last && <Button variant="secondary" onClick={() => setStep(step + 1)}>Next</Button>}
        {!edit && <Button variant="outline" disabled={!canSubmit || save.isPending} loading={save.isPending && save.variables === true} onClick={() => { setErrors({}); save.mutate(true) }}>Save draft</Button>}
        <Button disabled={!canSubmit} loading={save.isPending && save.variables !== true} onClick={() => { setErrors({}); save.mutate(false) }}>{edit ? 'Save changes' : 'Save store'}</Button>
      </div>
      {save.isError && errorList.length === 0 && <div className="mt-3"><Alert tone="error">{errorMessage(save.error)}</Alert></div>}
      <Modal open={blocker.state === 'blocked'} onClose={() => blocker.reset?.()} title="Leave without saving?"
        footer={<><Button variant="outline" onClick={() => blocker.reset?.()}>Keep editing</Button><Button variant="destructive" onClick={() => blocker.proceed?.()}>Discard changes</Button></>}>
        <p className="text-sm">You have unsaved changes to this store. If you leave now they will be lost.</p>
      </Modal>
    </>
  )
}
