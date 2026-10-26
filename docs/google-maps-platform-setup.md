# Google Maps Platform setup

ZuuVi uses Google Maps Platform for the map and address search in the browser, and for geocoding and road
distances on the server. Nothing here has been verified against live Google services from the build
environment; follow the checks at the end to confirm your own setup.

## 1. Create the project and billing

1. In the [Google Cloud Console](https://console.cloud.google.com/), create a project (or reuse one).
2. Link a billing account. Maps Platform requires billing to be enabled.
3. Costs depend on usage and on Google's current pricing and free-usage terms. Check the pricing page for each
   API below before launch and set a budget alert. Do not assume usage will be free.

## 2. Enable these APIs

| API | Used for | Called from |
| --- | --- | --- |
| Maps JavaScript API | Maps and draggable pins | Browser |
| Places API (New) | Address autocomplete and place details | Browser |
| Geocoding API | Pin to address, address to pin | Server |
| Routes API | Road distance for delivery fees | Server |
| Address Validation API | Optional extra address check | Server (off by default) |

Maps URLs (the "Navigate" links for riders and stores) need no key and no API.

## 3. Create two restricted keys

Use two keys so a leaked browser key cannot spend server-side quota.

**Browser key** (`GOOGLE_MAPS_BROWSER_API_KEY`), exposed to every visitor by design:

- Application restriction: **Websites (HTTP referrers)**. Add your production domain, for example
  `https://www.example.com/*`, and `http://localhost:5173/*` and `http://127.0.0.1:8000/*` for development.
- API restriction: Maps JavaScript API and Places API (New) only.

**Server key** (`GOOGLE_MAPS_SERVER_API_KEY`), never sent to browsers:

- Application restriction: **IP addresses** if your host has stable outbound IPs. Many platforms (including
  Railway) do not, in which case use "None" and rely on the API restriction plus quota caps.
- API restriction: Geocoding API, Routes API, and Address Validation API if you enable it.

Then:

- Create a **Map ID** (Map Management, JavaScript, vector) and set `GOOGLE_MAPS_MAP_ID`. Advanced markers
  need one. `DEMO_MAP_ID` works in development only.
- Set per-API **quota caps** and a **budget alert** so a bug or abuse cannot produce a surprise bill.

## 4. Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `GOOGLE_MAPS_BROWSER_API_KEY` | empty | Browser key. The older `GOOGLE_MAPS_API_KEY` is still read if this is unset. |
| `GOOGLE_MAPS_SERVER_API_KEY` | empty | Server key. Required for geocoding and routes. |
| `GOOGLE_MAPS_MAP_ID` | `DEMO_MAP_ID` in debug, otherwise empty | Cloud-styled map ID. |
| `GOOGLE_MAPS_REGION` | `IN` | Region bias for search and geocoding. |
| `GOOGLE_MAPS_LANGUAGE` | `en` | Result language. |
| `GOOGLE_ROUTES_TRAVEL_MODE` | `TWO_WHEELER` | `TWO_WHEELER` or `DRIVE`. See the note below. |
| `GOOGLE_HTTP_TIMEOUT_SECONDS` | `5` | Timeout for each Google request. |
| `GOOGLE_ROUTES_CACHE_TTL_SECONDS` | `600` | Route cache lifetime. `0` turns caching off. |
| `GOOGLE_ADDRESS_VALIDATION_ENABLED` | `False` | Optional Address Validation calls. |
| `DELIVERY_QUOTES_ENFORCED` | `False` | When `True`, delivery orders require a valid server quote. |
| `DELIVERY_QUOTE_TTL_SECONDS` | `900` | How long a quote can be used (minimum 60). |
| `THROTTLE_GEO_*`, `THROTTLE_AUTH_LOGIN` | see `.env.example` | Rate limits for paid or sensitive endpoints. |

Never commit real keys. `.env` is for local development only; set production values in your host's
environment settings.

**Travel mode.** Two-wheeler routing is not available in every country or for every route, and the exact
constraints were not verified when this was written. If Routes returns errors for `TWO_WHEELER` in your area,
set `GOOGLE_ROUTES_TRAVEL_MODE=DRIVE` and compare results. Check the current Routes documentation.

**Route caching.** Routes are cached for a short, configurable time to cut cost and latency. Google's terms
limit what Maps content may be cached or stored; coordinates and place IDs have specific allowances, and route
distance and duration are not explicitly covered. Have the terms reviewed, and set the TTL to `0` if you need
to avoid caching route data. Cached results are always labelled `CACHED` in admin tools.

## 5. Build and deploy the React app

The Maps-enabled screens live in `frontend/` and are served at `/app/`.

```bash
cd frontend
npm ci
npm run build      # outputs frontend/dist/app
```

The Django app serves `frontend/dist/app/index.html` for every `/app/...` route and WhiteNoise serves the
hashed assets. If the build is missing, `/app/` answers with a 503 explaining what to run.

`railway.toml` currently builds only Django (`python scripts/collectstatic.py`). To deploy the React app,
add `npm ci && npm run build --prefix frontend` before that command, or build in CI. This change was left to
you because it alters your deploy pipeline.

## 6. Verify your setup

1. Sign in to the admin section of `/app/` as a user with the Maps permission and open **Maps status**.
2. Confirm both keys show as present, then press **Run health check**. This makes one small paid request per
   service and records whether Google accepted the key.
3. Create a pricing config under **Delivery pricing**, then use the **simulator** with a real store and a
   pin to confirm a live route and fee.
4. Open a store's location, place the pin, tick the confirmation, and save.
5. Only after stores have confirmed pins and a pricing config exists, set `DELIVERY_QUOTES_ENFORCED=True`.

## 7. Optional live tests

Normal tests never call Google; any attempt fails the test run. Live checks are the admin health check above.
