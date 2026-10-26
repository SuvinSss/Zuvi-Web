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
}
/** Browser key (restricted by HTTP referrer to your site, Maps JavaScript API only). Empty = OpenStreetMap. */
export const GOOGLE_BROWSER_KEY = import.meta.env.VITE_GOOGLE_MAPS_BROWSER_KEY ?? ''
export const MAP_PROVIDER: 'google' | 'osm' = GOOGLE_BROWSER_KEY ? 'google' : 'osm'
