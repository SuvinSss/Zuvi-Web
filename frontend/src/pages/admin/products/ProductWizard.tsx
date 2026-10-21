import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, ChevronDown } from 'lucide-react'
import { useRef, useState, type ReactNode } from 'react'
import { useBlocker, useNavigate } from 'react-router-dom'
import { FilePicker, Modal, useToast } from '@/components/kit'
import { useBeforeUnload } from '@/components/management'
import { Alert, Button, ButtonLink, Card, Field, Input, PageHeader, Select, Spinner, Textarea } from '@/components/ui'
import { useDebounced } from '@/hooks/useDebounced'
import { errorMessage, fieldErrors } from '@/lib/api'
import { formatMoney } from '@/lib/format'
import { changeProductStatus, pricingPreview, setPricing } from '@/services/management'
import { createProduct, getMeta, uploadImage } from '@/services/products'
import type { PriceBreakdown, ProductWritePayload } from '@/types/api'

const STEPS = ['Product', 'Stock', 'Price', 'Offer', 'Review'] as const
const MONEY = /^\d{1,9}(\.\d{1,2})?$/
const QTY = /^\d{1,9}(\.\d{1,3})?$/
type Finish = 'draft' | 'submit' | 'approve'

const blank = {
  store: '', name: '', category: '', description: '', sku: '', brand: '', unit: 'PIECE', unit_value: '1',
  opening_stock: '', low_stock_threshold: '0', manufacturing_date: '', expiry_date: '',
  store_price: '', selling_price: '', target_margin: '',
  discount_type: '', discount_value: '', discount_starts_at: '', discount_ends_at: '',
}
type Form = typeof blank

export const autoSku = (name: string) => `AUTO-${name.toUpperCase().replace(/[^A-Z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 40)}`
const iso = (local: string) => (local ? new Date(local).toISOString() : null)

