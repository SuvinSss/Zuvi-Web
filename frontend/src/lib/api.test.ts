import axios, { AxiosError } from 'axios'
import { afterEach, describe, expect, it } from 'vitest'
import { api, csrfToken, errorMessage, fieldErrors, setCsrfToken } from './api'

function failure(status: number, data: unknown): AxiosError {
  return new AxiosError('x', 'ERR', undefined, undefined, { status, data, statusText: '', headers: {}, config: { headers: new axios.AxiosHeaders() } })
}

afterEach(() => { document.cookie = 'csrftoken=; expires=Thu, 01 Jan 1970 00:00:00 GMT'; setCsrfToken('') })

describe('csrf', () => {
  it('prefers the csrftoken cookie, else the server-provided token', () => {
    setCsrfToken('from-server')
    expect(csrfToken()).toBe('from-server')
    document.cookie = 'csrftoken=from-cookie'
    expect(csrfToken()).toBe('from-cookie')
  })

  it('attaches X-CSRFToken to unsafe requests only', async () => {
    document.cookie = 'csrftoken=abc123'
    const seen: Record<string, string | undefined> = {}
    api.defaults.adapter = async (config) => {
      seen[config.method ?? ''] = config.headers.get('X-CSRFToken') as string | undefined
      return { data: {}, status: 200, statusText: 'OK', headers: {}, config }
    }
    await api.get('/x'); await api.post('/x'); await api.patch('/x'); await api.delete('/x')
    expect(seen.get).toBeUndefined()
    expect(seen.post).toBe('abc123')
    expect(seen.patch).toBe('abc123')
    expect(seen.delete).toBe('abc123')
  })
})

describe('errorMessage', () => {
  it('prefers the server detail', () => expect(errorMessage(failure(409, { detail: 'Already imported.' }))).toBe('Already imported.'))
  it('formats field errors', () => expect(errorMessage(failure(400, { store_price: ['Enter a price.'] }))).toBe('store price: Enter a price.'))
  it('explains network failures', () => expect(errorMessage(new AxiosError('Network Error'))).toMatch(/Cannot reach the server/))
  it('does not leak server internals on 500', () => expect(errorMessage(failure(500, '<html>Traceback</html>'))).toBe('The server had a problem. Please try again.'))
  it('falls back for unknown errors', () => expect(errorMessage(new Error('boom'))).toMatch(/Something went wrong/))
})

describe('fieldErrors', () => {
  it('maps DRF 400 bodies', () => expect(fieldErrors(failure(400, { sku: ['Taken'], name: 'Required', detail: 'x' }))).toEqual({ sku: 'Taken', name: 'Required' }))
  it('ignores other statuses', () => expect(fieldErrors(failure(500, { sku: ['x'] }))).toEqual({}))
})
