import type { Point, ResolvedAddress } from "./types";

export interface ServerGeocode {
  formatted_address: string;
  place_id: string;
  latitude: string;
  longitude: string;
  precise: boolean;
  components: {
    line1: string;
    locality: string;
    district: string;
    state: string;
    postal_code: string;
  };
}

export function fromServerGeocode(g: ServerGeocode): { point: Point; address: ResolvedAddress } {
  return {
    point: { lat: Number(g.latitude), lng: Number(g.longitude) },
    address: {
      formattedAddress: g.formatted_address,
      placeId: g.place_id,
      precise: g.precise,
      line1: g.components.line1,
      locality: g.components.locality,
      district: g.components.district,
      state: g.components.state,
      postalCode: g.components.postal_code,
    },
  };
}

interface PlaceComponent {
  longText?: string | null;
  types: string[];
}

const pick = (parts: PlaceComponent[], ...types: string[]): string => {
  for (const t of types) {
    const hit = parts.find((p) => p.types.includes(t));
    if (hit?.longText) return hit.longText;
  }
  return "";
};

/** Build a ResolvedAddress from a Places (New) place's address components. */
export function fromPlaceComponents(
  placeId: string,
  formattedAddress: string,
  parts: PlaceComponent[],
): ResolvedAddress {
  const street = [pick(parts, "street_number"), pick(parts, "route")].filter(Boolean).join(" ");
  return {
    formattedAddress,
    placeId,
    precise: Boolean(street || pick(parts, "premise", "subpremise")),
    line1: street || pick(parts, "premise", "sublocality_level_1", "sublocality"),
    locality: pick(parts, "locality", "administrative_area_level_3"),
    district: pick(parts, "administrative_area_level_2"),
    state: pick(parts, "administrative_area_level_1"),
    postalCode: pick(parts, "postal_code"),
  };
}
