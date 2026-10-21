import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Alert, Button, Card, Field, Input, Select } from '@/components/ui'
import { useToast } from '@/components/kit'
import { useDebounced } from '@/hooks/useDebounced'
import { errorMessage, fieldErrors } from '@/lib/api'
import { formatMoney } from '@/lib/format'
import { pricingPreview, setPricing } from '@/services/management'
import type { ProductDetail } from '@/types/api'

const num = (v: string) => v.trim() !== '' && Number.isFinite(Number(v)) && Number(v) >= 0
const pct = (v: string | null | undefined) => (v == null ? '—' : `${v}%`)
const toLocal = (iso?: string | null) => {
  if (!iso) return ''
  const d = new Date(iso)
  return new Date(d.getTime() - d.getTimezoneOffset() * 60_000).toISOString().slice(0, 16)
}
const toIso = (local: string) => (local ? new Date(local).toISOString() : null)
const OFFER_LABEL: Record<string, string> = { scheduled: 'Offer scheduled', live: 'Offer running', ended: 'Offer ended' }

function Row({ label, hint, value, strong }: { label: string; hint?: string; value: string; strong?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1.5">
      <dt className="text-sm text-muted">{label}{hint && <span className="block text-xs">{hint}</span>}</dt>
      <dd className={`text-right tabular-nums ${strong ? 'text-base font-semibold text-forest' : 'text-sm'}`}>{value}</dd>
    </div>
  )
}

