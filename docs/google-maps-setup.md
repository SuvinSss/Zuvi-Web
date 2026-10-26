# Google Maps Platform setup (web and mobile)

Zuuvi uses Google for four things. Everything except drawing the map goes through the Zuuvi backend, so the secret server key never reaches a browser or a phone, and the website and future Android/iOS apps share the same endpoints, rules and caching.

| Need | Google API | Called by |
|---|---|---|
| Address suggestions while typing | Places API (New) Autocomplete | backend `GET /api/v1/geo/search/` |
| Coordinates for a chosen suggestion | Places API (New) Place Details | backend `GET /api/v1/geo/place/` |
| Address for a GPS fix or dropped pin | Geocoding API | backend `GET /api/v1/geo/reverse/` |
| Road distance for the delivery fee | Routes API `computeRoutes` (two-wheeler) | backend, during checkout quote and order placement |
| Showing the map | Maps JavaScript API (web), Maps SDK for Android, Maps SDK for iOS | the client |

Google's terms require Geocoding/Places results shown on a map to be shown on a **Google map**, so turning on Google search also switches the map to Google. Google content is not cached by Zuuvi beyond the request; only place ids may be stored.

## 1. Google Cloud Console
1. Create a project, attach a **billing account**, and set a **budget alert** plus per-API **daily quotas** (APIs & Services → each API → Quotas).
2. Enable: Places API (New), Geocoding API, Routes API, Maps JavaScript API. For apps also enable Maps SDK for Android and/or Maps SDK for iOS.
3. Create keys (APIs & Services → Credentials), each with **API restrictions**:

| Key | Application restriction | API restriction | Where it lives |
|---|---|---|---|
| Server | IP addresses of your backend servers | Places API (New), Geocoding API, Routes API | `backend/.env` `GOOGLE_MAPS_SERVER_KEY` |
| Web | HTTP referrers: `https://zuuvi.in/*`, `https://www.zuuvi.in/*`, `http://localhost:5173/*` | Maps JavaScript API | `frontend/.env` `VITE_GOOGLE_MAPS_BROWSER_KEY` |
| Android | Android apps: package name + SHA-1 of the release (and debug) signing certificate | Maps SDK for Android | the Android app's manifest / secrets file |
| iOS | iOS apps: bundle identifier | Maps SDK for iOS | the iOS app's config |

Web and app keys are visible to users by design; the restrictions are what protect them. **Never** put the server key in the web or app code.

## 2. Configure Zuuvi
`backend/.env`:
```
GOOGLE_MAPS_SERVER_KEY=your-server-key
LOCATION_GEOCODER=google
LOCATION_ROUTER=google
GOOGLE_ROUTES_TRAVEL_MODE=TWO_WHEELER   # or DRIVE
LOCATION_PROVIDER_TIMEOUT=5
```
`frontend/.env` (rebuild the frontend afterwards):
```
VITE_GOOGLE_MAPS_BROWSER_KEY=your-web-key
```
Restart Django. `GET /api/v1/geo/config/` should now report `"geocoder": "google", "router": "google", "map": "google"`. Without keys everything keeps working on OpenStreetMap with estimated distances.

## Website: where Google Maps appears
| Page | What it shows |
|---|---|
| Header "Delivering to" and Saved addresses | Search with Google suggestions ("Powered by Google"), use my location, drag-the-pin map (one-finger panning on phones) |
| Checkout | Road distance from Google Routes in the delivery fee |
| Order page (customer) | Map with the rider's last position, your address and the store; "Open in Google Maps" |
| Store page (public) | Shop location map and "Get directions" |
| Rider job page | Store and drop-off on one map; "Full route in Google Maps" (two-wheeler) and per-stop navigate links |
| Admin store wizard / store Address tab | Place or check the store pin |
| Admin delivery zones | Draw zones on the map |

Links that open Google Maps (directions, "open in Google Maps") need no key and work even without the keys below.

