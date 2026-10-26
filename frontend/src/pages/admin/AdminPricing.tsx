import { useState, type FormEvent } from "react";
import { LocationPicker } from "../../components/maps/LocationPicker";
import { Alert, Button, ErrorRetry, Field, Loading } from "../../components/ui";
import { ApiError, get, messageOf, post } from "../../lib/api";
import { money, toFixed6 } from "../../lib/format";
import { useLoad } from "../../lib/useAsync";
import type { Point, PricingConfig, SimulationResult, StoreLocation } from "../../lib/types";

const FIELDS: [string, string][] = [
  ["fuel_price_per_litre", "Fuel price per litre"],
  ["vehicle_mileage_km_per_litre", "Vehicle mileage (km/l)"],
  ["maintenance_cost_per_km", "Maintenance per km"],
  ["operational_distance_multiplier", "Distance multiplier"],
  ["minimum_operational_distance_km", "Minimum operational distance (km)"],
  ["rider_base_payout", "Rider base payout"],
  ["rider_payout_per_km", "Rider payout per km"],
  ["other_cost_per_delivery", "Other cost per delivery"],
  ["customer_base_fee", "Customer base fee"],
  ["customer_free_distance_km", "Free distance (km)"],
  ["customer_fee_per_km", "Customer fee per km"],
  ["customer_minimum_fee", "Customer minimum fee"],
  ["customer_maximum_fee", "Customer maximum fee (blank = none)"],
  ["fee_rounding_step", "Round fee up to nearest"],
  ["free_delivery_threshold", "Free delivery above (blank = never)"],
  ["store_funded_discount_percent", "Store-funded discount %"],
  ["max_road_distance_km", "Maximum road distance (km)"],
];

