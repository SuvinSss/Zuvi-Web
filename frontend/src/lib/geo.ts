export interface Fix { latitude: string; longitude: string; accuracy_m: number | null }

/** One-shot position. Rejects with a human message; never invents coordinates. */
export function currentPosition(): Promise<Fix> {
  return new Promise((resolve, reject) => {
    if (!('geolocation' in navigator)) { reject(new Error('This device cannot share its location.')); return }
    navigator.geolocation.getCurrentPosition(
      (p) => resolve({ latitude: p.coords.latitude.toFixed(6), longitude: p.coords.longitude.toFixed(6), accuracy_m: Number.isFinite(p.coords.accuracy) ? Math.round(p.coords.accuracy) : null }),
      (e) => reject(new Error(e.code === e.PERMISSION_DENIED ? 'Location permission is blocked. Allow location access in your browser settings and try again.' : 'We could not get your location. Move to an open area and try again.')),
      { enableHighAccuracy: true, timeout: 15000, maximumAge: 5000 },
    )
  })
}

export const mapsLink = (lat: number | string | null | undefined, lon: number | string | null | undefined) =>
  lat === null || lat === undefined || lon === null || lon === undefined ? null : `https://www.google.com/maps/dir/?api=1&destination=${lat},${lon}`
