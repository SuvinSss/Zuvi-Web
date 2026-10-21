import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FileSpreadsheet, Upload } from 'lucide-react'
import { DataTable, Pagination, QueryBoundary, Segmented, Status, useToast } from '@/components/kit'
import { Button, ButtonLink, PageHeader } from '@/components/ui'
import { useUrlState } from '@/hooks/useUrlState'
import { errorMessage } from '@/lib/api'
import { formatDateTime } from '@/lib/format'
import { errorReportUrl } from '@/services/imports'
import { importJobs, retryImport } from '@/services/management'
import type { ImportJob } from '@/types/management'

export default function ImportJobs() {
  const qc = useQueryClient()
  const toast = useToast()
  const { values, page, set } = useUrlState(['status'] as const)
  const q = useQuery({ queryKey: ['import-jobs', values.status, page], queryFn: () => importJobs({ status: values.status, page }), placeholderData: (p) => p })
  const retry = useMutation({
    mutationFn: (id: string) => retryImport(id),
    onSuccess: () => { toast('success', 'Retry finished.'); void qc.invalidateQueries({ queryKey: ['import-jobs'] }); void qc.invalidateQueries({ queryKey: ['products'] }) },
    onError: (e) => toast('error', errorMessage(e)),
  })
  return (
    <>
      <PageHeader title="Bulk import jobs" subtitle="Every product import: who ran it, what was created, and what still needs attention."
        actions={<ButtonLink icon={Upload} to="/admin/products/import">New import</ButtonLink>} />
      <div className="mb-4"><Segmented label="Status" value={values.status} onChange={(v) => set({ status: v })} options={[{ value: '', label: 'All' }, { value: 'PREVIEWED', label: 'Waiting for review' }, { value: 'COMMITTED', label: 'Imported' }, { value: 'FAILED', label: 'Failed' }]} /></div>
      <QueryBoundary query={q} isEmpty={q.data?.count === 0} empty={{ icon: FileSpreadsheet, title: 'No imports yet', text: 'Imports you run will be listed here.' }}>
        <DataTable caption="Import jobs" rows={q.data?.results ?? []} rowKey={(j) => j.id}
          columns={[
            { key: 'f', header: 'File', primary: true, cell: (j: ImportJob) => <><strong>{j.source_name || 'Import'}</strong><br /><span className="text-xs text-muted">{j.created_by ?? '—'} · {formatDateTime(j.created_at)}</span></> },
            { key: 's', header: 'Status', cell: (j: ImportJob) => <><Status value={j.status === 'PREVIEWED' ? 'PENDING' : j.status === 'COMMITTED' ? 'COMPLETED' : 'FAILED'} label={j.status === 'PREVIEWED' ? 'Waiting for review' : undefined} />{j.attempts > 1 && <span className="ml-2 text-xs text-muted">{j.attempts} attempts</span>}</> },
            { key: 'r', header: 'Rows', cell: (j: ImportJob) => `${j.counts.total} · ${j.counts.valid} valid${j.counts.invalid ? ` · ${j.counts.invalid} to fix` : ''}` },
            { key: 'o', header: 'Result', cell: (j: ImportJob) => (j.status === 'PREVIEWED' ? '—' : `${j.summary.created ?? 0} created · ${j.summary.updated ?? 0} updated · ${j.summary.failed ?? 0} left out`) },
            { key: 'a', header: 'Actions', cell: (j: ImportJob) => (
              <span className="flex flex-wrap gap-2">
                {(j.status === 'PREVIEWED' || j.retryable) && <ButtonLink size="sm" variant="outline" to={`/admin/products/import?job=${j.id}`}>{j.status === 'PREVIEWED' ? 'Review' : 'Fix rows'}</ButtonLink>}
                {j.retryable && <Button size="sm" variant="secondary" loading={retry.isPending && retry.variables === j.id} onClick={() => retry.mutate(j.id)}>Retry</Button>}
                {(j.counts.invalid > 0 || (j.summary.failed ?? 0) > 0) && <ButtonLink size="sm" variant="ghost" href={errorReportUrl(j.id, 'xlsx')}>Error report</ButtonLink>}
              </span>) },
          ]} />
        <Pagination page={page} count={q.data?.count ?? 0} onPage={(n) => set({ page: n })} />
      </QueryBoundary>
    </>
  )
}
