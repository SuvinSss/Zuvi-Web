import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { useEffect, useRef } from 'react'

// Tiles: set VITE_MAP_TILE_URL / VITE_MAP_ATTRIBUTION to a tile service you are licensed to use.
// The OpenStreetMap default is fine for development and light use only (see its tile usage policy).
const TILE_URL = import.meta.env.VITE_MAP_TILE_URL || 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
const ATTRIBUTION = import.meta.env.VITE_MAP_ATTRIBUTION || '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
import { KERALA_CENTER, type MapProps } from './mapTypes'

const pinIcon = (color: string) => L.divIcon({
  className: '',
  html: `<span style="display:block;width:28px;height:28px;border-radius:50% 50% 50% 0;background:${color};transform:rotate(-45deg);border:3px solid #fff;box-shadow:0 2px 6px rgba(0,0,0,.35)"></span>`,
  iconSize: [28, 28], iconAnchor: [14, 28],
})

/**
 * Small Leaflet wrapper. A draggable pin (``value``/``onPinChange``), extra read-only markers,
 * an optional polygon and click handling (for drawing zones).
 */
export default function LeafletMap({ value, onPinChange, markers = [], polygon, onMapClick, height = 280, label = 'Map', zoom = 15 }: MapProps) {
  const el = useRef<HTMLDivElement>(null)
  const map = useRef<L.Map | null>(null)
  const pin = useRef<L.Marker | null>(null)
  const extras = useRef<L.LayerGroup | null>(null)
  const shape = useRef<L.Polygon | null>(null)
  const fitted = useRef(false)
  const pinCb = useRef(onPinChange)
  const clickCb = useRef(onMapClick)
  useEffect(() => { pinCb.current = onPinChange; clickCb.current = onMapClick })

  useEffect(() => {
    if (!el.current || map.current) return
    const m = L.map(el.current, { center: value ? [value.lat, value.lon] : KERALA_CENTER, zoom: value ? zoom : 8, scrollWheelZoom: false })
    L.tileLayer(TILE_URL, { attribution: ATTRIBUTION, maxZoom: 19 }).addTo(m)
    extras.current = L.layerGroup().addTo(m)
    m.on('click', (e: L.LeafletMouseEvent) => {
      if (clickCb.current) clickCb.current(e.latlng.lat, e.latlng.lng)
      else if (pinCb.current) pinCb.current(e.latlng.lat, e.latlng.lng)
    })
    map.current = m
    return () => { m.stop(); m.off(); m.remove(); map.current = null; pin.current = null }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    const m = map.current
    if (!m) return
    if (!value) { pin.current?.remove(); pin.current = null; return }
    const ll: L.LatLngExpression = [value.lat, value.lon]
    if (!pin.current) {
      pin.current = L.marker(ll, { draggable: Boolean(pinCb.current), icon: pinIcon('#0f5132'), keyboard: true, title: 'Delivery location' }).addTo(m)
      pin.current.on('dragend', () => { const p = pin.current!.getLatLng(); pinCb.current?.(p.lat, p.lng) })
      m.setView(ll, Math.max(m.getZoom(), zoom), { animate: false })
    } else {
      pin.current.setLatLng(ll)
      if (!m.getBounds().contains(ll)) m.panTo(ll, { animate: false })
    }
  }, [value, zoom])

  useEffect(() => {
    const group = extras.current
    if (!group) return
    group.clearLayers()
    markers.forEach((mk) => L.marker([mk.lat, mk.lon], { icon: pinIcon(mk.color ?? '#b45309'), title: mk.label }).bindTooltip(mk.label ?? '').addTo(group))
  }, [markers])

  useEffect(() => {
    const m = map.current
    if (!m) return
    shape.current?.remove()
    shape.current = polygon && polygon.length >= 2 ? L.polygon(polygon, { color: '#0f5132', weight: 2, fillOpacity: 0.12 }).addTo(m) : null
    // Fit once (an existing zone being edited); never re-fit while the person is adding points.
    if (polygon && polygon.length >= 3 && !value && !fitted.current) { fitted.current = true; m.fitBounds(L.latLngBounds(polygon), { maxZoom: 15, animate: false }) }
    if (polygon && polygon.length > 0) fitted.current = true
  }, [polygon, value])

  return <div ref={el} role="application" aria-label={label} className="z-0 w-full overflow-hidden rounded-control ring-1 ring-line" style={{ height }} />
}
