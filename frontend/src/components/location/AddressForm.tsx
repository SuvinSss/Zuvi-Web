import { useState, type FormEvent } from "react";
import { ApiError, messageOf, post } from "../../lib/api";
import { toFixed6 } from "../../lib/format";
import type { AddressPayload, LocationSource, Point, ResolvedAddress, SavedAddress } from "../../lib/types";
import { Alert, Button, Field } from "../ui";

interface Props {
  point: Point;
  resolved: ResolvedAddress | null;
  source: LocationSource;
  defaultName?: string;
  onSaved: (a: SavedAddress) => void;
  onCancel: () => void;
}

export function AddressForm({ point, resolved, source, defaultName = "", onSaved, onCancel }: Props) {
  const [v, setV] = useState({
    label: "HOME" as AddressPayload["label"],
    recipient_name: defaultName,
    phone_number: "",
    line1: resolved?.line1 ?? "",
    line2: "",
    landmark: "",
    city: resolved?.locality ?? "",
    district: resolved?.district ?? "",
    state: resolved?.state ?? "",
    postal_code: resolved?.postalCode ?? "",
    delivery_instructions: "",
    is_default: false,
    confirmed: false,
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  const set = <K extends keyof typeof v>(k: K, value: (typeof v)[K]) => setV((p) => ({ ...p, [k]: value }));

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setFieldErrors({});
    const { confirmed, ...rest } = v;
    const payload: AddressPayload = {
      ...rest,
      latitude: toFixed6(point.lat),
      longitude: toFixed6(point.lng),
      google_place_id: resolved?.placeId ?? "",
      location_source: source,
      location_confirmed: confirmed,
    };
    try {
      onSaved(await post<SavedAddress>("/customer/addresses/", payload));
    } catch (err) {
      if (err instanceof ApiError) {
        const next: Record<string, string> = {};
        for (const k of Object.keys(err.fields)) {
          const m = err.fieldMessage(k);
          if (m) next[k] = m;
        }
        setFieldErrors(next);
      }
      setError(messageOf(err));
    } finally {
      setBusy(false);
    }
  }

  const text = (name: keyof typeof v, label: string, extra?: { type?: string; autoComplete?: string }) => (
    <Field label={label} error={fieldErrors[name]}>
      {({ id, describedBy }) => (
        <input
          id={id}
          aria-describedby={describedBy}
          aria-invalid={Boolean(fieldErrors[name])}
          type={extra?.type ?? "text"}
          autoComplete={extra?.autoComplete}
          value={String(v[name])}
          onChange={(e) => set(name, e.target.value as never)}
        />
      )}
    </Field>
  );

  return (
    <form onSubmit={(e) => void submit(e)} noValidate>
      {resolved && !resolved.precise && (
        <Alert kind="warn">
          Google couldn't match a street address for this pin. Check the details below and add a landmark
          so the rider can find you.
        </Alert>
      )}
      {error && <Alert>{error}</Alert>}
      <Field label="Save as" error={fieldErrors.label}>
        {({ id }) => (
          <select id={id} value={v.label} onChange={(e) => set("label", e.target.value as AddressPayload["label"])}>
            <option value="HOME">Home</option>
            <option value="WORK">Work</option>
            <option value="OTHER">Other</option>
          </select>
        )}
      </Field>
      {text("recipient_name", "Name", { autoComplete: "name" })}
      {text("phone_number", "Phone number", { type: "tel", autoComplete: "tel" })}
      {text("line1", "House / street")}
      {text("line2", "Floor, building (optional)")}
      {text("landmark", "Landmark (optional)")}
      {text("city", "City")}
      {text("state", "State")}
      {text("postal_code", "PIN code", { autoComplete: "postal-code" })}
      {text("delivery_instructions", "Delivery instructions (optional)")}
      <label className="row" style={{ marginBottom: ".5rem" }}>
        <input
          type="checkbox"
          style={{ width: "auto", minHeight: 0 }}
          checked={v.is_default}
          onChange={(e) => set("is_default", e.target.checked)}
        />
        Make this my default address
      </label>
      <label className="row" style={{ marginBottom: ".75rem" }}>
        <input
          type="checkbox"
          style={{ width: "auto", minHeight: 0 }}
          checked={v.confirmed}
          onChange={(e) => set("confirmed", e.target.checked)}
        />
        The pin is at my exact delivery spot
      </label>
      {fieldErrors.location_confirmed && <p className="field-error">{fieldErrors.location_confirmed}</p>}
      <div className="row">
        <Button type="submit" disabled={busy || !v.confirmed}>
          {busy ? "Saving…" : "Save address"}
        </Button>
        <Button variant="secondary" onClick={onCancel}>
          Back
        </Button>
      </div>
    </form>
  );
}
