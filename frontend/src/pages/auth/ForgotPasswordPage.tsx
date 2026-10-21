import { useState } from 'react'
import { Link } from 'react-router-dom'
import { AuthShell } from '@/components/AuthShell'
import { Alert, Button, Field, Input } from '@/components/ui'
import { errorMessage } from '@/lib/api'
import { requestPasswordReset } from '@/services/auth'

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState('')
  const [state, setState] = useState<'idle' | 'sending' | 'sent'>('idle')
  const [error, setError] = useState('')
  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setError('')
    setState('sending')
    try { await requestPasswordReset(email.trim()); setState('sent') } catch (e) { setError(errorMessage(e)); setState('idle') }
  }
  return (
    <AuthShell title="Reset your password" subtitle="Enter the email on your account and we’ll send a reset link if it exists.">
      {state === 'sent' ? (
        <Alert tone="success" title="Check your email">If that address has an account, a reset link is on its way. The link works once and expires.</Alert>
      ) : (
        <form onSubmit={(e) => void submit(e)} className="space-y-4">
          {error && <Alert tone="error">{error}</Alert>}
          <Field label="Email" required>{(p) => <Input {...p} type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />}</Field>
          <Button type="submit" loading={state === 'sending'} className="w-full">Send reset link</Button>
        </form>
      )}
      <p className="mt-4 text-center text-sm"><Link to="/login" className="font-medium text-forest hover:underline">Back to sign in</Link></p>
    </AuthShell>
  )
}
