import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { z } from 'zod'
import { Logo } from '@/components/Logo'
import { Alert, Button, Field, Input } from '@/components/ui'
import { useAuth } from '@/features/auth/AuthProvider'
import { errorMessage } from '@/lib/api'

const schema = z.object({
  username: z.string().trim().min(1, 'Enter your username.'),
  password: z.string().min(1, 'Enter your password.'),
})
type Values = z.infer<typeof schema>

export default function LoginPage() {
  const { status, expired, signIn } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const from = (location.state as { from?: string } | null)?.from ?? '/products'
  const [serverError, setServerError] = useState('')
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<Values>({ resolver: zodResolver(schema) })

  if (status === 'authenticated') return <Navigate to={from} replace />

  const onSubmit = handleSubmit(async ({ username, password }) => {
    setServerError('')
    try {
      await signIn(username, password)
      navigate(from, { replace: true })
    } catch (error) {
      setServerError(errorMessage(error, 'Could not sign in.'))
    }
  })

  return (
    <div className="grid min-h-dvh lg:grid-cols-2">
      <div className="hidden flex-col justify-between bg-night p-12 lg:flex">
        <Logo variant="dark" className="w-48" />
        <div>
          <h2 className="max-w-md text-4xl font-semibold leading-tight text-white">Fresh, local, and easy to manage.</h2>
          <p className="mt-4 max-w-md text-white/70">Keep your catalogue accurate, your product photos light and fast, and bulk-add products from a spreadsheet.</p>
        </div>
        <p className="text-sm text-white/50">Zuvi management</p>
      </div>
      <div className="flex items-center justify-center px-4 py-10 sm:px-8">
        <form onSubmit={(event) => void onSubmit(event)} noValidate className="rise w-full max-w-sm space-y-5">
          <Logo variant="light" className="mx-auto w-36 lg:hidden" />
          <div>
            <h1 className="text-2xl font-semibold text-forest">Sign in</h1>
            <p className="mt-1 text-sm text-muted">Use your Zuvi management account.</p>
          </div>
          {expired && <Alert tone="warn" title="Your session expired">Please sign in again. Unsaved changes on the previous page were not submitted.</Alert>}
          {serverError && <Alert tone="error">{serverError}</Alert>}
          <Field label="Username" error={errors.username?.message}>
            {(props) => <Input {...props} autoComplete="username" autoFocus {...register('username')} />}
          </Field>
          <Field label="Password" error={errors.password?.message}>
            {(props) => <Input {...props} type="password" autoComplete="current-password" {...register('password')} />}
          </Field>
          <Button type="submit" loading={isSubmitting} className="w-full">Sign in</Button>
        </form>
      </div>
    </div>
  )
}