/** Cost → selling price → discount → final price → profit, explained in plain words. The server does the maths. */
export function PricingPanel({ product }: { product: ProductDetail }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [mode, setMode] = useState<'price' | 'margin'>('price')
  const [selling, setSelling] = useState(product.selling_price ?? '')
  const [targetMargin, setTargetMargin] = useState('')
  const [discountType, setDiscountType] = useState(product.discount_type ?? '')
  const [discountValue, setDiscountValue] = useState(product.discount_value && Number(product.discount_value) ? product.discount_value : '')
  const [starts, setStarts] = useState(toLocal(product.discount_starts_at))
  const [ends, setEnds] = useState(toLocal(product.discount_ends_at))
  const [reason, setReason] = useState('')
  const [errors, setErrors] = useState<Record<string, string>>({})

  const input = useDebounced({ selling, discountType, discountValue }, 350)
  const ready = num(input.selling) && Number(input.selling) > 0 && (!input.discountType || num(input.discountValue))
  const preview = useQuery({
    queryKey: ['pricing-preview', product.id, input],
    queryFn: () => pricingPreview({ product: product.id, selling_price: input.selling, discount_type: input.discountType, discount_value: input.discountType ? input.discountValue : '' }),
    enabled: ready, retry: false, placeholderData: (previous) => previous,
  })
  const suggestionReady = mode === 'margin' && num(targetMargin) && Number(product.store_price) > 0
  const suggestion = useQuery({
    queryKey: ['pricing-suggest', product.id, targetMargin],
    queryFn: () => pricingPreview({ product: product.id, target_margin: targetMargin }),
    enabled: suggestionReady, retry: false,
  })
  const save = useMutation({
    mutationFn: () => setPricing(product.id, { selling_price: selling, discount_type: discountType, discount_value: discountType ? discountValue : '', discount_starts_at: discountType ? toIso(starts) : null, discount_ends_at: discountType ? toIso(ends) : null, reason }),
    onSuccess: () => { setErrors({}); toast('success', 'Price saved.'); void qc.invalidateQueries({ queryKey: ['product'] }); void qc.invalidateQueries({ queryKey: ['products'] }) },
    onError: (e) => setErrors(fieldErrors(e)),
  })

  const b = preview.data?.breakdown
  const stale = ready && preview.isFetching
  const errorText = preview.error ? errorMessage(preview.error) : ''
  const apiErrors = Object.values(errors).join(' ')

  return (
    <Card className="space-y-4 p-4 sm:p-6">
      <div>
        <h2 className="text-lg font-semibold text-forest">Price &amp; profit</h2>
        <p className="text-sm text-muted">Store price is what Zuuvi pays the store. Customers pay the final price.</p>
      </div>
      <dl className="rounded-control bg-canvas px-3"><Row label="Store price" hint="Cost to Zuuvi per unit" value={formatMoney(product.store_price)} /></dl>

      <fieldset className="space-y-3">
        <legend className="sr-only">How do you want to set the price?</legend>
        <div className="flex gap-4 text-sm" role="radiogroup" aria-label="Pricing method">
          <label className="flex min-h-11 items-center gap-2"><input type="radio" name="pm" className="accent-forest" checked={mode === 'price'} onChange={() => setMode('price')} />I know the selling price</label>
          <label className="flex min-h-11 items-center gap-2"><input type="radio" name="pm" className="accent-forest" checked={mode === 'margin'} onChange={() => setMode('margin')} />I want a target margin</label>
        </div>
        {mode === 'margin' && (
          <div className="space-y-2 rounded-control border border-line p-3">
            <Field label="Target margin (%)" hint="Share of the selling price you want to keep as profit. Must be below 100.">
              {(p) => <Input {...p} inputMode="decimal" value={targetMargin} onChange={(e) => setTargetMargin(e.target.value)} />}
            </Field>
            {suggestion.data?.suggested_selling_price && (
              <div className="flex flex-wrap items-center gap-3 text-sm">
                <span>Suggested selling price: <strong>{formatMoney(suggestion.data.suggested_selling_price)}</strong></span>
                <Button size="sm" variant="outline" onClick={() => { setSelling(suggestion.data!.suggested_selling_price!); setMode('price') }}>Use this price</Button>
              </div>
            )}
            {suggestion.error && <p className="text-sm text-danger" role="alert">{errorMessage(suggestion.error)}</p>}
            <p className="text-xs text-muted">Nothing changes until you choose “Use this price” and save.</p>
          </div>
        )}
        <Field label="Selling price before discount (₹)" required error={errors.selling_price} hint="The regular price on the shelf.">
          {(p) => <Input {...p} inputMode="decimal" value={selling} onChange={(e) => setSelling(e.target.value)} />}
        </Field>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Discount">
            {(p) => (
              <Select {...p} value={discountType} onChange={(e) => { setDiscountType(e.target.value); if (!e.target.value) setDiscountValue('') }}>
                <option value="">No discount</option><option value="PERCENTAGE">Percentage off</option><option value="FIXED">Amount off (₹)</option>
              </Select>
            )}
          </Field>
          {discountType && (
            <Field label={discountType === 'PERCENTAGE' ? 'Discount (%)' : 'Discount (₹)'} error={errors.discount_value}>
              {(p) => <Input {...p} inputMode="decimal" value={discountValue} onChange={(e) => setDiscountValue(e.target.value)} />}
            </Field>
          )}
          {discountType && <>
            <Field label="Offer starts (optional)" hint="Empty = now.">{(p) => <Input {...p} type="datetime-local" value={starts} onChange={(e) => setStarts(e.target.value)} />}</Field>
            <Field label="Offer ends (optional)" error={errors.discount_ends_at ?? (starts && ends && ends <= starts ? 'The offer must end after it starts.' : undefined)} hint="Empty = until removed.">{(p) => <Input {...p} type="datetime-local" value={ends} onChange={(e) => setEnds(e.target.value)} />}</Field>
          </>}
        </div>
        {product.offer_state && product.offer_state !== 'none' && <p className="text-sm"><span className="rounded-full bg-warn-bg px-2 py-0.5 text-xs text-warn">{OFFER_LABEL[product.offer_state]}</span> Outside the offer dates customers pay the selling price.</p>}
      </fieldset>

      <div aria-live="polite" className={stale ? 'opacity-60' : undefined}>
        {b ? (
          <dl className="divide-y divide-line rounded-control border border-line px-3">
            <Row label="Selling price" value={formatMoney(b.selling_price)} />
            <Row label="Discount" value={Number(b.discount_amount) ? `− ${formatMoney(b.discount_amount)}` : 'None'} />
            <Row label="Final price" hint="What the customer pays" value={formatMoney(b.final_price)} strong />
            <Row label="Profit per unit" hint="Final price − store price" value={formatMoney(b.profit_per_unit)} strong />
            <Row label="Profit margin" hint="Profit ÷ final price" value={pct(b.margin_percent)} />
            <Row label="Markup" hint="Profit ÷ store price" value={pct(b.markup_percent)} />
          </dl>
        ) : <p className="text-sm text-muted">Enter a selling price to see the profit.</p>}
        {b && <p className="mt-2 text-xs text-muted">{b.label}. Tax and payment fees are not included.</p>}
        {b?.warnings.map((w) => <Alert key={w} tone="warn">{w}</Alert>)}
        {errorText && !b && <p className="text-sm text-danger" role="alert">{errorText}</p>}
      </div>

      {apiErrors && <Alert tone="error">{apiErrors}</Alert>}
      <Field label="Reason (optional)" hint="Shown in the price history.">{(p) => <Input {...p} value={reason} maxLength={255} onChange={(e) => setReason(e.target.value)} />}</Field>
      <Button onClick={() => save.mutate()} loading={save.isPending} disabled={!ready || Boolean(b?.below_cost) || Boolean(starts && ends && ends <= starts)}>Save price</Button>
      {b?.below_cost && <p className="text-xs text-muted">Prices below the store price cannot be saved.</p>}
    </Card>
  )
}
