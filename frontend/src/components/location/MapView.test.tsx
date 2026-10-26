import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('./LeafletMap', () => ({ default: () => <div data-testid="leaflet" /> }))
vi.mock('./GoogleMap', () => ({ default: () => <div data-testid="google" /> }))
vi.mock('@/services/delivery', () => ({ geoConfig: vi.fn() }))

describe('MapView provider', () => {
  beforeEach(() => vi.resetModules())

  it('uses Google when the backend supplies a browser key, with no frontend rebuild', async () => {
    const delivery = await import('@/services/delivery')
    vi.mocked(delivery.geoConfig).mockResolvedValue({ browser_key: 'web-key', map_id: 'MAPID' } as never)
    const { MapView } = await import('./MapView')
    render(<MapView />)
    expect(await screen.findByTestId('google')).toBeInTheDocument()
    expect(screen.queryByTestId('leaflet')).not.toBeInTheDocument()
  })

  it('falls back to OpenStreetMap when there is no key, and when the config cannot load', async () => {
    const delivery = await import('@/services/delivery')
    vi.mocked(delivery.geoConfig).mockResolvedValue({ browser_key: '' } as never)
    const { MapView } = await import('./MapView')
    const first = render(<MapView />)
    await waitFor(() => expect(screen.getByTestId('leaflet')).toBeInTheDocument())
    first.unmount()
    vi.resetModules()
    const again = await import('@/services/delivery')
    vi.mocked(again.geoConfig).mockRejectedValue(new Error('offline'))
    const { MapView: Fresh } = await import('./MapView')
    render(<Fresh />)
    await waitFor(() => expect(screen.getByTestId('leaflet')).toBeInTheDocument())
  })
})
