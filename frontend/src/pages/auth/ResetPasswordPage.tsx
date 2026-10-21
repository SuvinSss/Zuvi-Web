import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { AuthShell } from '@/components/AuthShell'
import { Alert, Button, Field, Input } from '@/components/ui'
import { errorMessage } from '@/lib/api'
import { confirmPasswordReset } from '@/services/auth'

export default function ResetPasswordPage() {
  const [params] = useSearchParams()
  const uid = params.get('uid') ?? ''
  const token = params.get('token') ?? ''
  const [password, setPassword] = useState('')
  const [state, setState] = useState<'idle' | 'sending' | 'done'>('idle')
  const [error, setError] = useState('')
  if (!uid || !token) return <AuthShell title="Reset link problem"><Alert tone="error">This reset link is incomplete. Request a new one.</Alert><Link to="/forgot-password"><Button className="mt-4 w-full">Request a new link</Button></Link></AuthShell>
  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setError('')
    setState('sending')
    try { await confirmPasswordReset(uid, token, password); setState('done') } catch (e) { setError(errorMessage(e)); setState('idle') }
  }
  return (
    <AuthShell title="Choose a new password">
      {state === 'done' ? (
        <>
          <Alert tone="success" title="Password updated">You can now sign in with your new password.</Alert>
          <Link to="/login"><Button className="mt-4 w-full">Sign in</Button></Link>
        </>
      ) : (
        <form onSubmit={(e) => void submit(e)} className="space-y-4">
          {error && <Alert tone="error">{error}</Alert>}
          <Field label="New password" required hint="At least 8 characters.">{(p) => <Input {...p} type="password" autoComplete="new-password" required minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} />}</Field>
          <Button type="submit" loading={state === 'sending'} className="w-full">Save password</Button>
        </form>
      )}
    </AuthShell>
  )
}
