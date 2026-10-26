import { useEffect, useRef, useState } from 'react'
import { GOOGLE_BROWSER_KEY, KERALA_CENTER, type MapProps } from './mapTypes'

let loader: Promise<void> | null = null

/** Load the Maps JavaScript API once. The key is a referrer-restricted browser key, never the server key. */
function loadGoogle(): Promise<void> {
  if (typeof (window as { google?: { maps?: { importLibrary?: unknown } } }).google?.maps?.importLibrary === 'function') return Promise.resolve()
  if (loader) return loader
  loader = new Promise<void>((resolve, reject) => {
    const cb = '__zuuviGoogleMapsReady'
    ;(window as unknown as Record<string, () => void>)[cb] = () => resolve()
    const s = document.createElement('script')
    s.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(GOOGLE_BROWSER_KEY)}&v=weekly&loading=async&region=IN&language=en&callback=${cb}`
    s.async = true
    s.onerror = () => { loader = null; reject(new Error('Google Maps could not load.')) }
    document.head.appendChild(s)
  })
  return loader
}

const pinSymbol = (color: string): google.maps.Symbol => ({
  path: 'M12 2C8 2 5 5.1 5 9c0 5.2 7 13 7 13s7-7.8 7-13c0-3.9-3-7-7-7z', fillColor: color, fillOpacity: 1, strokeColor: '#ffffff', strokeWeight: 2,
  scale: 1.6, anchor: new google.maps.Point(12, 22),
})

/** Same props and behaviour as the Leaflet map: draggable pin, extra markers, polygon, tap handling. */
export default function GoogleMap({ value, onPinChange, markers = [], polygon, onMapClick, height = 280, label = 'Map', zoom = 15 }: MapProps) {
  const el = useRef<HTMLDivElement>(null)
  const map = useRef<google.maps.Map | null>(null)
  const pin = useRef<google.maps.Marker | null>(null)
  const extras = useRef<google.maps.Marker[]>([])
  const shape = useRef<google.maps.Polygon | null>(null)
  const fitted = useRef(false)
  const pinCb = useRef(onPinChange)
  const clickCb = useRef(onMapClick)
  const [ready, setReady] = useState(false)
  const [failed, setFailed] = useState(false)
  useEffect(() => { pinCb.current = onPinChange; clickCb.current = onMapClick })

  useEffect(() => {
    let cancelled = false
    loadGoogle().then(async () => {
      if (cancelled || !el.current || map.current) return
      const { Map } = (await google.maps.importLibrary('maps')) as google.maps.MapsLibrary
      await google.maps.importLibrary('marker')
      const m = new Map(el.current, {
        center: value ? { lat: value.lat, lng: value.lon } : { lat: KERALA_CENTER[0], lng: KERALA_CENTER[1] }, zoom: value ? zoom : 8,
        gestureHandling: 'cooperative', streetViewControl: false, mapTypeControl: false, fullscreenControl: false, clickableIcons: false,
      })
      m.addListener('click', (e: google.maps.MapMouseEvent) => {
        if (!e.latLng) return
        if (clickCb.current) clickCb.current(e.latLng.lat(), e.latLng.lng())
        else pinCb.current?.(e.latLng.lat(), e.latLng.lng())
      })
      map.current = m
      setReady(true)
    }).catch(() => { if (!cancelled) setFailed(true) })
    return () => { cancelled = true }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    const m = map.current
    if (!m || !ready) return
    if (!value) { pin.current?.setMap(null); pin.current = null; return }
    const pos = { lat: value.lat, lng: value.lon }
    if (!pin.current) {
      pin.current = new google.maps.Marker({ position: pos, map: m, draggable: Boolean(pinCb.current), icon: pinSymbol('#0f5132'), title: 'Delivery location' })
      pin.current.addListener('dragend', () => { const p = pin.current?.getPosition(); if (p) pinCb.current?.(p.lat(), p.lng()) })
      m.setCenter(pos); m.setZoom(Math.max(m.getZoom() ?? zoom, zoom))
    } else {
      pin.current.setPosition(pos)
      if (!m.getBounds()?.contains(pos)) m.panTo(pos)
    }
  }, [value, zoom, ready])

  useEffect(() => {
    const m = map.current
    if (!m || !ready) return
    extras.current.forEach((x) => x.setMap(null))
    extras.current = markers.map((mk) => new google.maps.Marker({ position: { lat: mk.lat, lng: mk.lon }, map: m, title: mk.label, icon: pinSymbol(mk.color ?? '#b45309') }))
  }, [markers, ready])

  useEffect(() => {
    const m = map.current
    if (!m || !ready) return
    shape.current?.setMap(null)
    const path = (polygon ?? []).map(([lat, lng]) => ({ lat, lng }))
    shape.current = path.length >= 2 ? new google.maps.Polygon({ paths: path, map: m, strokeColor: '#0f5132', strokeWeight: 2, fillColor: '#0f5132', fillOpacity: 0.12, clickable: false }) : null
    if (path.length >= 3 && !value && !fitted.current) {
      const b = new google.maps.LatLngBounds(); path.forEach((p) => b.extend(p)); m.fitBounds(b)
    }
    if (path.length) fitted.current = true
  }, [polygon, value, ready])

  return (
    <div className="relative">
      <div ref={el} role="application" aria-label={label} className="z-0 w-full overflow-hidden rounded-control bg-canvas ring-1 ring-line" style={{ height }} />
      {failed && <p role="alert" className="absolute inset-x-2 top-2 rounded-control bg-white/95 p-2 text-xs text-warn shadow">The map could not load. You can still search for the address or type it in.</p>}
    </div>
  )
}
