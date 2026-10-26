# Google Maps troubleshooting

Start at **Admin → Maps status**. It shows which keys are set and the result of the last health check
(error code, message, latency and last success). "Present" only means a value exists; the health check shows
whether Google accepts it.

## The map is grey, or the app says Google rejected the key

- Open the browser console. `RefererNotAllowedMapError` means the site's address isn't in the browser key's
  referrer list. Add `https://your-domain/*`.
- `ApiNotActivatedMapError`: enable Maps JavaScript API and Places API (New) in the project.
- `BillingNotEnabledMapError`: link billing to the project.
- Key restrictions can take a few minutes to apply.
- Advanced markers need a Map ID: set `GOOGLE_MAPS_MAP_ID`.

The app still lets customers type their address when the map fails.

## Address search shows no results

- Confirm Places API (New) is enabled and allowed on the browser key.
- Search needs at least three characters and is limited to India (`GOOGLE_MAPS_REGION`).

## "We couldn't find an address for this pin"

Reverse geocoding uses the server key. Check the health check for Geocoding. In the open ocean or unmapped
areas Google may return no result; the user can still type the address.

## Delivery quote errors

| Code | Meaning | What to do |
| --- | --- | --- |
| `MAPS_NOT_CONFIGURED` | Server key missing | Set `GOOGLE_MAPS_SERVER_API_KEY` |
| `MAPS_KEY_REJECTED` | Google denied the server key | Check API restrictions and that Routes API is enabled; check IP restriction |
| `MAPS_QUOTA_EXCEEDED` | Quota or rate limit hit | Raise quota caps; the customer can retry shortly |
| `MAPS_TIMEOUT` / `MAPS_NETWORK_ERROR` | Google slow or unreachable | Retry; raise `GOOGLE_HTTP_TIMEOUT_SECONDS` if frequent |
| `NO_ROUTE` | No road route | Check both pins; the address may be unreachable |
| `PRICING_NOT_CONFIGURED` | No active pricing config | Create one in Admin → Delivery pricing |
| `NOT_SERVICEABLE` | A store is closed, unconfirmed, or too far | The reasons list says which store and why |
| `QUOTE_INVALID` (expired or changed) | Basket or address changed, or 15 min passed | Recalculate the fee |

If Routes fails only with `TWO_WHEELER`, set `GOOGLE_ROUTES_TRAVEL_MODE=DRIVE`.

## A store doesn't appear for customers

Open Admin → Store locations. Each issue has an action: missing pin, pin outside India, pin at (0,0),
unconfirmed pin, store inactive, or the same location as another store.

## `/app/` shows "has not been built yet"

Run `npm ci && npm run build` inside `frontend/`, then restart Django. On Railway the build command must
include the frontend build (see the setup guide).

## Rate-limited (HTTP 429)

Paid endpoints are throttled per user. Raise the matching `THROTTLE_*` value if legitimate use hits it.

## Logs

Google errors are logged under `geo.google` with the HTTP status and Google's status code. Keys and request
URLs are removed before logging.
