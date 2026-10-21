import { useMutation, useQueryClient } from '@tanstack/react-query'
import { MapPin, MessageSquare, Star } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { Section, useToast } from '@/components/kit'
import { Alert, Button, Card, Field, Input, PageHeader } from '@/components/ui'
import { useAuth } from '@/features/auth/AuthProvider'
import { errorMessage, fieldErrors } from '@/lib/api'
import { roleLabel } from '@/lib/roles'
import { changePassword, updateProfile } from '@/services/auth'

export default function AccountPage() {
  const { user } = useAuth()
  const qc = useQueryClient()
  const toast = useToast()
  const [form, setForm] = useState({ first_name: user?.first_name ?? '', last_name: user?.last_name ?? '', phone_number: user?.phone_number ?? '', email: user?.email ?? '' })
  const [pw, setPw] = useState({ current: '', next: '', confirm: '' })
  const [pwError, setPwError] = useState('')
  const save = useMutation({ mutationFn: () => updateProfile(form), onSuccess: () => { toast('success', 'Profile saved.'); void qc.invalidateQueries({ queryKey: ['session'] }) } })
  const pass = useMutation({
    mutationFn: () => changePassword(pw.current, pw.next),
    onSuccess: () => { toast('success', 'Password changed.'); setPw({ current: '', next: '', confirm: '' }) },
  })
  const fe = fieldErrors(save.error)
  const pe = fieldErrors(pass.error)
  const submitPw = (e: FormEvent) => {
    e.preventDefault()
    if (pw.next !== pw.confirm) { setPwError('The new passwords do not match.'); return }
    setPwError('')
    pass.mutate()
  }
  return (
    <>
      <PageHeader title="My account" subtitle={`${(user ? roleLabel[user.role] : '')} · @${user?.username}`} />
      <div className="mb-6 grid gap-3 sm:grid-cols-3">
        {[['/account/addresses', MapPin, 'Addresses'], ['/account/reviews', Star, 'My reviews'], ['/account/feedback', MessageSquare, 'Feedback']].map(([to, Icon, text]) => {
          const I = Icon as typeof MapPin
          return <Link key={to as string} to={to as string} className="flex min-h-14 items-center gap-3 rounded-card border border-line bg-white p-4 font-semibold text-forest shadow-card hover:bg-pale"><I className="size-5" aria-hidden="true" />{text as string}</Link>
        })}
      </div>
      <div className="grid gap-6 lg:grid-cols-2">
        <Section title="Profile">
          <Card className="p-4">
            <form onSubmit={(e) => { e.preventDefault(); save.mutate() }} className="space-y-3" noValidate>
              {save.isError && !Object.keys(fe).length && <Alert>{errorMessage(save.error)}</Alert>}
              <Field label="First name" error={fe.first_name}>{(p) => <Input {...p} autoComplete="given-name" value={form.first_name} onChange={(e) => setForm({ ...form, first_name: e.target.value })} />}</Field>
              <Field label="Last name" error={fe.last_name}>{(p) => <Input {...p} autoComplete="family-name" value={form.last_name} onChange={(e) => setForm({ ...form, last_name: e.target.value })} />}</Field>
              <Field label="Phone number" error={fe.phone_number}>{(p) => <Input {...p} type="tel" autoComplete="tel" value={form.phone_number} onChange={(e) => setForm({ ...form, phone_number: e.target.value })} />}</Field>
              <Field label="Email" error={fe.email}>{(p) => <Input {...p} type="email" autoComplete="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />}</Field>
              <Button type="submit" loading={save.isPending}>Save profile</Button>
            </form>
          </Card>
        </Section>
        <Section title="Change password">
          <Card className="p-4">
            <form onSubmit={submitPw} className="space-y-3" noValidate>
              {pass.isError && !Object.keys(pe).length && <Alert>{errorMessage(pass.error)}</Alert>}
              <Field label="Current password" error={pe.current_password}>{(p) => <Input {...p} type="password" autoComplete="current-password" value={pw.current} onChange={(e) => setPw({ ...pw, current: e.target.value })} />}</Field>
              <Field label="New password" error={pe.new_password} hint="At least 8 characters.">{(p) => <Input {...p} type="password" autoComplete="new-password" value={pw.next} onChange={(e) => setPw({ ...pw, next: e.target.value })} />}</Field>
              <Field label="Confirm new password" error={pwError}>{(p) => <Input {...p} type="password" autoComplete="new-password" value={pw.confirm} onChange={(e) => setPw({ ...pw, confirm: e.target.value })} />}</Field>
              <Button type="submit" loading={pass.isPending}>Change password</Button>
            </form>
          </Card>
        </Section>
      </div>
    </>
  )
}
