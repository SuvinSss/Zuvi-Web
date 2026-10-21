import axios, { AxiosError } from 'axios'

/**
 * One configured HTTP client. The Django session cookie (HttpOnly) is the only
 * credential; nothing secret is kept in browser storage. Unsafe requests carry
 * the CSRF token from the `csrftoken` cookie, or — when the API is on another
 * origin and the cookie is unreadable — the token returned by /auth/session/.
 */
export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api/v1',
  withCredentials: true,
  headers: { Accept: 'application/json' },
})

let tokenFromServer = ''
export function setCsrfToken(token: string | undefined) {
  if (token) tokenFromServer = token
}

export function csrfToken(): string {
  const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/)
  return match?.[1] ? decodeURIComponent(match[1]) : tokenFromServer
}

api.interceptors.request.use((config) => {
  if (!/^(get|head|options)$/i.test(config.method ?? 'get')) {
    config.headers.set('X-CSRFToken', csrfToken())
  }
  return config
})

type Handler = () => void
let onSessionExpired: Handler | undefined
export function setSessionExpiredHandler(handler: Handler | undefined) {
  onSessionExpired = handler
}

api.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    const url = error.config?.url ?? ''
    const isAuthCall = url.includes('/auth/')
    if (!isAuthCall && error.response?.status === 401) onSessionExpired?.()
    const detail = (error.response?.data as { detail?: string } | undefined)?.detail
    if (!isAuthCall && error.response?.status === 403 && detail?.includes('credentials were not provided')) {
      onSessionExpired?.()
    }
    return Promise.reject(error)
  },
)

type ErrorBody = { detail?: string; [field: string]: unknown }

/** A single human-readable message for any failed request. */
export function errorMessage(error: unknown, fallback = 'Something went wrong. Please try again.'): string {
  if (axios.isAxiosError(error)) {
    if (!error.response) return 'Cannot reach the server. Check your connection and try again.'
    const raw = error.response.data as unknown
    const data = raw && typeof raw === 'object' ? (raw as ErrorBody) : undefined
    if (typeof data?.detail === 'string') return data.detail
    const first = Object.entries(data ?? {}).find(([, value]) => Array.isArray(value) || typeof value === 'string')
    if (first) {
      const [field, value] = first
      const text = Array.isArray(value) ? String(value[0]) : String(value)
      return field === 'non_field_errors' ? text : `${field.replace(/_/g, ' ')}: ${text}`
    }
    if (error.response.status === 413) return 'That file is too large.'
    if (error.response.status >= 500) return 'The server had a problem. Please try again.'
  }
  return fallback
}

/** DRF field errors as { field: message } for form libraries. */
export function fieldErrors(error: unknown): Record<string, string> {
  if (!axios.isAxiosError(error) || error.response?.status !== 400) return {}
  const data = error.response.data as ErrorBody | undefined
  const out: Record<string, string> = {}
  for (const [field, value] of Object.entries(data ?? {})) {
    if (Array.isArray(value)) out[field] = String(value[0])
    else if (typeof value === 'string' && field !== 'detail') out[field] = value
  }
  return out
}
