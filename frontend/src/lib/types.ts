export type Portal = "customer" | "store" | "delivery" | "admin";

export interface SessionUser {
  id: number;
  username: string;
  name: string;
  role: string;
}

export interface Session {
  authenticated: boolean;
  portal?: Portal;
  user?: SessionUser;
  permissions?: { maps: boolean; pricing: boolean; assignments: boolean };
  csrfToken?: string;
}

export interface MapsConfig {
  browserKey: string;
  mapId: string;
  region: string;
  language: string;
  browserConfigured: boolean;
  serverConfigured: boolean;
}

export type LocationSource = "MANUAL" | "PLACE_SEARCH" | "CURRENT_LOCATION" | "MAP_PIN";

export interface Point {
  lat: number;
  lng: number;
}

/** A readable address for a point, from Google (browser or server side). */
export interface ResolvedAddress {
  formattedAddress: string;
  placeId: string;
  /** True when Google matched a building or street address, not just an area. */
  precise: boolean;
  line1: string;
  locality: string;
  district: string;
  state: string;
  postalCode: string;
}

export interface SavedAddress {
  id: number;
  label: "HOME" | "WORK" | "OTHER";
  label_display: string;
  recipient_name: string;
  phone_number: string;
  line1: string;
  line2: string;
  landmark: string;
  city: string;
  district: string;
  state: string;
  postal_code: string;
  country: string;
  latitude: string;
  longitude: string;
  google_place_id: string;
  location_source: LocationSource;
  location_confirmed: boolean;
  delivery_instructions: string;
  is_default: boolean;
}

export interface AddressPayload {
  label: "HOME" | "WORK" | "OTHER";
  recipient_name: string;
  phone_number: string;
  line1: string;
  line2: string;
  landmark: string;
  city: string;
  district: string;
  state: string;
  postal_code: string;
  latitude: string;
  longitude: string;
  google_place_id: string;
  location_source: LocationSource;
  location_confirmed: boolean;
  delivery_instructions: string;
  is_default: boolean;
}

export interface NearbyStore {
  id: number;
  name: string;
  category: string;
  straight_line_km: number | null;
  within_delivery_area: boolean;
  reasons: { code: string; message: string }[];
  approximate: boolean;
}

export interface CartStoreGroup {
  store_id: number;
  store_name: string;
  items_subtotal: string;
  items: {
    product_name: string;
    quantity: string | number;
    unit_price: string | null;
    line_total: string | null;
    is_available: boolean;
    warnings: string[];
  }[];
}

export interface CheckoutSummary {
  cart: {
    is_empty: boolean;
    items_subtotal: string;
    blocking_messages: string[];
    stores: CartStoreGroup[];
  };
  addresses: SavedAddress[];
  checkout_token: string;
  payment_methods: { value: string; label: string }[];
}

export interface QuoteLeg {
  store_id: number;
  store_name: string;
  items_subtotal: string;
  road_distance_km: string;
  delivery_fee_before_discount: string;
  delivery_discount: string;
  delivery_fee: string;
}

export interface DeliveryQuote {
  id: number;
  address_id: number;
  expires_at: string;
  delivery_fee_before_discount: string;
  delivery_discount: string;
  delivery_fee: string;
  legs: QuoteLeg[];
  distance_note: string;
}

export interface OrderTracking {
  order_number: string;
  status: string;
  status_display: string;
  delivery: { label: string; latitude: string | null; longitude: string | null };
  delivery_charge: string;
  delivery_discount: string;
  grand_total: string;
  delivery_time_note: string;
  stores: {
    store_name: string;
    status: string;
    status_display: string;
    pickup: { latitude: string; longitude: string };
    delivery_partner_status: string | null;
    delivery_fee: string;
  }[];
}

export interface LocationIssue {
  code: string;
  message: string;
  action: string;
}

export interface StoreLocation {
  id: number;
  name: string;
  store_code: string;
  status: string;
  is_active: boolean;
  latitude: string | null;
  longitude: string | null;
  line1: string;
  line2: string;
  landmark: string;
  city: string;
  district: string;
  state: string;
  postal_code: string;
  google_place_id: string;
  delivery_radius_km: string;
  location_confirmed_at: string | null;
  can_take_delivery_orders: boolean;
  issues: LocationIssue[];
}

export interface AddressBlock {
  recipient_name: string;
  phone_number: string;
  line1: string;
  line2: string;
  landmark: string;
  city: string;
  postal_code: string;
  latitude: string;
  longitude: string;
  navigation_url: string;
}

export interface FulfilmentOrder {
  store_order_number: string;
  status: string;
  status_display: string;
  pickup: AddressBlock;
  dropoff?: AddressBlock;
}

export interface RiderAssignment {
  id: number;
  store_order_number: string;
  status: string;
  status_display: string;
  store_order_status: string;
  store_order_status_display: string;
  is_active: boolean;
  next_action: { code: string; label: string } | null;
  pickup: AddressBlock;
  dropoff?: AddressBlock;
  delivery_instructions?: string;
  route?: { distance_km: string; duration_minutes: number; source: string };
}

export interface HealthEntry {
  checked_at: string | null;
  ok: boolean | null;
  error_code: string;
  message: string;
  latency_ms: number | null;
  last_success_at: string | null;
}

export interface MapsStatus {
  configuration: {
    browser_key_present: boolean;
    server_key_present: boolean;
    map_id_present: boolean;
    region: string;
    language: string;
    travel_mode: string;
    route_cache_ttl_seconds: number;
    address_validation_enabled: boolean;
    delivery_quotes_enforced: boolean;
  };
  health: Record<"GEOCODING" | "ROUTES", HealthEntry>;
  pricing_configured: boolean;
  docs: { setup: string; troubleshooting: string; google_cloud_console: string };
}

export interface PricingConfig {
  id: number;
  version: number;
  name: string;
  is_active: boolean;
  created_at: string;
  [field: string]: string | number | boolean | null;
}

export interface SimulationResult {
  input: { kind: string; latitude: string; longitude: string; items_subtotal: string };
  route: {
    distance_km: string;
    duration_seconds: number;
    source: "LIVE" | "CACHED";
    is_live: boolean;
    calculated_at: string;
    travel_mode: string;
    provider: string;
  };
  serviceability: {
    eligible: boolean;
    reasons: { code: string; message: string }[];
    straight_line_km: number | null;
    within_max_road_distance: boolean;
  };
  pricing_version: number;
  pricing: Record<string, string>;
}

export interface AdminAssignment {
  id: number;
  store_order_number: string;
  store_name: string;
  agent_id: number;
  agent_username: string;
  status: string;
  assigned_at: string;
}
