import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Star } from 'lucide-react'
import { useState } from 'react'
import { KeyValue, QueryBoundary, Section, Stars, Pagination, useToast } from '@/components/kit'
import { Alert, Button, Card, Field, Input, PageHeader, Select } from '@/components/ui'
import { useAuth } from '@/features/auth/AuthProvider'
import { errorMessage, fieldErrors } from '@/lib/api'
import { formatDate } from '@/lib/format'
import { label } from '@/lib/labels'
import { useUrlState } from '@/hooks/useUrlState'
import { partnerMe, partnerRatings, updatePartner } from '@/services/ops'
import { PARTNER_STATUS } from './labels'

const VEHICLES = [['BICYCLE', 'Bicycle'], ['SCOOTER', 'Scooter'], ['MOTORCYCLE', 'Motorcycle'], ['CAR', 'Car'], ['VAN', 'Van'], ['OTHER', 'Other']]

export default function DeliveryProfile() {
  const { user } = useAuth()
  const qc = useQueryClient()
  const toast = useToast()
  const me = useQuery({ queryKey: ['partner-me'], queryFn: partnerMe })
  const [form, setForm] = useState<{ vehicle_type: string; vehicle_number: string } | null>(null)
  const f = form ?? { vehicle_type: me.data?.vehicle_type ?? '', vehicle_number: me.data?.vehicle_number ?? '' }
  const save = useMutation({ mutationFn: () => updatePartner(f), onSuccess: (p) => { qc.setQueryData(['partner-me'], p); setForm(null); toast('success', 'Vehicle details saved.') } })
  const fe = fieldErrors(save.error)
  const { page, set } = useUrlState([] as const)
  const ratings = useQuery({ queryKey: ['partner-ratings', page], queryFn: () => partnerRatings(page), placeholderData: (p) => p })
  return (
    <>
      <PageHeader title="Profile" subtitle={user?.name} />
      <QueryBoundary query={me} skeleton="detail">
        {me.data && (
          <div className="grid gap-6 lg:grid-cols-2">
            <Card className="space-y-3 p-4">
              <KeyValue rows={[['Account', label(PARTNER_STATUS, me.data.status)], ['Joined', formatDate(me.data.created_at)], ['Phone', user?.phone_number]]} />
              <form className="space-y-3" noValidate onSubmit={(e) => { e.preventDefault(); save.mutate() }}>
                {save.isError && !Object.keys(fe).length && <Alert>{errorMessage(save.error)}</Alert>}
                <Field label="Vehicle" error={fe.vehicle_type}>{(p) => <Select {...p} value={f.vehicle_type} onChange={(e) => setForm({ ...f, vehicle_type: e.target.value })}>{VEHICLES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</Select>}</Field>
                <Field label="Vehicle number" error={fe.vehicle_number}>{(p) => <Input {...p} value={f.vehicle_number} onChange={(e) => setForm({ ...f, vehicle_number: e.target.value })} />}</Field>
                <Button type="submit" loading={save.isPending} disabled={!form}>Save</Button>
              </form>
            </Card>
            <Section title="Ratings from customers">
              <QueryBoundary query={ratings} isEmpty={ratings.data?.count === 0} empty={{ icon: Star, title: 'No ratings yet' }}>
                <ul className="space-y-2">{ratings.data?.results.map((r) => <li key={r.id}><Card className="p-3"><Stars value={r.rating} />{r.comment && <p className="mt-1 text-sm">{r.comment}</p>}<p className="text-xs text-muted">{formatDate(r.created_at)}</p></Card></li>)}</ul>
                <Pagination page={page} count={ratings.data?.count ?? 0} onPage={(n) => set({ page: n })} />
              </QueryBoundary>
            </Section>
          </div>
        )}
      </QueryBoundary>
    </>
  )
}
