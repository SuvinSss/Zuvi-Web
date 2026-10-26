# Delivery pricing and location API (`/api/v1/`)

| Method & path | Who | Purpose |
|---|---|---|
| `GET geo/search/?q=&session=&lat=&lon=` | anyone (throttled) | Address suggestions. `{results, available, attribution}`; `available:false` when no provider/failure. `session` groups a typing session for billing; lat/lon bias results. |
| `GET geo/reverse/?lat=&lon=` | anyone (throttled) | Address for a point. 400 for invalid coordinates. |
| `GET geo/place/?id=&session=` | anyone (throttled) | Coordinates and address parts for a suggestion with `needs_details: true` (Google). |
| `GET geo/config/` | anyone | Which providers are on (`map`, `search_available`, `road_distance`, `attribution`, `suggestions_need_details`). No keys. For web and mobile apps. |
| `GET delivery/stores/?lat=&lon=` | anyone (throttled) | Active stores with `serviceable`, `reasons`, `distance_km`, `distance_source`, indicative `fee` (before order-size offers), `eta_minutes`. |
| `POST checkout/quote/` `{fulfillment_type, delivery_address_id}` | customer | Server totals: per-store customer delivery view, `delivery_total`, `grand_total`, `quote_token` (expires after `CHECKOUT_QUOTE_TTL_SECONDS`, default 600). |
| `POST checkout/` (+ `quote_token`, `Idempotency-Key` header) | customer | Places the order. Fees are recalculated server-side; client totals are ignored. If the total, cart, address or quote validity changed: **409** `{quote_token: ["The total changed from ₹X to ₹Y. Store: delivery ₹a → ₹b (offer no longer applies)"], price_changed: true}` and nothing is created. Same Idempotency-Key = same order. |
| `GET orders/<id>/` | customer | Each store order now includes `delivery_charge` and a customer-safe `delivery` breakdown. |
| `GET deliveries/<id>/` | rider/store/admin | Adds `trip`: distance, source, `estimated_payout`, payout breakdown, ETA. |
| `GET delivery/earnings/` | rider | Own earnings and totals (today, unpaid, all-time). |
| `GET store/finance/` | store user | Items, commission, store-funded offers, settlement per order; delivery fees shown as not store revenue; `location_problems`. |
| `GET/POST admin/delivery-pricing/` | view / manage permission | Active, scheduled and history versions; POST `{settings:{…}, reason, effective_from?, zone?}` creates a version (validated by pricing sample distances). |
| `POST admin/delivery-pricing/simulate/` | view permission | `{distance_km | store+lat+lon, items_subtotal, is_peak, heavy, overrides:{…}, batch:{route_km, stops}}` → full breakdown; saves nothing. |
| `GET/POST admin/delivery-zones/`, `PATCH admin/delivery-zones/<id>/` | view / manage | Zones with polygon `[[lat, lon], …]` (3–500 points), surcharge, active flag. Duplicate names → 400. |
| `GET admin/delivery-operations/?days=` | view permission | Store pin problems, orders without destination pins, riders online, deliveries waiting/needing attention, failed attempts by reason, delivery money totals from snapshots, fees to review. |
| `GET/POST admin/partner-earnings/` | view / payouts permission | List earnings; POST `{ids, payout_reference}` marks unpaid ones paid (audited). |

Errors follow the existing `{field: [message]}` format. Customer-facing responses never include estimated cost, rider pay, subsidy or contribution.
