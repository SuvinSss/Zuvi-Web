import { AlertCircle, CheckCircle2, Loader2, X, type LucideIcon } from 'lucide-react'
import { forwardRef, useId, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from 'react'

const cx = (...parts: (string | false | null | undefined)[]) => parts.filter(Boolean).join(' ')

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger'
const VARIANTS: Record<Variant, string> = {
  primary: 'bg-forest text-white hover:bg-deep active:bg-deep shadow-sm',
  secondary: 'bg-white text-forest ring-1 ring-inset ring-line hover:bg-pale',
  ghost: 'text-forest hover:bg-pale',
  danger: 'bg-white text-danger ring-1 ring-inset ring-danger/30 hover:bg-danger-bg',
}

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  loading?: boolean
  icon?: LucideIcon
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'primary', loading = false, icon: Icon, className, children, disabled, type = 'button', ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cx(
        'inline-flex min-h-11 items-center justify-center gap-2 rounded-control px-4 text-sm font-semibold transition-colors',
        'disabled:cursor-not-allowed disabled:opacity-60',
        VARIANTS[variant],
        className,
      )}
      {...rest}
    >
      {loading ? <Loader2 className="size-4 animate-spin" aria-hidden="true" /> : Icon ? <Icon className="size-4" aria-hidden="true" /> : null}
      {children}
    </button>
  )
})

export const controlClass =
  'block w-full min-h-11 rounded-control border border-line bg-white px-3 py-2 text-base text-ink placeholder:text-muted/70 ' +
  'focus:border-emerald focus:outline-none focus:ring-2 focus:ring-emerald/30 disabled:bg-canvas disabled:text-muted sm:text-sm'

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input({ className, ...rest }, ref) {
  return <input ref={ref} className={cx(controlClass, className)} {...rest} />
})
export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(function Select({ className, ...rest }, ref) {
  return <select ref={ref} className={cx(controlClass, className)} {...rest} />
})
export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(function Textarea({ className, ...rest }, ref) {
  return <textarea ref={ref} className={cx(controlClass, className)} {...rest} />
})

interface FieldProps {
  label: string
  error?: string | undefined
  hint?: string
  required?: boolean
  children: (props: { id: string; 'aria-invalid': boolean | undefined; 'aria-describedby': string | undefined }) => ReactNode
  className?: string
}

/** Label + control + hint/error wired together for screen readers. */
export function Field({ label, error, hint, required, children, className }: FieldProps) {
  const id = useId()
  const describedBy = error ? `${id}-error` : hint ? `${id}-hint` : undefined
  return (
    <div className={className}>
      <label htmlFor={id} className="mb-1 block text-sm font-medium text-ink">
        {label}
        {required && <span className="text-danger" aria-hidden="true"> *</span>}
      </label>
      {children({ id, 'aria-invalid': error ? true : undefined, 'aria-describedby': describedBy })}
      {error ? (
        <p id={`${id}-error`} role="alert" className="mt-1 text-sm text-danger">{error}</p>
      ) : hint ? (
        <p id={`${id}-hint`} className="mt-1 text-xs text-muted">{hint}</p>
      ) : null}
    </div>
  )
}

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <section className={cx('rounded-card border border-line bg-white shadow-card', className)}>{children}</section>
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <header className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold text-forest sm:text-3xl">{title}</h1>
        {subtitle && <p className="mt-1 max-w-2xl text-sm text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </header>
  )
}

const BADGE: Record<string, string> = {
  APPROVED: 'bg-mint text-deep',
  PENDING: 'bg-warn-bg text-warn',
  DRAFT: 'bg-canvas text-muted ring-1 ring-line',
  REJECTED: 'bg-danger-bg text-danger',
  INACTIVE: 'bg-canvas text-muted ring-1 ring-line',
}
export function StatusBadge({ status }: { status: string }) {
  return (
    <span className={cx('inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold', BADGE[status] ?? BADGE.DRAFT)}>
      {status.charAt(0) + status.slice(1).toLowerCase()}
    </span>
  )
}

export function Spinner({ label = 'Loading…' }: { label?: string }) {
  return (
    <div role="status" className="flex items-center justify-center gap-2 p-8 text-sm text-muted">
      <Loader2 className="size-5 animate-spin text-emerald" aria-hidden="true" />
      <span>{label}</span>
    </div>
  )
}

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden="true" className={cx('skeleton rounded-control', className)} />
}

export function EmptyState({ icon: Icon, title, children, action }: { icon: LucideIcon; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="rise flex flex-col items-center gap-3 px-6 py-14 text-center">
      <div className="grid size-14 place-items-center rounded-full bg-pale text-emerald">
        <Icon className="size-7" aria-hidden="true" />
      </div>
      <h2 className="text-lg font-semibold text-forest">{title}</h2>
      {children && <p className="max-w-md text-sm text-muted">{children}</p>}
      {action}
    </div>
  )
}

export function Alert({ tone = 'error', title, children, onDismiss }: { tone?: 'error' | 'success' | 'warn' | 'info'; title?: string; children?: ReactNode; onDismiss?: () => void }) {
  const styles = {
    error: 'border-danger/30 bg-danger-bg text-danger',
    success: 'border-emerald/30 bg-pale text-deep',
    warn: 'border-warn/30 bg-warn-bg text-warn',
    info: 'border-line bg-canvas text-ink',
  }[tone]
  const Icon = tone === 'success' ? CheckCircle2 : AlertCircle
  return (
    <div role={tone === 'error' ? 'alert' : 'status'} className={cx('flex gap-3 rounded-control border p-3 text-sm', styles)}>
      <Icon className="mt-0.5 size-5 shrink-0" aria-hidden="true" />
      <div className="min-w-0 flex-1">
        {title && <p className="font-semibold">{title}</p>}
        {children && <div className={title ? 'mt-0.5' : ''}>{children}</div>}
      </div>
      {onDismiss && (
        <button type="button" onClick={onDismiss} aria-label="Dismiss" className="grid size-8 place-items-center rounded-md hover:bg-black/5">
          <X className="size-4" aria-hidden="true" />
        </button>
      )}
    </div>
  )
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="flex flex-col items-center gap-3 px-6 py-12 text-center">
      <Alert tone="error" title="Could not load this">{message}</Alert>
      {onRetry && <Button variant="secondary" onClick={onRetry}>Try again</Button>}
    </div>
  )
}
