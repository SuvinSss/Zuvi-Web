import { lazy, Suspense, useEffect, useSyncExternalStore } from 'react'
import { geoConfig } from '@/services/delivery'
import LeafletMap from './LeafletMap'
import { googleKey, mapConfigVersion, runtimeConfigLoaded, setRuntimeMapConfig, subscribeMapConfig, type MapProps } from './mapTypes'

export { googleMapsDirections, googleMapsPlace, KERALA_CENTER, MAP_PROVIDER, type MapMarker } from './mapTypes'

const GoogleMap = lazy(() => import('./GoogleMap'))

let configRequest: Promise<void> | null = null
/** Ask the backend once for the browser key (when the build has none). Failure just means OpenStreetMap. */
function loadRuntimeConfig() {
  configRequest ??= geoConfig()
    .then((c) => setRuntimeMapConfig(c.browser_key ?? '', c.map_id ?? ''))
    .catch(() => setRuntimeMapConfig('', ''))
  return configRequest
}

/**
 * Google Maps when a browser key is available, otherwise Leaflet + OpenStreetMap. The key comes from
 * VITE_GOOGLE_MAPS_BROWSER_KEY at build time, or from the backend (GOOGLE_MAPS_BROWSER_KEY) at run time.
 * Both map kinds take the same props.
 */
export function MapView(props: MapProps) {
  useSyncExternalStore(subscribeMapConfig, mapConfigVersion)
  const loaded = runtimeConfigLoaded()
  useEffect(() => { if (!loaded) void loadRuntimeConfig() }, [loaded])
  const box = <div className="w-full rounded-control bg-canvas ring-1 ring-line" style={{ height: props.height ?? 280 }} />
  if (!loaded) return box
  if (googleKey()) {
    return <Suspense fallback={box}><GoogleMap {...props} /></Suspense>
  }
  return <LeafletMap {...props} />
}
