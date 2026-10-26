# Location and address system

## Customer experience
- **Header "Delivering to ▾ Home · Locality, Town"** (all customer pages). Opens a dialog: saved addresses, "Add a new address", and for browsing "Use my current location" or tap the map. Guests can pick a point to see which stores deliver; it is kept in memory only. For signed-in customers only the chosen saved-address **id** is remembered in the browser; coordinates are never stored there.
- **Address picker** (Saved addresses, checkout, header): 1) "Use my current location": explains why, asks permission only on tap, warns when GPS accuracy is worse than 100 m; 2) search with suggestions, loading, empty and unavailable states; 3) tap or drag the pin. Reverse geocoding fills locality/town/district/state/PIN without overwriting what the customer typed. Then house/building, street, landmark, town, district, state, PIN (optional, 6 digits if given), Home/Work/Other with a custom name, receiver, phone, instructions. **Save is disabled until the customer ticks that the pin is right.**
- Denied, unavailable or timed-out location never blocks: search and map stay available.
- Saved addresses show "Pin not confirmed" for older addresses; addresses without a pin cannot be used for delivery.
- **Stores** page shows, for the chosen location: "Delivers to you · 2.4 km (approx.) · ₹25 delivery · ~22 min" or the reason it doesn't.
- **Checkout** uses a server quote: per-store delivery line, "Delivery fee based on distance" with an expandable breakdown (distance, surcharges, discount and who it's for, tax). The customer never sees cost, rider pay or subsidy.

## Data stored per address
`customers.CustomerAddress`: label, custom_label, recipient, phone, instructions, place_id, location_source (GPS/SEARCH/PIN/MANUAL), location_accuracy_m, location_confirmed_at (set by the server), plus the `locations.Address` fields (PIN optional). Ownership is enforced: another customer's address id returns 404.

## Providers (`backend/logistics/providers.py`)
| Setting | Values | Default |
|---|---|---|
| `LOCATION_GEOCODER` | `none`, `nominatim`, `google` | `none` |
| `LOCATION_GEOCODER_URL` | base URL of a Nominatim-compatible server you may use | empty |
| `LOCATION_GEOCODER_USER_AGENT` | identifying UA (required by Nominatim policy) | `Zuuvi/1.0 (ops@zuuvi.in)` |
| `LOCATION_ROUTER` | `none`, `osrm`, `google` | `none` |
| `GOOGLE_MAPS_SERVER_KEY` | server-only Google key (see [google-maps-setup.md](google-maps-setup.md)) | empty |
| `VITE_GOOGLE_MAPS_BROWSER_KEY` (frontend) | referrer-restricted key; switches the map to Google | empty |
| `LOCATION_ROUTER_URL` | base URL of an OSRM server | empty |
| `LOCATION_PROVIDER_TIMEOUT` | seconds | 5 |
| `VITE_MAP_TILE_URL`, `VITE_MAP_ATTRIBUTION` (frontend) | map tile template and attribution | OpenStreetMap standard tiles |

- Out of the box nothing external is called: search and address lookup report "unavailable" and distances are estimated.
- Public demo servers (nominatim.openstreetmap.org, router.project-osrm.org, tile.openstreetmap.org) have strict usage policies and are **not** production services. Self-host or use a licensed provider, then set the variables. No API keys are ever placed in the React bundle; all geocoding and routing goes through the backend.
- Responses are validated (coordinates, distance plausibility), cached 24 h, throttled (`geo` 30/min, `quote` 60/min per client), and failures return a friendly "unavailable" instead of an error.

## Privacy
Location is requested only on a user action; there is no background tracking of customers. Riders' existing live-location feature is unchanged. Stores see a customer's address only on their own orders; riders only after accepting.
