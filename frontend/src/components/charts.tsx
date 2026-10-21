import { useId } from 'react'

/* Small dependency-free SVG charts. Each one has a text title and a visually hidden data table, so the numbers are available without sight. */

const W = 640
const H = 220
const PAD = { l: 44, r: 12, t: 12, b: 26 }
const shortDate = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })
const niceMax = (max: number) => {
  if (max <= 0) return 1
  const pow = 10 ** Math.floor(Math.log10(max))
  const n = max / pow
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * pow
}
const compact = (n: number) => new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 }).format(n)

export interface ChartPoint { label: string; value: number }

export function TrendChart({ title, points, kind = 'line', format = (n: number) => String(n), color = 'var(--color-emerald)' }: {
  title: string; points: ChartPoint[]; kind?: 'line' | 'bar'; format?: (n: number) => string; color?: string
}) {
  const id = useId()
  const total = points.reduce((s, p) => s + p.value, 0)
  const max = niceMax(Math.max(0, ...points.map((p) => p.value)))
  const iw = W - PAD.l - PAD.r
  const ih = H - PAD.t - PAD.b
  const x = (i: number) => PAD.l + (points.length === 1 ? iw / 2 : (i / (points.length - 1)) * iw)
  const y = (v: number) => PAD.t + ih - (v / max) * ih
  const ticks = [0, 0.5, 1].map((t) => t * max)
  const labelEvery = Math.max(1, Math.ceil(points.length / 6))
  const barW = Math.max(2, (iw / Math.max(points.length, 1)) * 0.7)
  return (
    <figure aria-labelledby={`${id}-t`} className="min-w-0">
      <figcaption id={`${id}-t`} className="sr-only">{title}</figcaption>
      {total === 0 ? (
        <p className="grid h-40 place-items-center rounded-control bg-canvas text-sm text-muted">No activity in this period.</p>
      ) : (
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${title}. Total ${format(total)}.`} className="h-auto w-full">
          {ticks.map((t) => (
            <g key={t}>
              <line x1={PAD.l} x2={W - PAD.r} y1={y(t)} y2={y(t)} stroke="var(--color-line)" strokeWidth="1" />
              <text x={PAD.l - 6} y={y(t) + 4} textAnchor="end" fontSize="11" fill="var(--color-muted)">{compact(t)}</text>
            </g>
          ))}
          {kind === 'bar'
            ? points.map((p, i) => <rect key={p.label} x={x(i) - barW / 2} y={y(p.value)} width={barW} height={Math.max(0, PAD.t + ih - y(p.value))} rx="2" fill={color}><title>{`${shortDate(p.label)}: ${format(p.value)}`}</title></rect>)
            : (
              <>
                <path d={`${points.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join(' ')} L${x(points.length - 1).toFixed(1)},${PAD.t + ih} L${x(0).toFixed(1)},${PAD.t + ih} Z`} fill={color} opacity="0.1" />
                <path d={points.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join(' ')} fill="none" stroke={color} strokeWidth="2.5" strokeLinejoin="round" />
                {points.length <= 31 && points.map((p, i) => <circle key={p.label} cx={x(i)} cy={y(p.value)} r="3" fill="var(--color-card, #fff)" stroke={color} strokeWidth="2"><title>{`${shortDate(p.label)}: ${format(p.value)}`}</title></circle>)}
              </>
            )}
          {points.map((p, i) => (i % labelEvery === 0 ? <text key={p.label} x={x(i)} y={H - 6} textAnchor="middle" fontSize="11" fill="var(--color-muted)">{shortDate(p.label)}</text> : null))}
        </svg>
      )}
      <table className="sr-only">
        <caption>{title}</caption>
        <thead><tr><th>Date</th><th>Value</th></tr></thead>
        <tbody>{points.map((p) => <tr key={p.label}><td>{shortDate(p.label)}</td><td>{format(p.value)}</td></tr>)}</tbody>
      </table>
    </figure>
  )
}

export interface BarRow { key: string; label: string; value: number; display?: string; hint?: string }

/** Ranked horizontal bars: used for status distribution, top stores and best-selling products. */
export function BarList({ rows, empty = 'No data in this period.' }: { rows: BarRow[]; empty?: string }) {
  if (!rows.length) return <p className="text-sm text-muted">{empty}</p>
  const max = Math.max(...rows.map((r) => r.value), 1)
  return (
    <ul className="space-y-3">
      {rows.map((r) => (
        <li key={r.key} className="text-sm">
          <div className="flex items-baseline justify-between gap-3">
            <span className="min-w-0 truncate" title={r.label}>{r.label}</span>
            <strong className="shrink-0 tabular-nums">{r.display ?? r.value}</strong>
          </div>
          <div className="mt-1 h-2 rounded-full bg-canvas" aria-hidden="true"><div className="h-2 rounded-full bg-emerald" style={{ width: `${Math.max(3, (r.value / max) * 100)}%` }} /></div>
          {r.hint && <p className="mt-0.5 text-xs text-muted">{r.hint}</p>}
        </li>
      ))}
    </ul>
  )
}
