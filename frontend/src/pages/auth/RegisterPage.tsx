import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link, useNavigate } from 'react-router-dom'
import { z } from 'zod'
import { AuthShell } from '@/components/AuthShell'
import { Alert, Button, Field, Input, Select, ButtonLink } from '@/components/ui'
import { useAuth } from '@/features/auth/AuthProvider'
import { errorMessage, fieldErrors } from '@/lib/api'
import * as auth from '@/services/auth'

const base = {
  first_name: z.string().trim().min(1, 'Enter your first name.'),
  last_name: z.string().trim().optional(),
  username: z.string().trim().min(3, 'Choose a username with at least 3 characters.').regex(/^[\w.@+-]+$/, 'Use letters, numbers and . @ + - _ only.'),
  email: z.string().trim().email('Enter a valid email address.'),
  phone_number: z.string().trim().regex(/^\+?\d{10,15}$/, 'Enter a phone number with 10–15 digits.'),
  password: z.string().min(8, 'Use at least 8 characters.'),
}
const customerSchema = z.object(base)
const partnerSchema = z.object({ ...base, vehicle_type: z.string().min(1), vehicle_number: z.string().trim().optional() })
type Values = z.infer<typeof partnerSchema>

const VEHICLES = [['BICYCLE', 'Bicycle'], ['SCOOTER', 'Scooter'], ['MOTORCYCLE', 'Motorcycle'], ['CAR', 'Car'], ['VAN', 'Van'], ['OTHER', 'Other']]

export default function RegisterPage({ partner = false }: { partner?: boolean }) {
  const navigate = useNavigate()
  const { signIn } = useAuth()
  const [serverError, setServerError] = useState('')
  const [pending, setPending] = useState(false)
  const { register, handleSubmit, setError, formState: { errors, isSubmitting } } = useForm<Values>({
    resolver: zodResolver(partner ? partnerSchema : customerSchema) as never,
    defaultValues: { vehicle_type: 'MOTORCYCLE' },
  })

  const onSubmit = handleSubmit(async (values) => {
    setServerError('')
    try {
      if (partner) {
        await auth.registerPartner({ ...values, vehicle_number: values.vehicle_number ?? '' })
        setPending(true)
      } else {
        await auth.register(values)
        await signIn(values.username, values.password)
        navigate('/', { replace: true })
      }
    } catch (error) {
      const fields = fieldErrors(error)
      for (const [field, message] of Object.entries(fields)) if (field in values) setError(field as keyof Values, { message })
      setServerError(Object.keys(fields).some((f) => f in values) ? '' : errorMessage(error, 'Could not create your account.'))
    }
  })

  if (pending) {
    return (
      <AuthShell title="Application received">
        <Alert tone="success" title="Thanks for applying">Your delivery partner account is waiting for approval. You can sign in once our team approves it.</Alert>
        <ButtonLink to="/login" className="mt-4 w-full">Go to sign in</ButtonLink>
      </AuthShell>
    )
  }

  return (
    <AuthShell title={partner ? 'Become a delivery partner' : 'Create your account'} subtitle={partner ? 'Apply to deliver orders. We approve every partner before they start.' : 'Shop from local stores and track your deliveries.'}>
      <form onSubmit={(e) => void onSubmit(e)} noValidate className="space-y-4">
        {serverError && <Alert tone="error">{serverError}</Alert>}
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="First name" required error={errors.first_name?.message}>{(p) => <Input {...p} autoComplete="given-name" {...register('first_name')} />}</Field>
          <Field label="Last name" error={errors.last_name?.message}>{(p) => <Input {...p} autoComplete="family-name" {...register('last_name')} />}</Field>
        </div>
        <Field label="Username" required error={errors.username?.message}>{(p) => <Input {...p} autoComplete="username" autoCapitalize="none" {...register('username')} />}</Field>
        <Field label="Email" required error={errors.email?.message}>{(p) => <Input {...p} type="email" autoComplete="email" inputMode="email" {...register('email')} />}</Field>
        <Field label="Mobile number" required hint="10–15 digits, e.g. 9876543210" error={errors.phone_number?.message}>{(p) => <Input {...p} type="tel" autoComplete="tel" inputMode="tel" {...register('phone_number')} />}</Field>
        {partner && (
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Vehicle" required>{(p) => <Select {...p} {...register('vehicle_type')}>{VEHICLES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</Select>}</Field>
            <Field label="Vehicle number" error={errors.vehicle_number?.message}>{(p) => <Input {...p} autoCapitalize="characters" {...register('vehicle_number')} />}</Field>
          </div>
        )}
        <Field label="Password" required hint="At least 8 characters. Avoid common passwords." error={errors.password?.message}>{(p) => <Input {...p} type="password" autoComplete="new-password" {...register('password')} />}</Field>
        <Button type="submit" loading={isSubmitting} className="w-full">{partner ? 'Submit application' : 'Create account'}</Button>
        <p className="text-center text-sm text-muted">Already have an account? <Link to="/login" className="font-medium text-forest hover:underline">Sign in</Link></p>
      </form>
    </AuthShell>
  )
}
