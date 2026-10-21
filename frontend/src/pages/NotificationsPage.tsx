import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Bell, CheckCheck } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Pagination, QueryBoundary, Segmented, useToast } from '@/components/kit'
import { Button, Card, PageHeader } from '@/components/ui'
import { useUrlState } from '@/hooks/useUrlState'
import { errorMessage } from '@/lib/api'
import { listNotifications, markAllNotificationsRead, markNotificationRead } from '@/services/platform'
import type { Notification } from '@/types/platform'

/** Only link to places that exist for the viewer; unknown payloads are shown as plain text. */
function target(n: Notification, area: string): string | null {
  const d = n.data
  const order = typeof d.order_id === 'number' ? d.order_id : undefined
  if (order && area === '/account') return `/account/orders/${order}`
  if (typeof d.ticket_id === 'number' && (area === '/account' || area === '/support')) return area === '/support' ? `/support/tickets/${d.ticket_id}` : `/account/support/tickets/${d.ticket_id}`
  if (typeof d.complaint_id === 'number' && (area === '/account' || area === '/support')) return area === '/support' ? `/support/complaints/${d.complaint_id}` : `/account/support/complaints/${d.complaint_id}`
  if (typeof d.delivery_id === 'number' && area === '/delivery') return `/delivery/assignments/${d.delivery_id}`
  return null
}

export default function NotificationsPage({ area = '/account' }: { area?: string }) {
  const qc = useQueryClient()
  const toast = useToast()
  const { values, page, set } = useUrlState(['unread'] as const)
  const list = useQuery({ queryKey: ['notifications', values.unread, page], queryFn: () => listNotifications({ page, unread: values.unread }), placeholderData: (p) => p })
  const refresh = () => { void qc.invalidateQueries({ queryKey: ['notifications'] }); void qc.invalidateQueries({ queryKey: ['unread-count'] }) }
  const readOne = useMutation({ mutationFn: markNotificationRead, onSuccess: refresh, onError: (e) => toast('error', errorMessage(e)) })
  const readAll = useMutation({ mutationFn: markAllNotificationsRead, onSuccess: () => { refresh(); toast('success', 'All notifications marked as read.') }, onError: (e) => toast('error', errorMessage(e)) })
  return (
    <>
      <PageHeader title="Notifications" actions={<Button variant="secondary" icon={CheckCheck} loading={readAll.isPending} onClick={() => readAll.mutate()}>Mark all as read</Button>} />
      <div className="mb-4"><Segmented label="Show" value={values.unread} onChange={(v) => set({ unread: v })} options={[{ value: '', label: 'All' }, { value: '1', label: 'Unread' }]} /></div>
      <QueryBoundary query={list} isEmpty={list.data?.count === 0} empty={{ icon: Bell, title: values.unread ? 'Nothing unread' : 'No notifications yet', text: 'Updates about your orders and requests appear here.' }}>
        <ul className="space-y-2">
          {list.data?.results.map((n) => {
            const to = target(n, area)
            return (
              <li key={n.id}>
                <Card className={`p-4 ${n.is_read ? '' : 'border-emerald'}`}>
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="font-semibold">{!n.is_read && <span className="mr-2 rounded-full bg-emerald px-2 py-0.5 text-xs text-white">New</span>}{n.title}</p>
                      {n.body && <p className="mt-1 whitespace-pre-line break-words text-sm">{n.body}</p>}
                      <p className="mt-1 text-xs text-muted">{new Date(n.created_at).toLocaleString('en-IN')}</p>
                      {to && <Link to={to} className="mt-1 inline-flex min-h-11 items-center inline-flex min-h-11 items-center text-sm font-semibold text-forest underline" onClick={() => !n.is_read && readOne.mutate(n.id)}>View details</Link>}
                    </div>
                    {!n.is_read && <Button variant="ghost" onClick={() => readOne.mutate(n.id)}>Mark read</Button>}
                  </div>
                </Card>
              </li>
            )
          })}
        </ul>
        <Pagination page={page} count={list.data?.count ?? 0} onPage={(p) => set({ page: p })} />
      </QueryBoundary>
    </>
  )
}
