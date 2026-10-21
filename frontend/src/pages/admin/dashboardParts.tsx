import { ArrowDownRight, ArrowUpRight } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Segmented } from '@/components/kit'
import { Card, Input } from '@/components/ui'
import { useUrlState } from '@/hooks/useUrlState'
import type { Kpi } from '@/types/ops'

export const ymd = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
const daysAgo = (n: number) => { const d = new Date(); d.setDate(d.getDate() - n); return ymd(d) }

const PRESETS = [{ value: 'today', label: 'Today' }, { value: '7', label: '7 days' }, { value: '30', label: '30 days' }, { value: '90', label: '90 days' }, { value: 'custom', label: 'Custom' }]

/** The selected period lives in the URL (?range=7 or ?range=custom&from=…&to=…) so it can be shared and survives refresh. */
export function usePeriod() {
  const { values, set } = useUrlState(['range', 'from', 'to'] as const)
  const range = values.range || '30'
  const today = ymd(new Date())
  let from = daysAgo(29)
  let to = today
  if (range === 'today') from = today
  else if (range === '7') from = daysAgo(6)
  else if (range === '90') from = daysAgo(89)
  else if (range === 'custom' && values.from && values.to) { from = values.from; to = values.to }
  const invalid = range === 'custom' && (!values.from || !values.to || values.from > values.to)
  return { range, from, to, invalid, set, raw: values }
}

export function PeriodPicker({ period }: { period: ReturnType<typeof usePeriod> }) {
  const { range, set, raw, invalid } = period
  return (
    <div className="flex flex-wrap items-end gap-3">
      <Segmented label="Period" value={range} onChange={(v) => set({ range: v === '30' ? '' : v, from: '', to: '' })} options={PRESETS} />
      {range === 'custom' && (
        <>
          <label className="text-sm">From<Input className="mt-1" type="date" max={ymd(new Date())} value={raw.from} onChange={(e) => set({ range: 'custom', from: e.target.value, to: raw.to })} /></label>
          <label className="text-sm">To<Input className="mt-1" type="date" max={ymd(new Date())} value={raw.to} onChange={(e) => set({ range: 'custom', from: raw.from, to: e.target.value })} /></label>
          {invalid && <p role="alert" className="text-sm text-danger">Choose a start date that is not after the end date (max 366 days).</p>}
        </>
      )}
    </div>
  )
}

export function KpiCard({ label, value, kpi, to, hint, attention }: { label: string; value: string | number; kpi?: Kpi; to?: string; hint?: string; attention?: boolean }) {
  const change = kpi?.change_percent
  const body = (
    <>
      <p className="text-sm text-muted">{label}</p>
      <p className={`mt-1 text-2xl font-semibold tabular-nums ${attention ? 'text-warn' : 'text-forest'}`}>{value}</p>
      {kpi && (
        <p className="mt-1 flex items-center gap-1 text-xs text-muted">
          {change === null || change === undefined ? 'No earlier data to compare' : (
            <>
              {change >= 0 ? <ArrowUpRight className="size-4 text-emerald" aria-hidden="true" /> : <ArrowDownRight className="size-4 text-danger" aria-hidden="true" />}
              <span className={change >= 0 ? 'font-semibold text-emerald' : 'font-semibold text-danger'}>{change >= 0 ? '+' : ''}{change}%</span> vs previous period
            </>
          )}
        </p>
      )}
      {hint && <p className="mt-1 text-xs text-muted">{hint}</p>}
    </>
  )
  return (
    <Card className={`min-w-0 ${attention ? 'border-l-4 !border-l-warn' : ''}`}>
      {to ? <Link to={to} className="block rounded-card p-4 hover:bg-pale/50 focus-visible:outline-2 focus-visible:outline-emerald">{body}</Link> : <div className="p-4">{body}</div>}
    </Card>
  )
}
