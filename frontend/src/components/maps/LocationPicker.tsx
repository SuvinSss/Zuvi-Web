import { AdvancedMarker, Map, type MapMouseEvent } from "@vis.gl/react-google-maps";
import { useEffect, useRef, useState } from "react";
import { ApiError, post } from "../../lib/api";
import { fromServerGeocode, type ServerGeocode } from "../../lib/address";
import type { Point, ResolvedAddress } from "../../lib/types";
import { mapsUnavailableMessage, useMapsAvailability } from "../../state/maps";
import { Alert } from "../ui";

const INDIA_CENTER: Point = { lat: 20.5937, lng: 78.9629 };

interface Props {
  point: Point | null;
  onChange: (p: Point, resolved: ResolvedAddress | null) => void;
  height?: number;
}

/**
 * Pin picker. The pin can be dragged or the map clicked; each move is looked up
 * through the backend (debounced) so the readable address stays in step with it.
 * If the lookup fails the position is still kept: the user can type the address.
 */
export function LocationPicker({ point, onChange, height = 320 }: Props) {
  const maps = useMapsAvailability();
  const [lookupError, setLookupError] = useState<string | null>(null);
  const [looking, setLooking] = useState(false);
  const timer = useRef<number | undefined>(undefined);
  const seq = useRef(0);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  function moved(p: Point) {
    onChange(p, null);
    window.clearTimeout(timer.current);
    const mine = ++seq.current;
    timer.current = window.setTimeout(async () => {
      setLooking(true);
      try {
        const g = await post<ServerGeocode>("/geo/reverse-geocode/", {
          latitude: p.lat.toFixed(6),
          longitude: p.lng.toFixed(6),
        });
        if (mine !== seq.current) return;
        setLookupError(null);
        onChange(p, fromServerGeocode(g).address);
      } catch (e) {
        if (mine !== seq.current) return;
        setLookupError(
          e instanceof ApiError && e.status === 401
            ? "Sign in to look up the address for this pin. You can still type it."
            : "We couldn't find an address for this pin. Move it or type the address yourself.",
        );
      } finally {
        if (mine === seq.current) setLooking(false);
      }
    }, 500);
  }

  if (maps.status !== "ready") {
    return maps.status === "loading" ? (
      <p className="muted" role="status">Loading map…</p>
    ) : (
      <Alert kind="warn">{mapsUnavailableMessage(maps)}</Alert>
    );
  }

  const center = point ?? INDIA_CENTER;
  return (
    <div>
      <div className="map-box" style={{ height }} data-testid="location-map">
        <Map
          mapId={maps.mapId}
          defaultCenter={center}
          center={point ?? undefined}
          defaultZoom={point ? 17 : 5}
          gestureHandling="greedy"
          disableDefaultUI
          zoomControl
          onClick={(e: MapMouseEvent) => {
            const ll = e.detail.latLng;
            if (ll) moved({ lat: ll.lat, lng: ll.lng });
          }}
        >
          {point && (
            <AdvancedMarker
              position={point}
              draggable
              title="Drag to your exact location"
              onDragEnd={(e) => {
                const ll = e.latLng;
                if (ll) moved({ lat: ll.lat(), lng: ll.lng() });
              }}
            />
          )}
        </Map>
      </div>
      <p className="muted" aria-live="polite">
        {looking ? "Looking up the address…" : "Drag the pin or tap the map to set your exact spot."}
      </p>
      {lookupError && <Alert kind="warn">{lookupError}</Alert>}
    </div>
  );
}
