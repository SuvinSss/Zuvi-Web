import { AlertCircle, CheckCircle2, Loader2, X, type LucideIcon } from 'lucide-react'
import { Link } from 'react-router-dom'
import { forwardRef, useId, type AnchorHTMLAttributes, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from 'react'

const cx = (...parts: (string | false | null | undefined)[]) => parts.filter(Boolean).join(' ')

export type ButtonVariant = 'primary' | 'secondary' | 'outline' | 'ghost' | 'destructive'
export type ButtonSize = 'sm' | 'md' | 'lg'

const VARIANTS: Record<ButtonVariant, string> = {
  primary: 'bg-forest text-white hover:bg-deep active:bg-deep shadow-sm',
  secondary: 'bg-pale text-forest hover:bg-line active:bg-line',
  outline: 'bg-white text-forest ring-1 ring-inset ring-line hover:bg-pale',
  ghost: 'text-forest hover:bg-pale',
  destructive: 'bg-white text-danger ring-1 ring-inset ring-danger/30 hover:bg-danger-bg',
}
/** One height scale for every button in the app; md is the 44px touch target. */
const SIZES: Record<ButtonSize, string> = {
  sm: 'min-h-9 px-3 text-xs',
  md: 'min-h-11 px-4 text-sm',
  lg: 'min-h-12 px-6 text-base',
}
const ICON_ONLY: Record<ButtonSize, string> = { sm: 'size-9 !px-0', md: 'size-11 !px-0', lg: 'size-12 !px-0' }

interface StyleOptions { variant?: ButtonVariant; size?: ButtonSize; iconOnly?: boolean; className?: string | undefined }
export const buttonClass = ({ variant = 'primary', size = 'md', iconOnly = false, className }: StyleOptions) =>
  cx(
    'inline-flex items-center justify-center gap-2 rounded-control font-semibold transition-colors',
    'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald',
    'disabled:cursor-not-allowed disabled:opacity-60 aria-disabled:cursor-not-allowed aria-disabled:opacity-60',
    VARIANTS[variant], SIZES[size], iconOnly && ICON_ONLY[size], className,
  )

interface BaseButtonProps {
  variant?: ButtonVariant
  size?: ButtonSize
  loading?: boolean
  icon?: LucideIcon
}
/** An icon-only button must say what it does: the label is required and doubles as the tooltip. */
type ButtonProps = BaseButtonProps & ButtonHTMLAttributes<HTMLButtonElement> & (
  | { iconOnly?: false }
  | { iconOnly: true; 'aria-label': string }
)

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'primary', size = 'md', loading = false, icon: Icon, iconOnly = false, className, children, disabled, type = 'button', ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      title={iconOnly ? (rest['aria-label'] as string) : rest.title}
      className={buttonClass({ variant, size, iconOnly, className })}
      {...rest}
    >
      {loading ? <Loader2 className="size-4 animate-spin" aria-hidden="true" /> : Icon ? <Icon className="size-4" aria-hidden="true" /> : null}
      {iconOnly ? null : children}
    </button>
  )
})

interface ButtonLinkProps extends BaseButtonProps, Omit<AnchorHTMLAttributes<HTMLAnchorElement>, 'href'> {
  to?: string
  href?: string
  disabled?: boolean
}
/** Navigation that looks like a button: a real link (router `to`, or `href` for downloads), never a button inside a link. */
export const ButtonLink = forwardRef<HTMLAnchorElement, ButtonLinkProps>(function ButtonLink(
  { to, href, variant = 'primary', size = 'md', icon: Icon, loading: _loading, disabled, className, children, ...rest },
  ref,
) {
  const content = <>{Icon ? <Icon className="size-4" aria-hidden="true" /> : null}{children}</>
  const cls = buttonClass({ variant, size, className })
  if (disabled || (!to && !href)) return <span aria-disabled="true" className={cls}>{content}</span>
  if (to) return <Link ref={ref} to={to} className={cls} {...rest}>{content}</Link>
  return <a ref={ref} href={href} className={cls} {...rest}>{content}</a>
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
  NEEDS_INFO: 'bg-warn-bg text-warn',
}
export function StatusBadge({ status }: { status: string }) {
  return (
    <span className={cx('inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold', BADGE[status] ?? BADGE.DRAFT)}>
      {(status.charAt(0) + status.slice(1).toLowerCase()).replace(/_/g, ' ').replace('Needs info', 'Needs information')}
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
