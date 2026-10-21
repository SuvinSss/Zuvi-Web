import { useQuery } from '@tanstack/react-query'
import { Tags } from 'lucide-react'
import { Link } from 'react-router-dom'
import { DataTable, QueryBoundary, Status } from '@/components/kit'
import { PageHeader } from '@/components/ui'
import { adminCategories } from '@/services/ops'

export default function AdminCategories() {
  const q = useQuery({ queryKey: ['admin-categories'], queryFn: adminCategories })
  return (
    <>
      <PageHeader title="Categories" subtitle="Product categories and how many products each holds." />
      <QueryBoundary query={q} isEmpty={q.data?.results.length === 0} empty={{ icon: Tags, title: 'No categories yet' }}>
        <DataTable caption="Categories" rows={q.data?.results ?? []} rowKey={(c) => c.id}
          columns={[
            { key: 'n', header: 'Category', primary: true, cell: (c) => <span className="font-semibold">{c.parent_name ? `${c.parent_name} › ` : ''}{c.name}</span> },
            { key: 'p', header: 'Products', cell: (c) => <Link className="inline-flex min-h-11 items-center text-forest hover:underline" to={`/admin/products?q=${encodeURIComponent(c.name)}`}>{c.product_count}</Link>, className: 'tabular-nums' },
            { key: 's', header: 'State', cell: (c) => <Status value={c.is_active ? 'ACTIVE' : 'INACTIVE'} label={c.is_active ? 'Active' : 'Inactive'} /> },
          ]} />
        <p className="mt-4 text-sm text-muted">Categories are created and renamed by a Super Admin in the technical admin (Django admin); the API does not yet offer category editing.</p>
      </QueryBoundary>
    </>
  )
}
