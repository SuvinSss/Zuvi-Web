import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { QueryBoundary, Status, useToast } from '@/components/kit'
import { Alert, Button, Card, PageHeader } from '@/components/ui'
import { errorMessage } from '@/lib/api'
import { formatDateTime } from '@/lib/format'
import { GOOGLE_MAP_ID, MAP_PROVIDER } from '@/components/location/mapTypes'
import { mapsStatus, runMapsHealthCheck, type MapsCheck, type MapsService } from '@/services/delivery'

const SERVICES: { key: MapsService; name: string; note: string }[] = [
  { key: 'PLACES', name: 'Places (address search)', note: 'Suggestions while a customer types an address.' },
  { key: 'GEOCODING', name: 'Geocoding (address from pin)', note: 'Turns a dropped pin or GPS fix into an address.' },
  { key: 'ROUTES', name: 'Routes (road distance)', note: 'Road distance used to price delivery.' },
]

function CheckResult({ check, lastSuccess }: { check: MapsCheck | null; lastSuccess: string | null }) {
  if (!check) return <p className="text-sm text-muted">Never checked.</p>
  return (
    <div className="space-y-1 text-sm">
      <Status value={check.ok ? 'ACTIVE' : 'REJECTED'} label={check.ok ? 'Working' : `Failed: ${check.error_code.toLowerCase().replace(/_/g, ' ')}`} />
      <p>{check.message}</p>
      <p className="text-muted">Checked {formatDateTime(check.checked_at)}{check.latency_ms !== null && ` · ${check.latency_ms} ms`}</p>
      <p className="text-muted">Last success: {lastSuccess ? formatDateTime(lastSuccess) : 'never'}</p>
    </div>
  )
}

export default function MapsStatusPage() {
  const qc = useQueryClient()
  const toast = useToast()
  const q = useQuery({ queryKey: ['maps-status'], queryFn: mapsStatus })
  const run = useMutation({
    mutationFn: runMapsHealthCheck,
    onSuccess: () => { toast('success', 'Health check finished.'); void qc.invalidateQueries({ queryKey: ['maps-status'] }) },
    onError: (e) => toast('error', errorMessage(e)),
  })
  const c = q.data?.configuration
  return (
    <div className="space-y-5">
      <PageHeader title="Google Maps status" subtitle="Whether the Google services behind address search, maps and delivery distance are set up and answering." />
      <QueryBoundary query={q} skeleton="detail">
        {q.data && c && (
          <>
            <Alert tone="info" title="What these checks mean">
              “Key present” only means a value is set. A health check makes one small paid request per service, so use it after changing keys or restrictions, not on a timer.
            </Alert>
            <Card className="space-y-2 p-4">
              <h2 className="text-lg font-semibold text-forest">Configuration</h2>
              <dl className="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
                <div className="flex justify-between"><dt className="text-muted">Server key</dt><dd>{c.server_key_present ? 'Present' : 'Missing'}</dd></div>
                <div className="flex justify-between"><dt className="text-muted">Address search / lookup</dt><dd>{c.geocoder}</dd></div>
                <div className="flex justify-between"><dt className="text-muted">Road distance</dt><dd>{c.router}</dd></div>
                <div className="flex justify-between"><dt className="text-muted">Travel mode</dt><dd>{c.travel_mode}</dd></div>
                <div className="flex justify-between"><dt className="text-muted">Request timeout</dt><dd>{c.timeout_seconds} s</dd></div>
                <div className="flex justify-between"><dt className="text-muted">Store pins must be confirmed</dt><dd>{c.store_pin_confirmation_required ? 'Yes' : 'No'}</dd></div>
              </dl>
              {(c.geocoder !== 'google' || c.router !== 'google') && (
                <Alert tone="warn">Google is not fully switched on. Set GOOGLE_MAPS_SERVER_KEY, LOCATION_GEOCODER=google and LOCATION_ROUTER=google. Until then distances are labelled estimates.</Alert>
              )}
            </Card>
            <Card className="space-y-1 p-4">
              <h2 className="text-lg font-semibold text-forest">Website map (this build)</h2>
              <p className="text-sm" data-testid="website-map">{MAP_PROVIDER === 'google' ? `Google Maps${GOOGLE_MAP_ID ? ' with a Map ID (Advanced Markers)' : ' (classic markers; add VITE_GOOGLE_MAPS_MAP_ID for Advanced Markers)'}` : 'OpenStreetMap. This build has no web key, so Google Maps is not used on the website.'}</p>
              {MAP_PROVIDER !== 'google' && <Alert tone="warn">Set VITE_GOOGLE_MAPS_BROWSER_KEY in frontend/.env and rebuild (or restart npm run dev). The key is read when the site is built, not at runtime.</Alert>}
            </Card>
            <div className="flex items-center gap-3">
              <Button onClick={() => run.mutate()} disabled={run.isPending}>{run.isPending ? 'Checking…' : 'Run health check'}</Button>
              <span className="text-sm text-muted">Uses a little Google quota.</span>
            </div>
            <div className="grid gap-4 lg:grid-cols-3">
              {SERVICES.map((svc) => (
                <Card key={svc.key} className="space-y-2 p-4">
                  <h3 className="font-semibold text-forest">{svc.name}</h3>
                  <p className="text-xs text-muted">{svc.note}</p>
                  <CheckResult check={q.data.checks[svc.key].latest} lastSuccess={q.data.checks[svc.key].last_success_at} />
                </Card>
              ))}
            </div>
          </>
        )}
      </QueryBoundary>
    </div>
  )
}
