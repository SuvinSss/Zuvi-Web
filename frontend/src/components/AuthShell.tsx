import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Logo } from '@/components/Logo'

export function AuthShell({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  return (
    <div className="flex min-h-dvh items-start justify-center bg-canvas px-4 py-8 sm:items-center">
      <div className="rise w-full max-w-md rounded-card border border-line bg-white p-5 shadow-card sm:p-8">
        <Link to="/" aria-label="Zuvi home" className="mb-5 block"><Logo variant="light" className="w-28" /></Link>
        <h1 className="text-2xl font-semibold text-forest">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-muted">{subtitle}</p>}
        <div className="mt-5">{children}</div>
      </div>
    </div>
  )
}
