import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { AuthShell } from '@/components/AuthShell'
import { Alert, Button, ButtonLink, Field, Input } from '@/components/ui'
import { errorMessage } from '@/lib/api'
import { acceptInvite } from '@/services/management'

/** Landing page of the one-time link a store owner receives: choose a password, then sign in. */
export default function SetupAccountPage() {
  const token = useSearchParams()[0].get('token') ?? ''
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [state, setState] = useState<'idle' | 'sending' | 'done'>('idle')
  const [error, setError] = useState('')
  if (!token) return <AuthShell title="Setup link problem"><Alert tone="error">This setup link is incomplete. Ask the administrator for a new one.</Alert></AuthShell>
  const mismatch = confirm !== '' && confirm !== password
  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    if (password !== confirm) { setError('The two passwords do not match.'); return }
    setError(''); setState('sending')
    try { await acceptInvite(token, password); setState('done') } catch (e) { setError(errorMessage(e)); setState('idle') }
  }
  return (
    <AuthShell title="Set up your store account">
      {state === 'done' ? (
        <>
          <Alert tone="success" title="Password saved">Your account is ready. Sign in with your username and the password you just chose.</Alert>
          <ButtonLink to="/login" className="mt-4 w-full">Sign in</ButtonLink>
        </>
      ) : (
        <form onSubmit={(e) => void submit(e)} className="space-y-4">
          {error && <Alert tone="error">{error}</Alert>}
          <Field label="New password" required hint="At least 8 characters, not common or only numbers.">{(p) => <Input {...p} type="password" autoComplete="new-password" required minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} />}</Field>
          <Field label="Confirm password" required error={mismatch ? 'The passwords do not match.' : undefined}>{(p) => <Input {...p} type="password" autoComplete="new-password" required value={confirm} onChange={(e) => setConfirm(e.target.value)} />}</Field>
          <Button type="submit" loading={state === 'sending'} className="w-full">Save password</Button>
          <p className="text-xs text-muted">This link works once and expires after 3 days.</p>
        </form>
      )}
    </AuthShell>
  )
}
