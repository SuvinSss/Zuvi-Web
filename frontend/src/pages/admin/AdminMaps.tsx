import { useState } from "react";
import { Alert, Button, ErrorRetry, Loading } from "../../components/ui";
import { get, messageOf, post } from "../../lib/api";
import { formatDateTime } from "../../lib/format";
import { useLoad } from "../../lib/useAsync";
import type { HealthEntry, MapsStatus } from "../../lib/types";

const yesNo = (v: boolean) => (v ? "Present" : "Missing");

function Health({ name, h }: { name: string; h: HealthEntry }) {
  return (
    <div className="card">
      <h2>{name}</h2>
      {h.ok === null ? (
        <p className="muted">Never checked.</p>
      ) : (
        <>
          <span className={`badge ${h.ok ? "live" : ""}`}>{h.ok ? "Working" : `Failed: ${h.error_code}`}</span>
          <p>{h.message}</p>
          <p className="muted">Checked {formatDateTime(h.checked_at)}{h.latency_ms !== null && ` · ${h.latency_ms} ms`}</p>
        </>
      )}
      <p className="muted">Last success: {formatDateTime(h.last_success_at)}</p>
    </div>
  );
}

export function AdminMaps() {
  const s = useLoad(() => get<MapsStatus>("/admin/maps/status/"));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function check() {
    setBusy(true);
    setError(null);
    try {
      await post("/admin/maps/health-check/");
      s.reload();
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setBusy(false);
    }
  }

  if (s.loading && !s.data) return <Loading />;
  if (s.error) return <ErrorRetry message={s.error} onRetry={s.reload} />;
  if (!s.data) return null;
  const c = s.data.configuration;
  return (
    <div>
      <h1>Google Maps status</h1>
      <Alert kind="info">
        “Present” only means a value is set. Run the health check to see whether Google accepts the key.
        Each check makes one small paid request per service.
      </Alert>
      <div className="card">
        <table>
          <tbody>
            <tr><th scope="row">Browser key</th><td>{yesNo(c.browser_key_present)}</td></tr>
            <tr><th scope="row">Server key</th><td>{yesNo(c.server_key_present)}</td></tr>
            <tr><th scope="row">Map ID</th><td>{yesNo(c.map_id_present)}</td></tr>
            <tr><th scope="row">Region / language</th><td>{c.region} / {c.language}</td></tr>
            <tr><th scope="row">Travel mode</th><td>{c.travel_mode}</td></tr>
            <tr><th scope="row">Route cache</th><td>{c.route_cache_ttl_seconds ? `${c.route_cache_ttl_seconds} s` : "off"}</td></tr>
            <tr><th scope="row">Address Validation</th><td>{c.address_validation_enabled ? "On" : "Off"}</td></tr>
            <tr><th scope="row">Delivery quotes enforced</th><td>{c.delivery_quotes_enforced ? "Yes" : "No"}</td></tr>
            <tr><th scope="row">Active pricing config</th><td>{s.data.pricing_configured ? "Yes" : "None: create one under Delivery pricing"}</td></tr>
          </tbody>
        </table>
      </div>
      {error && <Alert>{error}</Alert>}
      <Button onClick={() => void check()} disabled={busy}>{busy ? "Checking…" : "Run health check"}</Button>
      <div className="grid" style={{ marginTop: "1rem" }}>
        <Health name="Geocoding" h={s.data.health.GEOCODING} />
        <Health name="Routes" h={s.data.health.ROUTES} />
      </div>
      <p className="muted">Setup and troubleshooting guides are in the repository under <code>{s.data.docs.setup}</code> and <code>{s.data.docs.troubleshooting}</code>.</p>
    </div>
  );
}
