import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, ExternalLink } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Controller, useForm } from 'react-hook-form'
import { Link, useBlocker, useNavigate, useParams } from 'react-router-dom'
import { z } from 'zod'
import { ImageManager } from '@/components/ImageManager'
import { Alert, Button, Card, ErrorState, Field, Input, PageHeader, Select, Spinner, StatusBadge, Textarea } from '@/components/ui'
import { useAuth } from '@/features/auth/AuthProvider'
import { errorMessage, fieldErrors } from '@/lib/api'
import { formatMoney } from '@/lib/format'
import { createProduct, getMeta, getProduct, updateProduct, type ProductScope } from '@/services/products'
import type { ProductDetail, ProductWritePayload } from '@/types/api'

const decimal = (places: number, label: string) =>
  z.string().trim().regex(new RegExp(`^\\d{1,9}(\\.\\d{1,${places}})?$`), `${label} must be a number of 0 or more with at most ${places} decimals.`)

export function makeSchema(editing: boolean, needsStore = true) {
  return z
    .object({
      store: z.string(),
      name: z.string().trim().min(1, 'Enter a product name.').max(200, 'Use 200 characters or fewer.'),
      sku: z.string().trim().min(1, 'Enter a SKU.').max(64, 'Use 64 characters or fewer.'),
      category: z.string().min(1, 'Choose a category.'),
      brand: z.string(),
      tags: z.array(z.string()),
      description: z.string(),
      unit: z.string().min(1),
      unit_value: decimal(3, 'Unit value'),
      low_stock_threshold: decimal(3, 'Low-stock level'),
      store_price: decimal(2, 'Store price'),
      manufacturing_date: z.string(),
      expiry_date: z.string(),
      is_active: z.boolean(),
      is_featured: z.boolean(),
      save_as_draft: z.boolean(),
    })
    .superRefine((value, ctx) => {
      if (!editing && needsStore && !value.store) ctx.addIssue({ code: 'custom', path: ['store'], message: 'Choose the store this product belongs to.' })
      if (value.manufacturing_date && value.expiry_date && value.expiry_date < value.manufacturing_date) {
        ctx.addIssue({ code: 'custom', path: ['expiry_date'], message: 'Expiry must be on or after the manufacturing date.' })
      }
    })
}
export type FormValues = z.infer<ReturnType<typeof makeSchema>>

const EMPTY: FormValues = {
  store: '', name: '', sku: '', category: '', brand: '', tags: [], description: '', unit: 'PIECE', unit_value: '1',
  low_stock_threshold: '0', store_price: '', manufacturing_date: '', expiry_date: '', is_active: true, is_featured: false, save_as_draft: true,
}

function toFormValues(product: ProductDetail): FormValues {
  return {
    store: String(product.store.id), name: product.name, sku: product.sku, category: String(product.category.id),
    brand: product.brand ? String(product.brand.id) : '', tags: product.tags.map((t) => String(t.id)), description: product.description,
    unit: product.unit, unit_value: product.unit_value, low_stock_threshold: product.low_stock_threshold, store_price: product.store_price,
    manufacturing_date: product.manufacturing_date ?? '', expiry_date: product.expiry_date ?? '', is_active: product.is_active,
    is_featured: product.is_featured, save_as_draft: true,
  }
}

function toPayload(values: FormValues, editing: boolean, canFeature: boolean, scope: ProductScope): ProductWritePayload {
  return {
    ...(editing ? {} : { ...(scope === 'admin' ? { store: Number(values.store) } : {}), save_as_draft: values.save_as_draft }),
    name: values.name.trim(), sku: values.sku.trim(), category: Number(values.category), brand: values.brand ? Number(values.brand) : null,
    tags: values.tags.map(Number), description: values.description, unit: values.unit, unit_value: values.unit_value,
    low_stock_threshold: values.low_stock_threshold, store_price: values.store_price,
    manufacturing_date: values.manufacturing_date || null, expiry_date: values.expiry_date || null, is_active: values.is_active,
    ...(canFeature ? { is_featured: values.is_featured } : {}),
  }
}