### Optional: Map ID (styled map, Google's newer pins)
Google Maps Platform → **Map Management** → Create Map ID → type **JavaScript**, **Vector** → copy the ID into `frontend/.env` as `VITE_GOOGLE_MAPS_MAP_ID=...` and rebuild. With a Map ID the site uses Advanced Markers; you can then style the map under **Map Styles** and link the style to that Map ID. Without it the standard Google map and classic pins are used.

### Website checklist
1. `frontend/.env`: `VITE_GOOGLE_MAPS_BROWSER_KEY=<website key>` (and optional `VITE_GOOGLE_MAPS_MAP_ID`).
2. Vite reads these **at build time**: restart `npm run dev`, and run `npm run build` again for production.
3. The website key's referrers must include every address the site is opened from (`https://zuuvi.in/*`, `https://www.zuuvi.in/*`, any staging domain, `http://localhost:5173/*`).
4. If you later add a Content-Security-Policy on your web server, allow `https://maps.googleapis.com` and `https://maps.gstatic.com` (scripts, images, connections) and `https://*.googleapis.com` for connections.
5. Check: open Saved addresses → Add address. You should see a Google map, suggestions with "Powered by Google", and no "could not load" message. If the map shows "could not load", open the browser console: Google prints the exact reason (e.g. `RefererNotAllowedMapError`, `ApiNotActivatedMapError`, `BillingNotEnabledMapError`).

## 3. Mobile apps (Android / iOS)
Apps use the same REST API with token authentication (`POST /api/v1/auth/token/`, then `Authorization: Token …`).
1. On start, call `GET /api/v1/geo/config/` to learn whether search and road distance are on and which attribution to show.
2. Show the map with the native Maps SDK and the app's restricted key.
3. Address search: create a UUID **session token** when the user starts typing; call `/geo/search/?q=…&session=<token>&lat=…&lon=…` (lat/lon optional, biases results). Suggestions with `"needs_details": true` have no coordinates: on tap call `/geo/place/?id=<place_id>&session=<same token>`, then start a new token for the next search. Google bills one session instead of every keystroke. Show "Powered by Google" under suggestions.
4. "Use my location": ask the OS permission only when the user taps it, then call `/geo/reverse/?lat=&lon=`; let the user drag the pin and confirm. Save with `POST /customer/addresses/` (`location_source`, `location_accuracy_m`, `location_confirmed: true`).
5. Checkout: `POST /checkout/quote/` → show totals → `POST /checkout/` with `quote_token` and an `Idempotency-Key` header. Handle **409** by showing the message and the new quote.
6. Rider app: `GET /deliveries/<id>/` includes `trip` (distance, estimated payout); navigation can open the Google Maps app with the drop-off coordinates; `GET /delivery/earnings/`.
No Google server calls are needed from the app.

## 4. Cost control
- Store lists use a straight-line estimate (no Routes call per store). Road distance is fetched for each store in the cart at the checkout quote and again when the order is placed.
- Search is debounced, needs 3+ characters, uses session tokens and is throttled per client (`API_THROTTLE_GEO`, default 30/min; `API_THROTTLE_QUOTE`, default 60/min).
- If Google errors, times out or a quota is hit, search shows "unavailable" (pin and typing still work) and distances fall back to the labelled estimate (or delivery is refused if estimates are turned off in Delivery pricing).
- Check Google's current pricing and free usage before launch; prices change.

## 5. Troubleshooting
| Symptom | Likely cause |
|---|---|
| "Address search is unavailable" | `LOCATION_GEOCODER` not `google`, missing server key, Places API (New) not enabled, IP restriction doesn't match the server, quota/billing |
| Map says "could not load" | Missing/blocked browser key, referrer not allowed, Maps JavaScript API not enabled |
| Checkout says distance is estimated | Routes API not enabled or failing; see the Django log line "Routing unavailable" (keys are never logged) |
