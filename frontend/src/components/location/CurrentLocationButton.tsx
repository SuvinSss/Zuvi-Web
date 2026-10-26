import { useState } from "react";
import type { Point } from "../../lib/types";
import { Button } from "../ui";

export const MAX_ACCURACY_METERS = 100;

export function geolocationMessage(code: number | "unsupported"): string {
  switch (code) {
    case "unsupported":
      return "This device can't share its location. Search for your address instead.";
    case 1:
      return "Location permission was denied. Allow it in your browser settings, or search for your address.";
    case 2:
      return "Your location isn't available right now. Search for your address instead.";
    case 3:
      return "Finding your location took too long. Try again or search for your address.";
    default:
      return "We couldn't get your location. Search for your address instead.";
  }
}

interface Props {
  onLocate: (p: Point, accuracyMeters: number) => void;
}

export function CurrentLocationButton({ onLocate }: Props) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  function locate() {
    if (!("geolocation" in navigator)) {
      setMessage(geolocationMessage("unsupported"));
      return;
    }
    setBusy(true);
    setMessage(null);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setBusy(false);
        if (pos.coords.accuracy > MAX_ACCURACY_METERS) {
          setMessage(
            `Your location is only accurate to about ${Math.round(pos.coords.accuracy)} m. Drag the pin to your exact spot.`,
          );
        }
        onLocate({ lat: pos.coords.latitude, lng: pos.coords.longitude }, pos.coords.accuracy);
      },
      (err) => {
        setBusy(false);
        setMessage(geolocationMessage(err.code));
      },
      { enableHighAccuracy: true, timeout: 10_000, maximumAge: 30_000 },
    );
  }

  return (
    <div>
      <Button variant="secondary" onClick={locate} disabled={busy}>
        {busy ? "Finding you…" : "Use my current location"}
      </Button>
      {message && (
        <p className="muted" role="status">
          {message}
        </p>
      )}
    </div>
  );
}