function ConfigForm({ initial, onSaved }: { initial: PricingConfig | null; onSaved: () => void }) {
  const [v, setV] = useState<Record<string, string>>(() =>
    Object.fromEntries(FIELDS.map(([k]) => [k, initial?.[k] == null ? "" : String(initial[k])])),
  );
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setErrors({});
    const body: Record<string, string | null> = { name };
    for (const [k] of FIELDS) {
      const raw = v[k]?.trim() ?? "";
      if (raw !== "") body[k] = raw;
      else if (k === "customer_maximum_fee" || k === "free_delivery_threshold") body[k] = null;
    }
    try {
      await post("/admin/pricing/configs/", body);
      onSaved();
    } catch (err) {
      if (err instanceof ApiError) {
        const next: Record<string, string> = {};
        for (const k of Object.keys(err.fields)) {
          const m = err.fieldMessage(k);
          if (m) next[k] = m;
        }
        setErrors(next);
      }
      setError(messageOf(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={(e) => void submit(e)} noValidate>
      {error && <Alert>{error}</Alert>}
      <Field label="Version note">
        {({ id }) => <input id={id} value={name} maxLength={100} onChange={(e) => setName(e.target.value)} />}
      </Field>
      <div className="grid">
        {FIELDS.map(([k, label]) => (
          <Field key={k} label={label} error={errors[k]}>
            {({ id, describedBy }) => (
              <input id={id} aria-describedby={describedBy} inputMode="decimal" value={v[k] ?? ""} onChange={(e) => setV((p) => ({ ...p, [k]: e.target.value }))} />
            )}
          </Field>
        ))}
      </div>
      <Button type="submit" disabled={busy}>{busy ? "Saving…" : "Save as new active version"}</Button>
    </form>
  );
}

function Simulator() {
  const stores = useLoad(async () => (await get<{ stores: StoreLocation[] }>("/admin/stores/locations/")).stores);
  const [storeId, setStoreId] = useState("");
  const [point, setPoint] = useState<Point | null>(null);
  const [subtotal, setSubtotal] = useState("300");
  const [result, setResult] = useState<SimulationResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(refresh: boolean) {
    if (!point || !storeId) return;
    setBusy(true);
    setError(null);
    try {
      setResult(
        await post<SimulationResult>("/admin/pricing/simulate/", {
          store_id: Number(storeId),
          latitude: toFixed6(point.lat),
          longitude: toFixed6(point.lng),
          items_subtotal: subtotal,
          refresh,
        }),
      );
    } catch (e) {
      setResult(null);
      setError(messageOf(e));
    } finally {
      setBusy(false);
    }
  }

  const p = result?.pricing;
  return (
    <section className="card">
      <h2>Pricing simulator</h2>
      <p className="muted">Uses the same route lookup and price calculation as checkout. Costs one Routes request unless cached.</p>
      <Field label="Store">
        {({ id }) => (
          <select id={id} value={storeId} onChange={(e) => setStoreId(e.target.value)}>
            <option value="">Choose a store</option>
            {stores.data?.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
        )}
      </Field>
      <Field label="Basket subtotal (₹)">
        {({ id }) => <input id={id} inputMode="decimal" value={subtotal} onChange={(e) => setSubtotal(e.target.value)} />}
      </Field>
      <LocationPicker point={point} onChange={(pt) => setPoint(pt)} height={260} />
      <div className="row" style={{ margin: ".75rem 0" }}>
        <Button onClick={() => void run(false)} disabled={busy || !point || !storeId}>{busy ? "Calculating…" : "Simulate"}</Button>
        {result && <Button variant="secondary" onClick={() => void run(true)} disabled={busy}>Bypass cache</Button>}
      </div>
      {error && <Alert>{error}</Alert>}
      {result && p && (
        <div aria-live="polite">
          <p>
            Route: <strong>{result.route.distance_km} km</strong> ·{" "}
            {Math.round(result.route.duration_seconds / 60)} min ·{" "}
            <span className={`badge ${result.route.is_live ? "live" : "cached"}`}>{result.route.source}</span>{" "}
            <span className="muted">{result.route.travel_mode}</span>
          </p>
          {!result.serviceability.eligible && (
            <Alert kind="warn">Not serviceable: {result.serviceability.reasons.map((r) => r.message).join(" ")}</Alert>
          )}
          <table>
            <tbody>
              <tr><th scope="row">Customer fee (before discount)</th><td>{money(p.customer_fee_before_discount)}</td></tr>
              <tr><th scope="row">Discount</th><td>{money(p.discount)}</td></tr>
              <tr><th scope="row">Customer pays</th><td><strong>{money(p.customer_fee)}</strong></td></tr>
              <tr><th scope="row">Operational cost (internal)</th><td>{money(p.operational_cost)}</td></tr>
              <tr><th scope="row">Rider payout (internal)</th><td>{money(p.rider_payout)}</td></tr>
              <tr><th scope="row">Platform subsidy (internal)</th><td>{money(p.platform_subsidy)}</td></tr>
              <tr><th scope="row">Unrecovered cost (internal)</th><td>{money(p.unrecovered_cost)}</td></tr>
              <tr><th scope="row">Contribution (internal)</th><td>{money(p.contribution)}</td></tr>
            </tbody>
          </table>
          <p className="muted">Pricing version {result.pricing_version}</p>
        </div>
      )}
    </section>
  );
}

export function AdminPricing() {
  const cfg = useLoad(async () => (await get<{ configs: PricingConfig[] }>("/admin/pricing/configs/")).configs);
  const [creating, setCreating] = useState(false);
  if (cfg.loading && !cfg.data) return <Loading />;
  if (cfg.error) return <ErrorRetry message={cfg.error} onRetry={cfg.reload} />;
  const active = cfg.data?.find((c) => c.is_active) ?? null;
  return (
    <div>
      <h1>Delivery pricing</h1>
      {!active && <Alert kind="warn">No active pricing config. Delivery quotes can't be created until you add one.</Alert>}
      <section className="card">
        <h2>{active ? `Active: version ${active.version}` : "Create the first version"}</h2>
        <p className="muted">Versions are never edited. Saving creates a new active version; existing orders keep their saved fee.</p>
        {creating || !active ? (
          <ConfigForm initial={active} onSaved={() => { setCreating(false); cfg.reload(); }} />
        ) : (
          <Button onClick={() => setCreating(true)}>Create new version</Button>
        )}
      </section>
      <Simulator />
      <section className="card table-wrap">
        <h2>History</h2>
        <table>
          <thead><tr><th>Version</th><th>Created</th><th>Active</th></tr></thead>
          <tbody>
            {cfg.data?.map((c) => (
              <tr key={c.id}><td>{c.version}{c.name ? ` · ${c.name}` : ""}</td><td>{new Date(c.created_at).toLocaleString("en-IN")}</td><td>{c.is_active ? "Yes" : ""}</td></tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