export default function ProductFormPage({ scope = 'admin' }: { scope?: ProductScope }) {
  const base = scope === 'store' ? '/store/products' : '/admin/products'
  const params = useParams()
  const id = params.id ? Number(params.id) : null
  const editing = id !== null
  const { user } = useAuth()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [serverError, setServerError] = useState('')

  const meta = useQuery({ queryKey: ['meta', scope], queryFn: () => getMeta(scope), staleTime: 5 * 60_000 })
  const product = useQuery({ queryKey: ['product', scope, id], queryFn: () => getProduct(id as number, scope), enabled: editing })
  const schema = useMemo(() => makeSchema(editing, scope === 'admin'), [editing, scope])
  const canChange = scope === 'store' ? Boolean(meta.data?.can.change) : Boolean(user?.permissions.change)

  const { register, control, handleSubmit, reset, setError, formState: { errors, isDirty, isSubmitting, isSubmitSuccessful } } = useForm<FormValues>({
    resolver: zodResolver(schema), defaultValues: EMPTY,
  })
  useEffect(() => { if (product.data) reset(toFormValues(product.data)) }, [product.data, reset])

  // Unsaved-work protection: in-app navigation and tab close/refresh.
  const dirty = isDirty && !isSubmitSuccessful
  // Set just before we navigate after a successful save.
  const savedRef = useRef(false)
  const blocker = useBlocker(({ currentLocation, nextLocation }) => dirty && currentLocation.pathname !== nextLocation.pathname)
  // Our own post-save redirect is not "leaving with unsaved work": let it through.
  useEffect(() => { if (blocker.state === 'blocked' && savedRef.current) blocker.proceed() }, [blocker])
  useEffect(() => {
    if (!dirty) return
    const handler = (event: BeforeUnloadEvent) => { event.preventDefault() }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [dirty])

  const save = useMutation({
    mutationFn: (values: FormValues) => {
      const payload = toPayload(values, editing, canChange && scope === 'admin', scope)
      return editing ? updateProduct(id, payload, scope) : createProduct(payload as ProductWritePayload, scope)
    },
  })

  // The ref is only written in the submit handler (an event), never while rendering.
  // eslint-disable-next-line react-hooks/refs
  const onSubmit = handleSubmit(async (values) => {
    setServerError('')
    try {
      const saved = await save.mutateAsync(values)
      await queryClient.invalidateQueries({ queryKey: ['products'] })
      queryClient.setQueryData(['product', scope, saved.id], saved)
      reset(toFormValues(saved))
      savedRef.current = true
      navigate(editing ? base : `${base}/${saved.id}`, { replace: !editing })
    } catch (error) {
      savedRef.current = false
      const fields = fieldErrors(error)
      const known = Object.keys(EMPTY)
      let placed = false
      for (const [field, message] of Object.entries(fields)) {
        if (known.includes(field)) { setError(field as keyof FormValues, { message }); placed = true }
      }
      if (!placed || fields.non_field_errors) setServerError(errorMessage(error))
    }
  })

  if (editing && product.isPending) return <Spinner label="Loading product…" />
  if (editing && product.isError) return <ErrorState message={errorMessage(product.error, 'This product could not be loaded.')} onRetry={() => void product.refetch()} />
  if (meta.isPending) return <Spinner />
  if (meta.isError) return <ErrorState message="Form options could not be loaded." onRetry={() => void meta.refetch()} />

  const m = meta.data
  const p = product.data
  const readOnly = editing && !canChange

  return (
    <>
      <Link to={base} className="mb-3 inline-flex min-h-11 items-center gap-1.5 text-sm font-medium text-forest hover:underline"><ArrowLeft className="size-4" aria-hidden="true" /> Products</Link>
      <PageHeader
        title={editing ? (p?.name ?? 'Edit product') : 'New product'}
        subtitle={editing ? `${p?.product_code} · ${p?.store.name}` : 'Add the basics now; photos come right after you save.'}
        actions={p && <StatusBadge status={p.status} />}
      />

      {blocker.state === 'blocked' && (
        <div className="mb-4">
          <Alert tone="warn" title="You have unsaved changes">
            <div className="mt-2 flex gap-2">
              <Button variant="danger" className="min-h-9" onClick={() => blocker.proceed()}>Leave without saving</Button>
              <Button variant="secondary" className="min-h-9" onClick={() => blocker.reset()}>Keep editing</Button>
            </div>
          </Alert>
        </div>
      )}

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <form onSubmit={(event) => void onSubmit(event)} noValidate className="space-y-6">
          {serverError && <Alert tone="error">{serverError}</Alert>}
          {p?.status === 'REJECTED' && p.rejection_reason && <Alert tone="warn" title="Rejected">{p.rejection_reason}</Alert>}

          <Card className="space-y-4 p-4 sm:p-6">
            <h2 className="text-lg font-semibold text-forest">Details</h2>
            <fieldset disabled={readOnly} className="grid gap-4 sm:grid-cols-2">
              {!editing && scope === 'admin' && (
                <Field label="Store" required error={errors.store?.message} className="sm:col-span-2">
                  {(props) => (
                    <Select {...props} {...register('store')}>
                      <option value="">Choose a store…</option>
                      {m.stores.map((s) => <option key={s.id} value={s.id}>{s.name} ({s.store_code})</option>)}
                    </Select>
                  )}
                </Field>
              )}
              <Field label="Name" required error={errors.name?.message} className="sm:col-span-2">{(props) => <Input {...props} {...register('name')} />}</Field>
              <Field label="SKU" required error={errors.sku?.message} hint="Unique within the store.">{(props) => <Input {...props} {...register('sku')} />}</Field>
              <Field label="Store price (₹)" required error={errors.store_price?.message} hint="Selling price and margin are set by management.">
                {(props) => <Input {...props} inputMode="decimal" {...register('store_price')} />}
              </Field>
              <Field label="Category" required error={errors.category?.message}>
                {(props) => (
                  <Select {...props} {...register('category')}>
                    <option value="">Choose a category…</option>
                    {m.categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                  </Select>
                )}
              </Field>
              <Field label="Brand" error={errors.brand?.message}>
                {(props) => (
                  <Select {...props} {...register('brand')}>
                    <option value="">No brand</option>
                    {m.brands.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
                  </Select>
                )}
              </Field>
              <Field label="Unit" error={errors.unit?.message}>
                {(props) => <Select {...props} {...register('unit')}>{m.units.map((u) => <option key={u.value} value={u.value}>{u.label}</option>)}</Select>}
              </Field>
              <Field label="Amount per unit" error={errors.unit_value?.message} hint="e.g. 500 for 500 ml.">{(props) => <Input {...props} inputMode="decimal" {...register('unit_value')} />}</Field>
              <Field label="Low-stock level" error={errors.low_stock_threshold?.message}>{(props) => <Input {...props} inputMode="decimal" {...register('low_stock_threshold')} />}</Field>
              <Field label="Manufactured" error={errors.manufacturing_date?.message}>{(props) => <Input {...props} type="date" {...register('manufacturing_date')} />}</Field>
              <Field label="Expires" error={errors.expiry_date?.message}>{(props) => <Input {...props} type="date" {...register('expiry_date')} />}</Field>
              <Field label="Description" error={errors.description?.message} className="sm:col-span-2">{(props) => <Textarea {...props} rows={4} {...register('description')} />}</Field>
              {m.tags.length > 0 && (
                <div className="sm:col-span-2">
                  <p className="mb-1 text-sm font-medium">Tags</p>
                  <Controller control={control} name="tags" render={({ field }) => (
                    <div className="flex flex-wrap gap-2">
                      {m.tags.map((tag) => {
                        const value = String(tag.id)
                        const on = field.value.includes(value)
                        return (
                          <label key={tag.id} className={`inline-flex min-h-11 cursor-pointer items-center gap-2 rounded-full px-3 text-sm ring-1 ring-inset has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-emerald ${on ? 'bg-mint text-deep ring-emerald/40' : 'bg-white ring-line'}`}>
                            <input type="checkbox" className="sr-only" checked={on} onChange={() => field.onChange(on ? field.value.filter((v) => v !== value) : [...field.value, value])} />
                            {tag.name}
                          </label>
                        )
                      })}
                    </div>
                  )} />
                </div>
              )}
              <label className="flex min-h-11 items-center gap-2 text-sm"><input type="checkbox" className="size-4 accent-forest" {...register('is_active')} /> Active (can be sold when approved)</label>
              {canChange && scope === 'admin' && <label className="flex min-h-11 items-center gap-2 text-sm"><input type="checkbox" className="size-4 accent-forest" {...register('is_featured')} /> Featured</label>}
              {!editing && <label className="flex min-h-11 items-center gap-2 text-sm sm:col-span-2"><input type="checkbox" className="size-4 accent-forest" {...register('save_as_draft')} /> Save as draft (otherwise it is submitted for review)</label>}
            </fieldset>
          </Card>

          {!readOnly && (
            <div className="sticky bottom-0 -mx-4 flex flex-wrap items-center gap-3 border-t border-line bg-canvas/95 px-4 py-3 backdrop-blur sm:mx-0 sm:rounded-card sm:border">
              <Button type="submit" loading={isSubmitting || save.isPending}>{editing ? 'Save changes' : 'Create product'}</Button>
              <Link to={base}><Button variant="ghost">Cancel</Button></Link>
              {dirty && <span className="text-sm text-muted">Unsaved changes</span>}
            </div>
          )}
        </form>

        <div className="space-y-6">
          {editing && p ? (
            <>
              <Card className="space-y-3 p-4 sm:p-6">
                <h2 className="text-lg font-semibold text-forest">Pricing &amp; stock</h2>
                <dl className="grid grid-cols-2 gap-y-2 text-sm">
                  <dt className="text-muted">Store price</dt><dd className="text-right tabular-nums">{formatMoney(p.store_price)}</dd>
                  <dt className="text-muted">Selling price</dt><dd className="text-right tabular-nums">{formatMoney(p.selling_price)}</dd>
                  <dt className="text-muted">Final price</dt><dd className="text-right font-semibold tabular-nums">{formatMoney(p.final_price)}</dd>
                  <dt className="text-muted">In stock</dt><dd className="text-right tabular-nums">{p.stock_quantity}</dd>
                </dl>
                <p className="text-xs text-muted">{scope === 'store' ? 'Your selling price is set by Zuuvi management after approval. Change stock from the Stock page.' : 'Margin, discount and approval are managed by the admin catalogue workflow.'}</p>
                {scope === 'store' && <Link to="/store/stock" className="inline-flex min-h-11 items-center gap-1.5 text-sm font-medium text-forest hover:underline">Go to stock <ExternalLink className="size-4" aria-hidden="true" /></Link>}
              </Card>
            </>
          ) : (
            <Card className="p-4 sm:p-6"><p className="text-sm text-muted">After you create the product you can add photos, and management can set the margin and approve it.</p></Card>
          )}
        </div>
      </div>

      {editing && p && <div className="mt-6"><ImageManager product={p} canChange={canChange} maxImages={m.max_images} scope={scope} /></div>}
    </>
  )
}
