import { lazy, Suspense } from 'react'
import LeafletMap from './LeafletMap'
import { MAP_PROVIDER, type MapProps } from './mapTypes'

export { googleMapsDirections, googleMapsPlace, KERALA_CENTER, MAP_PROVIDER, type MapMarker } from './mapTypes'

const GoogleMap = lazy(() => import('./GoogleMap'))

/**
 * Google Maps when VITE_GOOGLE_MAPS_BROWSER_KEY is set (required when Google search/geocoding results are
 * shown on a map), otherwise Leaflet + OpenStreetMap. Both take the same props.
 */
export function MapView(props: MapProps) {
  if (MAP_PROVIDER === 'google') {
    return <Suspense fallback={<div className="w-full rounded-control bg-canvas ring-1 ring-line" style={{ height: props.height ?? 280 }} />}><GoogleMap {...props} /></Suspense>
  }
  return <LeafletMap {...props} />
}