function Row({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return <div className="flex items-baseline justify-between gap-3 py-1.5"><dt className="text-sm text-muted">{label}{hint && <span className="block text-xs">{hint}</span>}</dt><dd className="text-right text-sm tabular-nums">{value}</dd></div>
}

/** Guided creation for management: details → stock → price → offer → review, then draft, submit or approve. */
export default function ProductWizard() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const toast = useToast()
  const meta = useQuery({ queryKey: ['meta', 'admin'], queryFn: () => getMeta('admin'), staleTime: 5 * 60_000 })
  const can = meta.data?.can
  const [step, setStep] = useState(0)
  const [f, setF] = useState<Form>(blank)
  const [photo, setPhoto] = useState<File | null>(null)
  const [skuAuto, setSkuAuto] = useState(true)
  const [advanced, setAdvanced] = useState(false)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState<Finish | null>(null)
  const [partial, setPartial] = useState<{ id: number; problem: string } | null>(null)
  const [dirty, setDirty] = useState(false)
  const [done, setDone] = useState(false)
  useBeforeUnload(dirty && !done)
  // A ref, not state: the post-save navigate() runs before React re-renders with done=true.
  const doneRef = useRef(false)
  const blocker = useBlocker(({ currentLocation, nextLocation }) => dirty && !doneRef.current && currentLocation.pathname !== nextLocation.pathname)

  const set = (changes: Partial<Form>) => { setF((v) => ({ ...v, ...changes })); setDirty(true) }
  const sku = skuAuto ? (f.name.trim() ? autoSku(f.name) : '') : f.sku

  // Live, server-calculated price explanation.
  const priceIn = useDebounced({ cost: f.store_price, selling: f.selling_price, dt: f.discount_type, dv: f.discount_value }, 350)
  const priceReady = Boolean(can?.pricing) && MONEY.test(priceIn.cost) && MONEY.test(priceIn.selling) && Number(priceIn.selling) > 0 && (!priceIn.dt || MONEY.test(priceIn.dv))
  const preview = useQuery({
    queryKey: ['wizard-price', priceIn], enabled: priceReady, retry: false, placeholderData: (p) => p,
    queryFn: () => pricingPreview({ cost: priceIn.cost, selling_price: priceIn.selling, discount_type: priceIn.dt, discount_value: priceIn.dt ? priceIn.dv : '' }),
  })
  const marginIn = useDebounced(f.target_margin, 350)
  const suggestion = useQuery({
    queryKey: ['wizard-suggest', f.store_price, marginIn], retry: false,
    enabled: Boolean(can?.pricing) && MONEY.test(f.store_price) && Number(f.store_price) > 0 && marginIn.trim() !== '',
    queryFn: () => pricingPreview({ cost: f.store_price, target_margin: marginIn }),
  })
  const b = priceReady ? preview.data?.breakdown : undefined

  // What stops each finishing action, in plain words.
  const basics = [!f.store && 'Store', !f.name.trim() && 'Product name', !f.category && 'Category', !sku && 'SKU', !MONEY.test(f.store_price) && 'Store price'].filter(Boolean) as string[]
  const stockError = f.opening_stock && !QTY.test(f.opening_stock) ? 'Enter a quantity of 0 or more.' : ''
  const priceSet = Boolean(can?.pricing && MONEY.test(f.selling_price) && Number(f.selling_price) > 0)
  const offerError = f.discount_starts_at && f.discount_ends_at && f.discount_ends_at <= f.discount_starts_at ? 'The offer must end after it starts.' : ''
  const approveBlockers = [...basics, !photo && 'Photo', !priceSet && 'Selling price', b?.below_cost && 'Price above store price'].filter(Boolean) as string[]

  const finish = async (mode: Finish) => {
    setBusy(mode); setErrors({}); setPartial(null)
    let id: number | null = null
    try {
      const payload = {
        store: Number(f.store), name: f.name.trim(), sku, category: Number(f.category), brand: f.brand ? Number(f.brand) : null, tags: [],
        description: f.description, unit: f.unit, unit_value: f.unit_value, low_stock_threshold: f.low_stock_threshold || '0',
        manufacturing_date: f.manufacturing_date || null, expiry_date: f.expiry_date || null, store_price: f.store_price, is_active: true,
        save_as_draft: true, ...(f.opening_stock && can?.stock ? { opening_stock: f.opening_stock } : {}),
      } as ProductWritePayload
      const created = await createProduct(payload, 'admin')
      id = created.id
      if (photo) await uploadImage(id, photo, f.name.trim(), true, 'admin')
      if (priceSet) {
        await setPricing(id, {
          selling_price: f.selling_price, discount_type: f.discount_type, discount_value: f.discount_type ? f.discount_value : '',
          discount_starts_at: f.discount_type ? iso(f.discount_starts_at) : null, discount_ends_at: f.discount_type ? iso(f.discount_ends_at) : null,
          reason: 'Set when the product was created',
        })
      }
      if (mode !== 'draft') await changeProductStatus(id, 'PENDING', 'Submitted when created')
      if (mode === 'approve') await changeProductStatus(id, 'APPROVED', 'Approved when created')
      doneRef.current = true; setDone(true)
      void qc.invalidateQueries({ queryKey: ['products'] }); void qc.invalidateQueries({ queryKey: ['admin-counts'] })
      toast('success', mode === 'approve' ? 'Product created and approved.' : mode === 'submit' ? 'Product created and sent for approval.' : 'Product saved as a draft.')
      navigate(`/admin/products/${id}`)
    } catch (error) {
      if (id === null) {
        const fe = fieldErrors(error)
        setErrors(fe)
        const back = ['name', 'store', 'category', 'sku', 'brand', 'unit', 'unit_value', 'description'].some((k) => fe[k]) ? 0
          : ['opening_stock', 'low_stock_threshold', 'expiry_date', 'manufacturing_date'].some((k) => fe[k]) ? 1 : fe.store_price ? 2 : step
        setStep(back)
        if (!Object.keys(fe).length) setErrors({ detail: errorMessage(error) })
      } else {
        doneRef.current = true; setDone(true)  // the product exists; do not create a second one on retry
        setPartial({ id, problem: errorMessage(error) })
      }
    } finally { setBusy(null) }
  }

  if (meta.isPending) return <Spinner />
  const m = meta.data
  if (!m) return <Alert tone="error">Could not load the form. Reload the page.</Alert>
  const err = (k: string) => errors[k]

  const panels: ReactNode[] = [
    <div key="0" className="grid gap-4 sm:grid-cols-2">
      <Field label="Product name" required error={err('name')} className="sm:col-span-2">{(p) => <Input {...p} maxLength={200} value={f.name} onChange={(e) => set({ name: e.target.value })} />}</Field>
      <Field label="Store" required error={err('store')}>{(p) => <Select {...p} value={f.store} onChange={(e) => set({ store: e.target.value })}><option value="">Choose a store</option>{m.stores.map((s) => <option key={s.id} value={s.id}>{s.name} ({s.store_code})</option>)}</Select>}</Field>
      <Field label="Category" required error={err('category')}>{(p) => <Select {...p} value={f.category} onChange={(e) => set({ category: e.target.value })}><option value="">Choose a category</option>{m.categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</Select>}</Field>
      <div className="sm:col-span-2"><FilePicker label="Main photo" file={photo} onFile={(file) => { setPhoto(file); setDirty(true) }} hint="Needed before the product can be approved." /></div>
      <Field label="Short description" className="sm:col-span-2">{(p) => <Textarea {...p} rows={3} value={f.description} onChange={(e) => set({ description: e.target.value })} />}</Field>
      <Field label="Pack size" hint="e.g. 1 kg, 500 g, 6 pieces">{(p) => <div className="flex gap-2"><Input {...p} inputMode="decimal" className="w-24" value={f.unit_value} onChange={(e) => set({ unit_value: e.target.value })} /><Select aria-label="Unit" value={f.unit} onChange={(e) => set({ unit: e.target.value })}>{m.units.map((u) => <option key={u.value} value={u.value}>{u.label}</option>)}</Select></div>}</Field>
      <div className="sm:col-span-2">
        <button type="button" className="inline-flex min-h-11 items-center gap-1 text-sm font-medium text-forest" aria-expanded={advanced} onClick={() => setAdvanced((a) => !a)}>
          <ChevronDown className={`size-4 transition-transform ${advanced ? 'rotate-180' : ''}`} aria-hidden="true" />More details (SKU, brand)
        </button>
        {advanced && (
          <div className="mt-2 grid gap-4 sm:grid-cols-2">
            <Field label="SKU" error={err('sku')} hint={skuAuto ? 'Created from the name. Change it if the product already has a code.' : 'Your own code. Must be unique in the store.'}>
              {(p) => <Input {...p} value={sku} onChange={(e) => { setSkuAuto(false); set({ sku: e.target.value }) }} />}
            </Field>
            <Field label="Brand">{(p) => <Select {...p} value={f.brand} onChange={(e) => set({ brand: e.target.value })}><option value="">No brand</option>{m.brands.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</Select>}</Field>
          </div>
        )}
        {!advanced && sku && <p className="text-xs text-muted">SKU will be <span className="font-mono">{sku}</span>{skuAuto && ' (generated)'}.</p>}
      </div>
    </div>,

    <div key="1" className="grid gap-4 sm:grid-cols-2">
      {can?.stock
        ? <Field label="Stock on hand" error={err('opening_stock') || stockError} hint="Units you have now. Leave empty if you don't know yet — nothing is assumed.">{(p) => <Input {...p} inputMode="decimal" value={f.opening_stock} onChange={(e) => set({ opening_stock: e.target.value })} />}</Field>
        : <Alert tone="info">You can’t record stock. Someone with inventory rights can add it from the Stock page.</Alert>}
      <Field label="Low-stock warning at" error={err('low_stock_threshold')} hint="You’ll see a warning when stock falls to this level.">{(p) => <Input {...p} inputMode="decimal" value={f.low_stock_threshold} onChange={(e) => set({ low_stock_threshold: e.target.value })} />}</Field>
      <Field label="Manufacturing date" error={err('manufacturing_date')}>{(p) => <Input {...p} type="date" value={f.manufacturing_date} onChange={(e) => set({ manufacturing_date: e.target.value })} />}</Field>
      <Field label="Expiry date" error={err('expiry_date')}>{(p) => <Input {...p} type="date" value={f.expiry_date} onChange={(e) => set({ expiry_date: e.target.value })} />}</Field>
    </div>,

    <div key="2" className="space-y-4">
      <Field label="Store price (₹)" required error={err('store_price')} hint="What Zuuvi pays the store for one unit — your cost.">{(p) => <Input {...p} inputMode="decimal" value={f.store_price} onChange={(e) => set({ store_price: e.target.value })} />}</Field>
      {can?.pricing ? (<>
        <Field label="Selling price (₹)" hint="The regular price customers see before any offer.">{(p) => <Input {...p} inputMode="decimal" value={f.selling_price} onChange={(e) => set({ selling_price: e.target.value })} />}</Field>
        <div className="rounded-control border border-line p-3">
          <Field label="Or work it out from a target margin (%)" hint="Share of the selling price you want to keep. Below 100.">{(p) => <Input {...p} inputMode="decimal" value={f.target_margin} onChange={(e) => set({ target_margin: e.target.value })} />}</Field>
          {suggestion.data?.suggested_selling_price && <div className="mt-2 flex flex-wrap items-center gap-3 text-sm">Suggested: <strong>{formatMoney(suggestion.data.suggested_selling_price)}</strong><Button size="sm" variant="outline" onClick={() => set({ selling_price: suggestion.data!.suggested_selling_price! })}>Use this price</Button></div>}
          {suggestion.error && <p className="mt-2 text-sm text-danger" role="alert">{errorMessage(suggestion.error)}</p>}
        </div>
        <PriceSummary b={b} withOffer={false} />
      </>) : <Alert tone="info">Selling price is set by someone with pricing rights. The product can be saved and submitted without it, but not approved.</Alert>}
    </div>,

    <div key="3" className="space-y-4">
      {!can?.pricing ? <Alert tone="info">Offers are part of pricing, which you can’t change.</Alert> : !priceSet ? <Alert tone="info">Set a selling price first.</Alert> : (<>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Discount">{(p) => <Select {...p} value={f.discount_type} onChange={(e) => set({ discount_type: e.target.value, ...(e.target.value ? {} : { discount_value: '', discount_starts_at: '', discount_ends_at: '' }) })}><option value="">No offer</option><option value="PERCENTAGE">Percentage off</option><option value="FIXED">Amount off (₹)</option></Select>}</Field>
          {f.discount_type && <Field label={f.discount_type === 'PERCENTAGE' ? 'Discount (%)' : 'Discount (₹)'}>{(p) => <Input {...p} inputMode="decimal" value={f.discount_value} onChange={(e) => set({ discount_value: e.target.value })} />}</Field>}
          {f.discount_type && <>
            <Field label="Starts (optional)" hint="Empty = starts now.">{(p) => <Input {...p} type="datetime-local" value={f.discount_starts_at} onChange={(e) => set({ discount_starts_at: e.target.value })} />}</Field>
            <Field label="Ends (optional)" error={offerError || undefined} hint="Empty = until you remove it.">{(p) => <Input {...p} type="datetime-local" value={f.discount_ends_at} onChange={(e) => set({ discount_ends_at: e.target.value })} />}</Field>
          </>}
        </div>
        <p className="text-xs text-muted">Only one discount applies per product, and it is never stacked. Outside the offer dates customers pay the regular selling price; checkout always recalculates.</p>
        <PriceSummary b={b} withOffer />
      </>)}
    </div>,

    <div key="4" className="space-y-4">
      <dl className="divide-y divide-line rounded-control border border-line px-3">
        <Row label="Product" value={<>{f.name || '—'} <span className="text-muted">· {f.unit_value} {m.units.find((u) => u.value === f.unit)?.label}</span></>} />
        <Row label="Store" value={m.stores.find((s) => String(s.id) === f.store)?.name ?? '—'} />
        <Row label="Category" value={m.categories.find((c) => String(c.id) === f.category)?.name ?? '—'} />
        <Row label="SKU" value={<span className="font-mono">{sku || '—'}</span>} hint={skuAuto && sku ? 'Generated from the name' : undefined} />
        <Row label="Photo" value={photo ? photo.name : 'None'} />
        <Row label="Stock on hand" value={f.opening_stock || 'Not entered'} />
        <Row label="Store price" value={f.store_price ? formatMoney(f.store_price) : '—'} />
        {can?.pricing && <Row label="Selling price" value={priceSet ? formatMoney(f.selling_price) : 'Not set'} />}
        {b && f.discount_type && <Row label="Offer" value={`− ${formatMoney(b.discount_amount)}${f.discount_starts_at || f.discount_ends_at ? ' (scheduled)' : ''}`} />}
        {b && <Row label="Customer pays" value={<strong>{formatMoney(b.final_price)}</strong>} />}
        {b && <Row label="Estimated gross profit" value={`${formatMoney(b.profit_per_unit)} · margin ${b.margin_percent ?? '—'}%`} />}
      </dl>
      {basics.length > 0 && <Alert tone="error" title="Needed before saving">{basics.join(', ')}</Alert>}
      {basics.length === 0 && approveBlockers.length > 0 && <Alert tone="warn" title="Can be saved and submitted, but not approved yet">Missing: {approveBlockers.join(', ')}.</Alert>}
      <Alert tone="info">
        <b>Save draft</b>: only management sees it. <b>Submit for approval</b>: goes to the approval queue. {can?.approve && <><b>Save and approve</b>: becomes sellable now if everything is complete.</>} Customers can only buy approved, active products.
      </Alert>
    </div>,
  ]

  const errorList = Object.entries(errors)
  const stepBlocked = (step === 0 && (!f.name.trim() || !f.store || !f.category)) || (step === 1 && Boolean(stockError)) || (step === 3 && Boolean(offerError))

  if (partial) {
    return (
      <>
        <PageHeader title="Product saved, one step did not finish" />
        <Card className="max-w-2xl space-y-4 p-4 sm:p-6">
          <Alert tone="warn" title="Saved as a draft">{partial.problem}</Alert>
          <p className="text-sm">The product exists, so it was not created twice. Finish the remaining step on the product page.</p>
          <ButtonLink to={`/admin/products/${partial.id}`}>Open the product</ButtonLink>
        </Card>
      </>
    )
  }

  return (
    <>
      <PageHeader title="Add product" subtitle="Five short steps. Nothing is saved until you finish." />
      <ol className="mb-6 flex flex-wrap gap-2" aria-label="Steps">
        {STEPS.map((label, i) => (
          <li key={label}>
            <button type="button" onClick={() => setStep(i)} aria-current={i === step ? 'step' : undefined}
              className={`inline-flex min-h-9 items-center gap-1.5 rounded-full px-3 text-sm ${i === step ? 'bg-forest text-white' : i < step ? 'bg-mint text-deep' : 'bg-canvas text-muted ring-1 ring-line'}`}>
              {i < step ? <Check className="size-4" aria-hidden="true" /> : <span aria-hidden="true">{i + 1}</span>}{label}
            </button>
          </li>
        ))}
      </ol>
      {errorList.length > 0 && <Alert tone="error" title="Please fix these">{errorList.map(([k, v]) => <span key={k} className="block">{k === 'detail' ? v : `${k.replace(/_/g, ' ')}: ${v}`}</span>)}</Alert>}
      <Card className="mt-4 p-4 sm:p-6"><h2 className="mb-4 text-lg font-semibold text-forest">{STEPS[step]}</h2>{panels[step]}</Card>
      <div className="sticky bottom-0 mt-4 flex flex-wrap items-center gap-3 border-t border-line bg-canvas/95 py-3 backdrop-blur">
        {step > 0 && <Button variant="outline" onClick={() => setStep(step - 1)}>Back</Button>}
        {step < STEPS.length - 1 && <Button onClick={() => setStep(step + 1)} disabled={stepBlocked}>Next</Button>}
        {step === STEPS.length - 1 && <>
          <Button variant="outline" loading={busy === 'draft'} disabled={busy !== null || basics.length > 0} onClick={() => void finish('draft')}>Save draft</Button>
          <Button variant={can?.approve ? 'secondary' : 'primary'} loading={busy === 'submit'} disabled={busy !== null || basics.length > 0} onClick={() => void finish('submit')}>Submit for approval</Button>
          {can?.approve && <Button loading={busy === 'approve'} disabled={busy !== null || approveBlockers.length > 0} onClick={() => void finish('approve')}>Save and approve</Button>}
        </>}
        <ButtonLink to="/admin/products" variant="ghost">Cancel</ButtonLink>
      </div>
      <Modal open={blocker.state === 'blocked'} onClose={() => blocker.reset?.()} title="Leave without saving?"
        footer={<><Button variant="outline" onClick={() => blocker.reset?.()}>Stay</Button><Button variant="destructive" onClick={() => blocker.proceed?.()}>Leave</Button></>}>
        <p className="text-sm">The product has not been saved.</p>
      </Modal>
    </>
  )
}

function PriceSummary({ b: x, withOffer }: { b: PriceBreakdown | undefined; withOffer: boolean }) {
  if (!x) return <p className="text-sm text-muted">Enter the store price and a selling price to see the profit.</p>
  return (
    <div aria-live="polite">
      <dl className="divide-y divide-line rounded-control border border-line px-3">
        <Row label="Selling price" value={formatMoney(x.selling_price)} />
        {withOffer && <Row label="Offer discount" value={Number(x.discount_amount) ? `− ${formatMoney(x.discount_amount)}` : 'None'} />}
        <Row label={withOffer ? 'Customer pays (during the offer)' : 'Customer pays'} value={<strong>{formatMoney(x.final_price)}</strong>} />
        <Row label="Estimated gross profit per unit" hint="Customer price − store price" value={formatMoney(x.profit_per_unit)} />
        <Row label="Profit margin" hint="Profit ÷ customer price" value={x.margin_percent == null ? '—' : `${x.margin_percent}%`} />
        <Row label="Markup" hint="Profit ÷ store price" value={x.markup_percent == null ? '—' : `${x.markup_percent}%`} />
      </dl>
      <p className="mt-2 text-xs text-muted">{x.label}.</p>
      {x.warnings.map((w) => <Alert key={w} tone="warn">{w}</Alert>)}
    </div>
  )
}
