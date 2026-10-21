import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Users } from 'lucide-react'
import { useState } from 'react'
import { DataTable, Pagination, QueryBoundary, ReasonDialog, Segmented, Status, useToast } from '@/components/kit'
import { Button, Input, PageHeader, Select } from '@/components/ui'
import { useAuth } from '@/features/auth/AuthProvider'
import { useUrlState } from '@/hooks/useUrlState'
import { errorMessage } from '@/lib/api'
import { formatDate } from '@/lib/format'
import { roleLabel } from '@/lib/roles'
import { adminUsers, setUserActive } from '@/services/ops'
import type { AdminUser } from '@/types/ops'
import type { Role } from '@/types/api'

export default function AdminUsers() {
  const { user: me } = useAuth()
  const qc = useQueryClient()
  const toast = useToast()
  const { values, page, set } = useUrlState(['role', 'active', 'q'] as const)
  const q = useQuery({ queryKey: ['admin-users', values, page], queryFn: () => adminUsers({ ...values, page }), placeholderData: (p) => p })
  const [target, setTarget] = useState<AdminUser | null>(null)
  const change = useMutation({
    mutationFn: (reason: string) => setUserActive(target!.id, !target!.is_active, reason),
    onSuccess: () => { toast('success', 'Account updated.'); setTarget(null); void qc.invalidateQueries({ queryKey: ['admin-users'] }) },
    onError: (e) => toast('error', errorMessage(e)),
  })
  return (
    <>
      <PageHeader title="Users" />
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <Segmented label="Account state" value={values.active} onChange={(v) => set({ active: v })} options={[{ value: '', label: 'All' }, { value: '1', label: 'Active' }, { value: '0', label: 'Suspended' }]} />
        <label className="text-sm">Role<Select className="mt-1" value={values.role} onChange={(e) => set({ role: e.target.value })}><option value="">Any</option>{Object.entries(roleLabel).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</Select></label>
        <label className="min-w-[12rem] flex-1 text-sm sm:max-w-xs">Search<Input className="mt-1" type="search" defaultValue={values.q} placeholder="Username, email or phone" onKeyDown={(e) => e.key === 'Enter' && set({ q: e.currentTarget.value })} onBlur={(e) => e.target.value !== values.q && set({ q: e.target.value })} /></label>
      </div>
      <QueryBoundary query={q} isEmpty={q.data?.count === 0} empty={{ icon: Users, title: 'No users match' }}>
        <DataTable caption="Users" rows={q.data?.results ?? []} rowKey={(u) => u.id}
          columns={[
            { key: 'u', header: 'User', primary: true, cell: (u) => <><strong>{u.username}</strong><br /><span className="text-xs text-muted">{u.email}</span></> },
            { key: 'r', header: 'Role', cell: (u) => roleLabel[u.role as Role] ?? u.role },
            { key: 's', header: 'State', cell: (u) => <Status value={u.is_active ? 'ACTIVE' : 'SUSPENDED'} label={u.is_active ? 'Active' : 'Suspended'} /> },
            { key: 'j', header: 'Joined', cell: (u) => formatDate(u.date_joined) },
            { key: 'l', header: 'Last sign-in', cell: (u) => formatDate(u.last_login) },
            { key: 'a', header: '', cell: (u) => u.id !== me?.id && <Button variant={u.is_active ? 'danger' : 'secondary'} className="min-h-9" onClick={() => setTarget(u)}>{u.is_active ? 'Suspend' : 'Reactivate'}</Button> },
          ]} />
        <Pagination page={page} count={q.data?.count ?? 0} onPage={(n) => set({ page: n })} />
      </QueryBoundary>
      <ReasonDialog open={!!target} title={target?.is_active ? `Suspend ${target.username}?` : `Reactivate ${target?.username}?`} field="Reason (recorded in the audit log)" confirm={target?.is_active ? 'Suspend' : 'Reactivate'} danger={target?.is_active} busy={change.isPending} onClose={() => setTarget(null)} onSubmit={(r) => change.mutate(r)} />
    </>
  )
}
