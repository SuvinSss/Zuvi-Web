import { useState } from "react";
import { ApiError, messageOf, patch } from "../lib/api";
import { parsePoint, toFixed6 } from "../lib/format";
import type { LocationSource, Point, ResolvedAddress, StoreLocation } from "../lib/types";
import { useMapsAvailability } from "../state/maps";
import { AddressSearch } from "./maps/AddressSearch";
import { LocationPicker } from "./maps/LocationPicker";
import { Alert, Button, Field } from "./ui";

interface Props {
  store: StoreLocation;
  endpoint: string;
  allowRadius: boolean;
  onSaved: (s: StoreLocation) => void;
}

/** Pin placement and address for a store. Used by the store portal and by admins. */
export function StoreLocationEditor({ store, endpoint, allowRadius, onSaved }: Props) {
  const maps = useMapsAvailability();
  const [point, setPoint] = useState<Point | null>(parsePoint(store.latitude, store.longitude));
  const [resolved, setResolved] = useState<ResolvedAddress | null>(null);
  const [source, setSource] = useState<LocationSource>("MAP_PIN");
  const [f, setF] = useState({
    line1: store.line1, line2: store.line2, landmark: store.landmark, city: store.city,
    district: store.district, state: store.state, postal_code: store.postal_code,
    delivery_radius_km: store.delivery_radius_km, confirm: false,
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});

  function adopt(r: ResolvedAddress) {
    setResolved(r);
    setF((p) => ({
      ...p,
      line1: p.line1 || r.line1,
      city: p.city || r.locality,
      district: p.district || r.district,
      state: p.state || r.state,
      postal_code: p.postal_code || r.postalCode,
    }));
  }

  async function save() {
    if (!point) {
      setError("Place the pin on the map first.");
      return;
    }
    setBusy(true);
    setError(null);
    setErrors({});
    const { delivery_radius_km, ...rest } = f;
    try {
      const updated = await patch<StoreLocation>(endpoint, {
        ...rest,
        latitude: toFixed6(point.lat),
        longitude: toFixed6(point.lng),
        google_place_id: resolved?.placeId ?? store.google_place_id,
        location_source: source,
        ...(allowRadius ? { delivery_radius_km } : {}),
      });
      setF((p) => ({ ...p, confirm: false }));
      onSaved(updated);
    } catch (e) {
      if (e instanceof ApiError) {
        const next: Record<string, string> = {};
        for (const k of Object.keys(e.fields)) {
          const m = e.fieldMessage(k);
          if (m) next[k] = m;
        }
        setErrors(next);
      }
      setError(messageOf(e));
    } finally {
      setBusy(false);
    }
  }

  const text = (name: "line1" | "line2" | "landmark" | "city" | "district" | "state" | "postal_code", label: string) => (
    <Field label={label} error={errors[name]}>
      {({ id, describedBy }) => (
        <input id={id} aria-describedby={describedBy} value={f[name]} onChange={(e) => setF((p) => ({ ...p, [name]: e.target.value }))} />
      )}
    </Field>
  );

  return (
    <div>
      {store.issues.map((i) => (
        <Alert kind="warn" key={i.code}>
          <strong>{i.message}</strong> {i.action}
        </Alert>
      ))}
      {store.issues.length === 0 && store.can_take_delivery_orders && (
        <Alert kind="info">This store's location is confirmed and ready for delivery orders.</Alert>
      )}
      {maps.status === "ready" && (
        <AddressSearch
          onSelect={(r) => {
            setPoint(r.point);
            setSource("PLACE_SEARCH");
            adopt(r.address);
          }}
        />
      )}
      <div style={{ marginTop: ".75rem" }}>
        <LocationPicker
          point={point}
          onChange={(p, r) => {
            setPoint(p);
            setSource("MAP_PIN");
            if (r) adopt(r);
          }}
        />
      </div>
      {point && <p className="muted">Pin: {toFixed6(point.lat)}, {toFixed6(point.lng)}</p>}
      {text("line1", "Street address")}
      {text("line2", "Building / floor (optional)")}
      {text("landmark", "Landmark (optional)")}
      {text("city", "City")}
      {text("district", "District (optional)")}
      {text("state", "State")}
      {text("postal_code", "PIN code")}
      {allowRadius && (
        <Field label="Delivery radius (km)" error={errors.delivery_radius_km}>
          {({ id }) => (
            <input id={id} inputMode="decimal" value={f.delivery_radius_km} onChange={(e) => setF((p) => ({ ...p, delivery_radius_km: e.target.value }))} />
          )}
        </Field>
      )}
      <label className="row" style={{ marginBottom: ".75rem" }}>
        <input type="checkbox" style={{ width: "auto", minHeight: 0 }} checked={f.confirm} onChange={(e) => setF((p) => ({ ...p, confirm: e.target.checked }))} />
        The pin is exactly at the store's pickup door
      </label>
      {error && <Alert>{error}</Alert>}
      <Button onClick={() => void save()} disabled={busy}>{busy ? "Saving…" : "Save location"}</Button>
    </div>
  );
}
