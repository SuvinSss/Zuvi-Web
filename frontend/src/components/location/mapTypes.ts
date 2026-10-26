export const KERALA_CENTER: [number, number] = [10.1632, 76.6413]
export interface MapMarker { lat: number; lon: number; label?: string; color?: string }
export interface MapProps {
  value?: { lat: number; lon: number } | null
  onPinChange?: (lat: number, lon: number) => void
  markers?: MapMarker[]
  polygon?: [number, number][]
  onMapClick?: (lat: number, lon: number) => void
  height?: number
  label?: string
  zoom?: number
  /** 'greedy' when the map is the main control (picking a pin on a phone); 'cooperative' when it sits in a scrolling page. */
  gesture?: 'cooperative' | 'greedy'
  /** Zoom to show every marker (tracking, rider job). */
  fitToMarkers?: boolean
}
/** Browser key (restricted by HTTP referrer to your site, Maps JavaScript API only). Empty = OpenStreetMap. */
export const GOOGLE_BROWSER_KEY = import.meta.env.VITE_GOOGLE_MAPS_BROWSER_KEY ?? ''
/** Optional Map ID (Map Management). Enables Google's Advanced Markers and cloud styling. */
export const GOOGLE_MAP_ID = import.meta.env.VITE_GOOGLE_MAPS_MAP_ID ?? ''
export const MAP_PROVIDER: 'google' | 'osm' = GOOGLE_BROWSER_KEY ? 'google' : 'osm'

/** The backend can also supply the (public, referrer-restricted) browser key, so no rebuild is needed to switch to Google. */
const runtime = { key: '', mapId: '', loaded: false }
const listeners = new Set<() => void>()
export const googleKey = () => GOOGLE_BROWSER_KEY || runtime.key
export const googleMapId = () => GOOGLE_MAP_ID || runtime.mapId
export const runtimeConfigLoaded = () => Boolean(GOOGLE_BROWSER_KEY) || runtime.loaded
export const subscribeMapConfig = (fn: () => void) => { listeners.add(fn); return () => { listeners.delete(fn) } }
export const mapConfigVersion = () => `${runtime.loaded}|${runtime.key}|${runtime.mapId}`
export function setRuntimeMapConfig(key: string, mapId: string) {
  runtime.key = key; runtime.mapId = mapId; runtime.loaded = true
  listeners.forEach((fn) => fn())
}

/** Links that open Google Maps (web or the app on phones). No key needed. */
export const googleMapsPlace = (lat: number | string, lon: number | string) => `https://www.google.com/maps/search/?api=1&query=${lat},${lon}`
export const googleMapsDirections = (dest: [number | string, number | string], origin?: [number | string, number | string] | null, mode: 'two-wheeler' | 'driving' = 'two-wheeler') =>
  `https://www.google.com/maps/dir/?api=1&destination=${dest[0]},${dest[1]}${origin ? `&origin=${origin[0]},${origin[1]}` : ''}&travelmode=${mode}`
