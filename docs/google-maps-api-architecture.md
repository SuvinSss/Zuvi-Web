# Google Maps architecture

## Who calls what

```
Browser (React, browser key)                Django (server key)
  Maps JavaScript API  <- map, pins          geo/google_client.py
  Places (New) autocomplete + details        - Geocoding (forward and reverse)
                                             - Routes computeRoutes / computeRouteMatrix
Browser --> /api/v1/... --> Django           - Address Validation (optional)
```

- The **browser key** is served by `GET /api/v1/config/maps/`. It is public by design and protected by
  referrer and API restrictions in Google Cloud.
- The **server key** only exists in server settings. It is sent to Google in a header (Routes) or query string
  (Geocoding), is scrubbed from logs and error messages, and is never returned by any endpoint.
- Autocomplete uses one session token per search, ended by the place-details call.
- Every paid server call sits behind login and a throttle. The one public location endpoint
  (`/stores/nearby/`) is straight-line maths only and never calls Google.

## Backend modules (`geo/`)

| Module | Responsibility |
| --- | --- |
| `config.py` | Reads settings; `browser_client_config()` exposes the browser key only. |
| `google_client.py` | The only code that talks to Google. Maps every failure to a `MapsError` with a public message. |
| `routing.py` | Cached route lookup, and one matrix call for several stores. Never falls back to a straight-line distance. |
| `serviceability.py` | Store eligibility: active, confirmed pin, radius prefilter. |
| `pricing.py` | `price_leg()`: one pure function used by checkout and the admin simulator. |
| `quotes.py` | Quote creation, fingerprinting, locking and consumption. |
| `store_locations.py` | Store pin reports and updates. |
| `navigation.py` | Google Maps navigation URLs. |
| `api/` | DRF views, permissions, throttles and the JSON error format. |

## Error handling

All failures become `{"error": {"code", "message", "retryable", ...}}`. Codes include `MAPS_NOT_CONFIGURED`,
`MAPS_KEY_REJECTED`, `MAPS_QUOTA_EXCEEDED`, `MAPS_TIMEOUT`, `MAPS_NETWORK_ERROR`, `MAPS_BAD_RESPONSE`,
`NO_ROUTE`, `ADDRESS_NOT_FOUND`, `INVALID_COORDINATES` and `PRICING_NOT_CONFIGURED`. Customers see plain
language; details go to server logs without keys or URLs.

## Frontend (`frontend/src`)

- `state/maps.tsx` loads Google with the browser key and exposes `ready`, `unconfigured`, `rejected` or
  `loading`. Components fall back to typed address entry when it is not `ready`.
- `components/maps/AddressSearch` (autocomplete), `LocationPicker` (draggable pin plus debounced reverse
  geocode), and `components/location/*` (current location, address form, header selector, dialog).
- Pages are grouped by portal: `customer`, `store`, `delivery`, `admin`.
- The selected location is kept in `localStorage` inside try/catch; the app works if storage is blocked.

## API endpoints (`/api/v1/`)

Public: `config/maps/`, `auth/session|login|logout/`, `stores/nearby/`.
Signed in: `geo/reverse-geocode/`, `geo/geocode/`.
Customer: `customer/addresses/` (+ `<id>/`, `<id>/default/`), `customer/checkout/summary/`,
`customer/delivery-quote/`, `customer/checkout/`, `customer/orders/<number>/tracking/`.
Store: `store/location/`, `store/orders/`.
Delivery partner: `rider/assignments/` (+ `<id>/`, `<id>/advance/`).
Admin: `admin/maps/status/`, `admin/maps/health-check/`, `admin/stores/locations/`,
`admin/stores/<id>/location/`, `admin/pricing/configs/`, `admin/pricing/simulate/`, `admin/assignments/`.

## Testing

Django tests replace the HTTP transport with `geo.testing.FakeTransport`; the test runner makes any real
Google request fail. Frontend tests use Vitest with Google bindings mocked. Neither proves that live Google
accepts your keys; use the admin health check for that.
