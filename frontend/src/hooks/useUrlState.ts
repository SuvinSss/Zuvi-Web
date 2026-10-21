import { useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'

/** Filters live in the URL so lists are shareable, survive refresh and work with the back button. */
export function useUrlState<T extends string>(keys: readonly T[]) {
  const [params, setParams] = useSearchParams()
  const values = Object.fromEntries(keys.map((k) => [k, params.get(k) ?? ''])) as Record<T, string>
  const page = Math.max(1, Number(params.get('page')) || 1)
  const set = useCallback(
    (patch: Partial<Record<T | 'page', string | number>>) => {
      setParams((current) => {
        const next = new URLSearchParams(current)
        for (const [k, v] of Object.entries(patch)) {
          if (v === '' || v === undefined || v === null || (k === 'page' && Number(v) <= 1)) next.delete(k)
          else next.set(k, String(v))
        }
        if (!('page' in patch)) next.delete('page') // changing a filter returns to page 1
        return next
      }, { replace: true })
    },
    [setParams],
  )
  return { values, page, set }
}
