import { useQuery } from '@tanstack/react-query'
import { Users } from 'lucide-react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { DataTable, KeyValue, Pagination, QueryBoundary, Section, Segmented, Status } from '@/components/kit'
import { Card, Input, PageHeader, Select } from '@/components/ui'
import { useUrlState } from '@/hooks/useUrlState'
import { formatDate, formatMoney } from '@/lib/format'
import { label, ORDER_STATUS, PAYMENT_METHOD, PAYMENT_STATUS } from '@/lib/labels'
import { adminCustomer, adminCustomers } from '@/services/ops'
import type { AdminCustomerRow } from '@/types/ops'

export function AdminCustomersList() {
  const navigate = useNavigate()
  const { values, page, set } = useUrlState(['q', 'active', 'ordering', 'from', 'to'] as const)
  const q = useQuery({ queryKey: ['admin-customers', values, page], queryFn: () => adminCustomers({ ...values, page }), placeholderData: (p) => p })
  const filtered = Object.values(values).some(Boolean)
  return (
    <>
      <PageHeader title="Customers" subtitle={q.data ? `${q.data.count} customer${q.data.count === 1 ? '' : 's'}` : undefined} />
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <Segmented label="Account state" value={values.active} onChange={(v) => set({ active: v })} options={[{ value: '', label: 'All' }, { value: '1', label: 'Active' }, { value: '0', label: 'Suspended' }]} />
        <label className="text-sm">Sort by<Select className="mt-1" value={values.ordering} onChange={(e) => set({ ordering: e.target.value })}><option value="">Newest</option><option value="orders">Most orders</option><option value="value">Highest delivered value</option><option value="name">Username A–Z</option></Select></label>
        <label className="text-sm">Joined from<Input className="mt-1" type="date" value={values.from} onChange={(e) => set({ from: e.target.value })} /></label>
        <label className="text-sm">to<Input className="mt-1" type="date" value={values.to} onChange={(e) => set({ to: e.target.value })} /></label>
        <label className="min-w-[12rem] flex-1 text-sm sm:max-w-xs">Search<Input className="mt-1" type="search" defaultValue={values.q} placeholder="Name, email, phone or code" onKeyDown={(e) => e.key === 'Enter' && set({ q: e.currentTarget.value })} onBlur={(e) => e.target.value !== values.q && set({ q: e.target.value })} /></label>
        {filtered && <button type="button" className="min-h-11 text-sm font-semibold text-forest underline" onClick={() => set({ q: '', active: '', ordering: '', from: '', to: '' })}>Reset filters</button>}
      </div>
      <QueryBoundary query={q} isEmpty={q.data?.count === 0} empty={{ icon: Users, title: filtered ? 'No customers match these filters' : 'No customers yet', text: filtered ? 'Try clearing a filter.' : 'Customers appear here after they register.' }}>
        <DataTable caption="Customers" rows={q.data?.results ?? []} rowKey={(c) => c.id} onRowClick={(c) => navigate(`/admin/customers/${c.id}`)}
          columns={[
            { key: 'n', header: 'Customer', primary: true, cell: (c: AdminCustomerRow) => <Link to={`/admin/customers/${c.id}`} onClick={(e) => e.stopPropagation()} className="inline-flex min-h-11 flex-col justify-center font-semibold text-forest hover:underline">{c.name}<span className="text-xs font-normal text-muted">{c.email}</span></Link> },
            { key: 'c', header: 'Code', cell: (c) => c.customer_code },
            { key: 'o', header: 'Orders', cell: (c) => c.order_count, className: 'tabular-nums' },
            { key: 'v', header: 'Delivered value', cell: (c) => formatMoney(c.delivered_value), className: 'tabular-nums' },
            { key: 'l', header: 'Last order', cell: (c) => formatDate(c.last_order_at) },
            { key: 'j', header: 'Joined', cell: (c) => formatDate(c.created_at) },
            { key: 's', header: 'State', cell: (c) => <Status value={c.is_active ? 'ACTIVE' : 'SUSPENDED'} label={c.is_active ? 'Active' : 'Suspended'} /> },
          ]} />
        <Pagination page={page} count={q.data?.count ?? 0} onPage={(p) => set({ page: p })} />
      </QueryBoundary>
    </>
  )
}

export function AdminCustomerPage() {
  const id = Number(useParams().id)
  const q = useQuery({ queryKey: ['admin-customer', id], queryFn: () => adminCustomer(id) })
  const c = q.data
  return (
    <>
      <PageHeader title={c?.name ?? 'Customer'} subtitle={c?.customer_code} actions={<Link className="inline-flex min-h-11 items-center text-sm font-semibold text-forest underline" to="/admin/customers">Back to customers</Link>} />
      <QueryBoundary query={q} skeleton="detail">
        {c && (
          <div className="grid gap-6 lg:grid-cols-[1fr_20rem]">
            <div className="space-y-6">
              <Section title="Recent orders" actions={<Link className="inline-flex min-h-11 items-center text-sm font-semibold text-forest underline" to={`/admin/orders?q=${encodeURIComponent(c.username)}`}>All orders</Link>}>
                {c.recent_orders.length === 0 ? <Card className="p-4 text-sm text-muted">This customer has not placed an order yet.</Card> : (
                  <Card className="divide-y divide-line">
                    {c.recent_orders.map((o) => (
                      <Link key={o.id} to={`/admin/orders/${o.id}`} className="flex min-h-14 items-center justify-between gap-3 px-4 py-2 text-sm hover:bg-pale/50">
                        <span><strong>{o.order_number}</strong><br /><span className="text-xs text-muted">{formatDate(o.placed_at)} · {label(PAYMENT_METHOD, o.payment_method)} · {label(PAYMENT_STATUS, o.payment_status)}</span></span>
                        <span className="flex flex-col items-end gap-1"><Status value={o.status} label={label(ORDER_STATUS, o.status)} /><span className="tabular-nums">{formatMoney(o.grand_total)}</span></span>
                      </Link>
                    ))}
                  </Card>
                )}
              </Section>
              <Section title="Orders by status">
                <Card className="p-4 text-sm">{Object.keys(c.orders_by_status).length === 0 ? <span className="text-muted">No orders.</span> : <ul className="flex flex-wrap gap-x-6 gap-y-1">{Object.entries(c.orders_by_status).map(([k, n]) => <li key={k}>{label(ORDER_STATUS, k)}: <strong>{n}</strong></li>)}</ul>}</Card>
              </Section>
            </div>
            <Card className="h-fit space-y-4 p-4">
              <Status value={c.is_active ? 'ACTIVE' : 'SUSPENDED'} label={c.is_active ? 'Active' : 'Suspended'} />
              <KeyValue rows={[['Username', c.username], ['Email', c.email || '—'], ['Phone', c.phone_number || '—'], ['Joined', formatDate(c.created_at)], ['Signed up via', label({}, c.registration_source)], ['Orders', c.order_count], ['Delivered value', formatMoney(c.delivered_value)], ['Support tickets', c.tickets], ['Complaints', c.complaints], ['Reviews written', c.reviews]]} />
              <Link className="inline-flex min-h-11 items-center text-sm font-semibold text-forest underline" to={`/admin/users?q=${encodeURIComponent(c.username)}`}>Suspend or reactivate in Users</Link>
            </Card>
          </div>
        )}
      </QueryBoundary>
    </>
  )
}
