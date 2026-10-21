import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Package, Plus } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { DataTable, Modal, Pagination, QueryBoundary, Segmented, Status, useToast } from '@/components/kit'
import { Alert, Button, Field, Input, PageHeader, Select } from '@/components/ui'
import { useAuth } from '@/features/auth/AuthProvider'
import { useUrlState } from '@/hooks/useUrlState'
import { errorMessage, fieldErrors } from '@/lib/api'
import { formatDate, formatMoney } from '@/lib/format'
import { listStoreProducts, stockMovement } from '@/services/ops'
import type { StoreProductRow } from '@/types/ops'

const MOVEMENTS = [['STOCK_IN', 'Stock received'], ['STOCK_OUT', 'Stock removed'], ['ADJUST_IN', 'Count correction (add)'], ['ADJUST_OUT', 'Count correction (remove)'], ['DAMAGED', 'Damaged'], ['EXPIRED', 'Expired']] as const
const PRODUCT_STATUS: Record<string, string> = { DRAFT: 'Draft', PENDING: 'Awaiting approval', APPROVED: 'Approved', REJECTED: 'Rejected', INACTIVE: 'Inactive' }

export default function StoreProducts({ mode }: { mode: 'products' | 'stock' }) {
  const { user } = useAuth()
  const canEdit = user?.store?.can_manage_inventory ?? false
  const { values, page, set } = useUrlState(['q', 'status', 'low_stock'] as const)
  const q = useQuery({ queryKey: ['store-products', values, page], queryFn: () => listStoreProducts({ ...values, page }), placeholderData: (p) => p })
  const [adjust, setAdjust] = useState<StoreProductRow | null>(null)
  const title = mode === 'stock' ? 'Stock' : 'Products'
  return (
    <>
      <PageHeader title={title} subtitle={mode === 'stock' ? 'Record stock received, removed or corrected. Every change is logged.' : 'New products are reviewed by Zuuvi before customers can see them.'}
        actions={mode === 'products' && canEdit && <Link to="/store/products/new"><Button icon={Plus}>New product</Button></Link>} />
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <Segmented label="Stock filter" value={values.low_stock} onChange={(v) => set({ low_stock: v })} options={[{ value: '', label: 'All' }, { value: '1', label: 'Low stock' }]} />
        <label className="text-sm">Status<Select className="mt-1" value={values.status} onChange={(e) => set({ status: e.target.value })}><option value="">Any</option>{Object.entries(PRODUCT_STATUS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</Select></label>
        <label className="min-w-0 flex-1 text-sm sm:max-w-xs">Search<Input className="mt-1" type="search" defaultValue={values.q} placeholder="Name, SKU or code" onKeyDown={(e) => e.key === 'Enter' && set({ q: e.currentTarget.value })} onBlur={(e) => e.target.value !== values.q && set({ q: e.target.value })} /></label>
      </div>
      <QueryBoundary query={q} isEmpty={q.data?.count === 0} empty={{ icon: Package, title: 'No products found', text: values.q || values.status || values.low_stock ? 'Try different filters.' : 'Add your first product to start selling.', action: canEdit && !values.q ? <Link to="/store/products/new"><Button>Add a product</Button></Link> : undefined }}>
        <DataTable caption={title} rows={q.data?.results ?? []} rowKey={(p) => p.id}
          columns={[
            { key: 'n', header: 'Product', primary: true, cell: (p) => <Link className="font-semibold text-forest hover:underline" to={`/store/products/${p.id}`}>{p.name}</Link> },
            { key: 'sku', header: 'SKU', cell: (p) => p.sku },
            { key: 'st', header: 'Status', cell: (p) => <Status value={p.status} label={PRODUCT_STATUS[p.status] ?? p.status} /> },
            { key: 'q', header: 'In stock', className: 'text-right tabular-nums', cell: (p) => { const low = Number(p.stock_quantity) <= Number(p.low_stock_threshold); return <span className={low ? 'font-semibold text-warn' : ''}>{Number(p.stock_quantity)}{low ? ' · low' : ''}</span> } },
            { key: 'pr', header: 'Your price', className: 'text-right tabular-nums', cell: (p) => formatMoney(p.store_price) },
            { key: 'fp', header: 'Selling price', className: 'text-right tabular-nums', cell: (p) => (p.final_price ? formatMoney(p.final_price) : 'Set on approval') },
            { key: 'ex', header: 'Expires', cell: (p) => formatDate(p.expiry_date) },
            { key: 'a', header: 'Actions', cell: (p) => canEdit && <Button variant="secondary" className="min-h-9" onClick={() => setAdjust(p)}>Adjust stock</Button> },
          ]} />
        <Pagination page={page} count={q.data?.count ?? 0} onPage={(n) => set({ page: n })} />
      </QueryBoundary>
      {adjust && <StockDialog product={adjust} onClose={() => setAdjust(null)} />}
    </>
  )
}

function StockDialog({ product, onClose }: { product: StoreProductRow; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [v, setV] = useState({ movement: 'STOCK_IN', quantity: '', reason: '', notes: '' })
  const save = useMutation({
    mutationFn: () => stockMovement(product.id, v),
    onSuccess: (r) => { toast('success', `Stock is now ${Number(r.stock_quantity)}.`); void qc.invalidateQueries({ queryKey: ['store-products'] }); void qc.invalidateQueries({ queryKey: ['store-me'] }); onClose() },
  })
  const fe = fieldErrors(save.error)
  return (
    <Modal open onClose={onClose} title={`Adjust stock: ${product.name}`}>
      <form className="space-y-3" noValidate onSubmit={(e) => { e.preventDefault(); save.mutate() }}>
        <p className="text-sm text-muted">Current stock: <strong>{Number(product.stock_quantity)}</strong></p>
        {save.isError && !Object.keys(fe).length && <Alert>{errorMessage(save.error)}</Alert>}
        <Field label="What happened?" error={fe.movement}>{(p) => <Select {...p} value={v.movement} onChange={(e) => setV({ ...v, movement: e.target.value })}>{MOVEMENTS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</Select>}</Field>
        <Field label="Quantity" required error={fe.quantity}>{(p) => <Input {...p} inputMode="decimal" value={v.quantity} onChange={(e) => setV({ ...v, quantity: e.target.value })} />}</Field>
        <Field label="Reason" required error={fe.reason} hint="For example: new delivery from supplier.">{(p) => <Input {...p} maxLength={255} value={v.reason} onChange={(e) => setV({ ...v, reason: e.target.value })} />}</Field>
        <Field label="Notes (optional)" error={fe.notes}>{(p) => <Input {...p} maxLength={500} value={v.notes} onChange={(e) => setV({ ...v, notes: e.target.value })} />}</Field>
        <div className="flex justify-end gap-2 pt-2"><Button variant="secondary" onClick={onClose}>Cancel</Button><Button type="submit" loading={save.isPending}>Record change</Button></div>
      </form>
    </Modal>
  )
}
