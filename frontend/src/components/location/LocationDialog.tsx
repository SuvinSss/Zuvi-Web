import { useState } from "react";
import { del, get, messageOf } from "../../lib/api";
import { parsePoint, shortAddress } from "../../lib/format";
import { useLoad } from "../../lib/useAsync";
import type { LocationSource, Point, ResolvedAddress, SavedAddress } from "../../lib/types";
import { useSelectedLocation } from "../../state/location";
import { useMapsAvailability } from "../../state/maps";
import { useSession } from "../../state/session";
import { AddressSearch } from "../maps/AddressSearch";
import { LocationPicker } from "../maps/LocationPicker";
import { Alert, Button, Dialog, ErrorRetry, Loading } from "../ui";
import { AddressForm } from "./AddressForm";
import { CurrentLocationButton } from "./CurrentLocationButton";

type Step = "choose" | "pin" | "form";

export function LocationDialog() {
  const { dialogOpen, closeDialog, select } = useSelectedLocation();
  if (!dialogOpen) return null;
  return (
    <Dialog title="Choose your delivery location" onClose={closeDialog}>
      <Chooser onDone={(l) => { select(l); closeDialog(); }} />
    </Dialog>
  );
}

function Chooser({ onDone }: { onDone: (l: { label: string; title: string; point: Point; addressId: number | null }) => void }) {
  const { session } = useSession();
  const maps = useMapsAvailability();
  const isCustomer = session?.authenticated === true && session.portal === "customer";
  const [step, setStep] = useState<Step>("choose");
  const [point, setPoint] = useState<Point | null>(null);
  const [resolved, setResolved] = useState<ResolvedAddress | null>(null);
  const [source, setSource] = useState<LocationSource>("MAP_PIN");
  return (
    <ChooserBody
      isCustomer={isCustomer}
      mapsReady={maps.status === "ready"}
      step={step}
      setStep={setStep}
      point={point}
      setPoint={setPoint}
      resolved={resolved}
      setResolved={setResolved}
      source={source}
      setSource={setSource}
      onDone={onDone}
      defaultName={session?.user?.name ?? ""}
    />
  );
}

interface BodyProps {
  isCustomer: boolean;
  mapsReady: boolean;
  step: Step;
  setStep: (s: Step) => void;
  point: Point | null;
  setPoint: (p: Point | null) => void;
  resolved: ResolvedAddress | null;
  setResolved: (r: ResolvedAddress | null) => void;
  source: LocationSource;
  setSource: (s: LocationSource) => void;
  onDone: (l: { label: string; title: string; point: Point; addressId: number | null }) => void;
  defaultName: string;
}

function ChooserBody(p: BodyProps) {
  const saved = useLoad(
    async () => {
      if (!p.isCustomer) return [] as SavedAddress[];
      return (await get<{ addresses: SavedAddress[] }>("/customer/addresses/")).addresses;
    },
    [p.isCustomer],
  );
  const [error, setError] = useState<string | null>(null);

  function picked(pt: Point, r: ResolvedAddress | null, src: LocationSource) {
    p.setPoint(pt);
    p.setResolved(r);
    p.setSource(src);
    p.setStep("pin");
  }

  async function remove(a: SavedAddress) {
    try {
      await del(`/customer/addresses/${a.id}/`);
      saved.reload();
    } catch (e) {
      setError(messageOf(e));
    }
  }

  if (p.step === "form" && p.point) {
    return (
      <AddressForm
        point={p.point}
        resolved={p.resolved}
        source={p.source}
        defaultName={p.defaultName}
        onCancel={() => p.setStep("pin")}
        onSaved={(a) =>
          p.onDone({
            label: a.label_display,
            title: shortAddress(a),
            point: parsePoint(a.latitude, a.longitude) ?? p.point!,
            addressId: a.id,
          })
        }
      />
    );
  }

  if (p.step === "pin" && p.point) {
    return (
      <div>
        <LocationPicker
          point={p.point}
          onChange={(pt, r) => {
            p.setPoint(pt);
            p.setResolved(r ?? p.resolved);
            p.setSource("MAP_PIN");
          }}
        />
        <p>{p.resolved?.formattedAddress ?? "Move the pin to your exact spot."}</p>
        <div className="row">
          {p.isCustomer ? (
            <Button onClick={() => p.setStep("form")}>Confirm and add details</Button>
          ) : (
            <Button
              onClick={() =>
                p.onDone({
                  label: "Selected",
                  title: p.resolved?.formattedAddress ?? "Pinned location",
                  point: p.point!,
                  addressId: null,
                })
              }
            >
              Use this location
            </Button>
          )}
          <Button variant="secondary" onClick={() => p.setStep("choose")}>
            Back
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div>
      {!p.mapsReady && (
        <Alert kind="warn">Maps and address search aren't available right now. Saved addresses still work.</Alert>
      )}
      {p.mapsReady && (
        <>
          <AddressSearch onSelect={(r) => picked(r.point, r.address, "PLACE_SEARCH")} />
          <div style={{ margin: ".75rem 0" }}>
            <CurrentLocationButton onLocate={(pt) => picked(pt, null, "CURRENT_LOCATION")} />
          </div>
        </>
      )}
      {error && <Alert>{error}</Alert>}
      <h3>Saved addresses</h3>
      {!p.isCustomer && <p className="muted">Sign in as a customer to use your saved addresses.</p>}
      {p.isCustomer && saved.loading && <Loading />}
      {p.isCustomer && saved.error && <ErrorRetry message={saved.error} onRetry={saved.reload} />}
      {p.isCustomer && saved.data && saved.data.length === 0 && (
        <p className="muted">No saved addresses yet. Search above to add one.</p>
      )}
      {saved.data?.map((a) => {
        const pt = parsePoint(a.latitude, a.longitude);
        return (
          <div className="card" key={a.id}>
            <strong>{a.label_display}</strong> {a.is_default && <span className="badge">Default</span>}
            <p className="muted">{shortAddress(a)}</p>
            <div className="row">
              <Button
                disabled={!pt}
                onClick={() =>
                  pt && p.onDone({ label: a.label_display, title: shortAddress(a), point: pt, addressId: a.id })
                }
              >
                Deliver here
              </Button>
              <Button variant="link" onClick={() => void remove(a)} aria-label={`Delete ${a.label_display} address`}>
                Delete
              </Button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
