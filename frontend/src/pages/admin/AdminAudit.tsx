import { useQuery } from '@tanstack/react-query'
import { ScrollText } from 'lucide-react'
import { DataTable, Pagination, QueryBoundary } from '@/components/kit'
import { Input, PageHeader } from '@/components/ui'
import { useUrlState } from '@/hooks/useUrlState'
import { auditEvents } from '@/services/ops'

export default function AdminAudit() {
  const { values, page, set } = useUrlState(['action', 'object_type', 'actor'] as const)
  const q = useQuery({ queryKey: ['audit', values, page], queryFn: () => auditEvents({ ...values, page }), placeholderData: (p) => p })
  const field = (key: 'action' | 'object_type' | 'actor', text: string, ph: string) => (
    <label className="text-sm">{text}<Input className="mt-1" defaultValue={values[key]} placeholder={ph} onKeyDown={(e) => e.key === 'Enter' && set({ [key]: e.currentTarget.value })} onBlur={(e) => e.target.value !== values[key] && set({ [key]: e.target.value })} /></label>
  )
  return (
    <>
      <PageHeader title="Audit log" subtitle="A permanent record of sensitive actions. Entries cannot be edited." />
      <div className="mb-4 flex flex-wrap gap-3">{field('action', 'Action', 'e.g. user.suspend')}{field('object_type', 'Object type', 'e.g. Store')}{field('actor', 'Actor username', 'username')}</div>
      <QueryBoundary query={q} isEmpty={q.data?.count === 0} empty={{ icon: ScrollText, title: 'No events match' }}>
        <DataTable caption="Audit events" rows={q.data?.results ?? []} rowKey={(e) => e.id}
          columns={[
            { key: 'w', header: 'When', primary: true, cell: (e) => new Date(e.created_at).toLocaleString('en-IN') },
            { key: 'a', header: 'Actor', cell: (e) => e.actor ?? 'System' },
            { key: 'ac', header: 'Action', cell: (e) => <code className="text-xs">{e.action}</code> },
            { key: 'o', header: 'Object', cell: (e) => `${e.object_type} ${e.object_id}` },
            { key: 's', header: 'Summary', cell: (e) => <span className="break-words">{e.summary}</span> },
          ]} />
        <Pagination page={page} count={q.data?.count ?? 0} onPage={(n) => set({ page: n })} />
      </QueryBoundary>
    </>
  )
}
