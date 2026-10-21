import { zodResolver } from '@hookform/resolvers/zod'
import { Eye, EyeOff } from 'lucide-react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { z } from 'zod'
import { Logo } from '@/components/Logo'
import { Alert, Button, Field, Input } from '@/components/ui'
import { useAuth } from '@/features/auth/AuthProvider'
import { errorMessage } from '@/lib/api'
import { homePath } from '@/lib/roles'

const schema = z.object({
  username: z.string().trim().min(1, 'Enter your username.'),
  password: z.string().min(1, 'Enter your password.'),
})
type Values = z.infer<typeof schema>

export default function LoginPage() {
  const { status, user, expired, signIn } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const from = (location.state as { from?: string } | null)?.from
  const [serverError, setServerError] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<Values>({ resolver: zodResolver(schema) })

  if (status === 'authenticated' && user) return <Navigate to={from ?? homePath(user)} replace />

  const onSubmit = handleSubmit(async ({ username, password }) => {
    setServerError('')
    try {
      const signedIn = await signIn(username, password)
      navigate(from ?? homePath(signedIn), { replace: true })
    } catch (error) {
      setServerError(errorMessage(error, 'Could not sign in.'))
    }
  })

  return (
    <div className="grid min-h-dvh lg:grid-cols-2">
      <div className="hidden flex-col justify-between bg-night p-12 lg:flex">
        <Link to="/" aria-label="Zuvi home"><Logo variant="dark" className="w-48" /></Link>
        <div>
          <h2 className="max-w-md text-4xl font-semibold leading-tight text-white">Fresh, local, and easy to manage.</h2>
          <p className="mt-4 max-w-md text-white/70">Shop from local stores, run your store, deliver orders or manage the platform — all from one account.</p>
        </div>
        <p className="text-sm text-white/50">Zuvi</p>
      </div>
      <div className="flex items-center justify-center px-4 py-10 sm:px-8">
        <form onSubmit={(event) => void onSubmit(event)} noValidate className="rise w-full max-w-sm space-y-5">
          <Link to="/" aria-label="Zuvi home" className="block lg:hidden"><Logo variant="light" className="mx-auto w-36" /></Link>
          <div>
            <h1 className="text-2xl font-semibold text-forest">Sign in</h1>
            <p className="mt-1 text-sm text-muted">Welcome back. Use your Zuvi username and password.</p>
          </div>
          {expired && <Alert tone="warn" title="Your session expired">Please sign in again. Anything you hadn’t submitted was not saved.</Alert>}
          {serverError && <Alert tone="error">{serverError}</Alert>}
          <Field label="Username" error={errors.username?.message}>
            {(props) => <Input {...props} autoComplete="username" autoCapitalize="none" autoFocus {...register('username')} />}
          </Field>
          <Field label="Password" error={errors.password?.message}>
            {(props) => (
              <div className="relative">
                <Input {...props} type={showPassword ? 'text' : 'password'} autoComplete="current-password" className="pr-12" {...register('password')} />
                <button type="button" onClick={() => setShowPassword((s) => !s)} aria-label={showPassword ? 'Hide password' : 'Show password'} aria-pressed={showPassword} className="absolute right-1 top-1/2 grid size-10 -translate-y-1/2 place-items-center rounded-control text-muted hover:text-ink">
                  {showPassword ? <EyeOff className="size-5" aria-hidden="true" /> : <Eye className="size-5" aria-hidden="true" />}
                </button>
              </div>
            )}
          </Field>
          <Button type="submit" loading={isSubmitting} className="w-full">Sign in</Button>
          <div className="flex flex-col gap-1 text-center text-sm">
            <Link to="/forgot-password" className="inline-flex min-h-11 items-center font-medium text-forest hover:underline">Forgot your password?</Link>
            <span className="text-muted">New here? <Link to="/register" className="inline-flex min-h-11 items-center font-medium text-forest hover:underline">Create an account</Link></span>
          </div>
        </form>
      </div>
    </div>
  )
}
