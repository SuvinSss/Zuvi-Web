import { useMapsLibrary } from "@vis.gl/react-google-maps";
import { useEffect, useId, useRef, useState } from "react";
import { fromPlaceComponents } from "../../lib/address";
import type { Point, ResolvedAddress } from "../../lib/types";

interface Suggestion {
  text: string;
  pick: () => Promise<{ point: Point; address: ResolvedAddress } | null>;
}

interface Props {
  onSelect: (r: { point: Point; address: ResolvedAddress }) => void;
  region?: string;
}

/**
 * Places (New) autocomplete. One session token covers the typing plus the final
 * place-details call, then a new token starts, which is how Google bills a session.
 */
export function AddressSearch({ onSelect, region = "in" }: Props) {
  const places = useMapsLibrary("places");
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<Suggestion[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const token = useRef<google.maps.places.AutocompleteSessionToken | null>(null);
  const seq = useRef(0);
  const listId = useId();
  const visible = query.trim().length >= 3 ? items : [];

  useEffect(() => {
    if (!places) return;
    const text = query.trim();
    if (text.length < 3) return;
    const mine = ++seq.current;
    const timer = window.setTimeout(async () => {
      try {
        setBusy(true);
        token.current ??= new places.AutocompleteSessionToken();
        const { suggestions } = await places.AutocompleteSuggestion.fetchAutocompleteSuggestions({
          input: text,
          sessionToken: token.current,
          includedRegionCodes: [region],
        });
        if (mine !== seq.current) return; // a newer keystroke superseded this response
        setError(null);
        setItems(
          suggestions.flatMap((s) => {
            const p = s.placePrediction;
            if (!p) return [];
            return [
              {
                text: p.text.text,
                pick: async () => {
                  const place = p.toPlace();
                  await place.fetchFields({
                    fields: ["location", "formattedAddress", "addressComponents", "id"],
                  });
                  const loc = place.location;
                  if (!loc) return null;
                  return {
                    point: { lat: loc.lat(), lng: loc.lng() },
                    address: fromPlaceComponents(
                      place.id,
                      place.formattedAddress ?? p.text.text,
                      (place.addressComponents ?? []).map((c) => ({ longText: c.longText, types: c.types })),
                    ),
                  };
                },
              },
            ];
          }),
        );
      } catch {
        if (mine === seq.current) {
          setItems([]);
          setError("Address search isn't working right now. Place the pin on the map or type the address.");
        }
      } finally {
        if (mine === seq.current) setBusy(false);
      }
    }, 300);
    return () => window.clearTimeout(timer);
  }, [query, places, region]);

  async function choose(s: Suggestion) {
    try {
      setBusy(true);
      const result = await s.pick();
      token.current = null; // the session ends with the place-details call
      if (!result) {
        setError("We couldn't find the exact spot for that result. Try another or use the map.");
        return;
      }
      setItems([]);
      setQuery(result.address.formattedAddress);
      setError(null);
      onSelect(result);
    } catch {
      setError("We couldn't load that place. Try another result.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <label htmlFor={`${listId}-input`} className="sr-only">
        Search for your address
      </label>
      <input
        id={`${listId}-input`}
        type="search"
        role="combobox"
        aria-expanded={visible.length > 0}
        aria-controls={listId}
        aria-autocomplete="list"
        autoComplete="off"
        placeholder="Search for area, street or landmark"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      {busy && <span className="sr-only" role="status">Searching…</span>}
      {error && <p className="field-error" role="alert">{error}</p>}
      {visible.length > 0 && (
        <ul className="suggestions" id={listId} role="listbox">
          {visible.map((s, i) => (
            <li key={`${i}-${s.text}`} role="option" aria-selected={false}>
              <button type="button" onClick={() => void choose(s)}>
                {s.text}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
