# Google Maps troubleshooting

Start with Admin → Delivery operations → **Google Maps status** and press **Run health check**. Each of the three Google services reports working or a reason.

| Health check says | Meaning | Fix |
|---|---|---|
| `NOT_CONFIGURED` | No server key, or `LOCATION_GEOCODER` / `LOCATION_ROUTER` is not `google` | Set `GOOGLE_MAPS_SERVER_KEY`, `LOCATION_GEOCODER=google`, `LOCATION_ROUTER=google`, restart |
| `KEY_REJECTED` | Google refused the key (HTTP 401/403, `REQUEST_DENIED`, `PERMISSION_DENIED`) | Check the API is enabled for that service, the key's API restrictions include it, and the IP restriction matches the server's outbound address. Restrictions take a few minutes to apply |
| `QUOTA_EXCEEDED` | HTTP 429, `OVER_QUERY_LIMIT`, `RESOURCE_EXHAUSTED` | Check quotas and billing in Google Cloud; raise caps or wait |
| `TIMEOUT` | No answer within `LOCATION_PROVIDER_TIMEOUT` (default 5 s) | Retry; raise the timeout if it is frequent |
| `NETWORK` | The server could not reach Google | Check the host's outbound network |
| `BAD_RESPONSE` | Unexpected reply | Check the service's API version and field mask; look at server logs |

Keys and request URLs are never logged or returned.

## Customers see
- **"We couldn't look up this point's address"**: reverse geocoding failed. The pin still works; they can type the address.
- **Address search unavailable**: search failed. Pin and typing still work.
- **"We can't work out the road distance right now"**: Routes failed and the active pricing version has *Allow estimated distance* off. Turn it on in Delivery pricing to fall back to a labelled estimate, or fix Routes.
- **Delivery fee labelled "estimated"**: Routes failed and an estimate was used.

## The map is grey, or says it could not load
Open the browser console; Google prints the reason: `RefererNotAllowedMapError` (add the site address to the web key's referrers), `ApiNotActivatedMapError` (enable Maps JavaScript API), `BillingNotEnabledMapError` (link billing). The web key and Map ID are build-time frontend settings (`VITE_GOOGLE_MAPS_BROWSER_KEY`, `VITE_GOOGLE_MAPS_MAP_ID`); rebuild after changing them.

## A store does not show up for a customer
Admin → Delivery operations lists stores that "need fixing". Common causes: no pin, pin outside Kerala, radius not set, no drawn zone in zone mode, store closed, or (when `STORE_PIN_CONFIRMATION_REQUIRED` is on) the pin has not been confirmed.

## Search or health check returns HTTP 429 from Zuuvi
Zuuvi throttles itself: `API_THROTTLE_GEO` (search, default 30/min), `API_THROTTLE_QUOTE` (60/min), `API_THROTTLE_MAPS_CHECK` (10/hour).

## Travel mode
`GOOGLE_ROUTES_TRAVEL_MODE` defaults to `TWO_WHEELER`. Availability depends on region; if Routes fails only in that mode, try `DRIVE`.
