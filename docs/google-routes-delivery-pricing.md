# Google Routes and delivery pricing

## Flow

1. The customer picks a saved address at checkout and asks for a delivery fee.
2. The server checks each store in the basket (active, confirmed pin, inside its radius by straight line).
3. For stores that pass, it asks Google Routes for the **road distance** from the store to the address. One
   store uses `computeRoutes`; several use a single `computeRouteMatrix` call (capped at 25 elements).
4. `price_leg()` turns each road distance into a fee, using the active pricing config.
5. The server stores a **quote** (one row per store leg) and returns only the customer-safe fields.
6. When the order is placed, the quote is locked, checked and consumed, and a **snapshot** is saved on the
   order. Later pricing or route changes never alter that order.

If Google can't be reached, the quote fails with a clear, retryable error. There is **no straight-line fallback**,
because quoting from a wrong distance would mis-price the order.

## What the quote guards against

- The quote belongs to one customer, one address and one basket shape. A fingerprint over the customer,
  destination, pricing config ID and each store's subtotal is re-checked at checkout under a row lock.
- It expires after `DELIVERY_QUOTE_TTL_SECONDS` (default 900) and can be used once.
- Prices in a checkout request are ignored; only `address_id`, `quote_id` and the checkout token are accepted.
- Another customer's quote or address looks like "not found".

## Pricing config

Configs are **versioned and append-only**: saving creates a new active version and deactivates the old one.
Only one can be active (database constraint). Fields:

| Group | Fields |
| --- | --- |
| Customer tariff | `customer_base_fee`, `customer_free_distance_km`, `customer_fee_per_km`, `customer_minimum_fee`, `customer_maximum_fee`, `fee_rounding_step` |
| Offers | `free_delivery_threshold`, `store_funded_discount_percent` |
| Operating cost (internal) | `fuel_price_per_litre`, `vehicle_mileage_km_per_litre`, `maintenance_cost_per_km`, `operational_distance_multiplier`, `minimum_operational_distance_km`, `rider_base_payout`, `rider_payout_per_km`, `other_cost_per_delivery` |
| Limit | `max_road_distance_km` |

Customer fee = `base + max(0, road_km − free_km) × per_km`, raised to the minimum, capped at the maximum, then
rounded **up** to the rounding step. If the basket reaches the free-delivery threshold the fee is discounted to
zero and the discount is split between the store and the platform.

Operational cost = fuel + maintenance + rider payout + other cost, using the operational distance
(`road_km × multiplier`, at least the minimum).

Worked example: base 20, free 0 km, 8.30 per km, step 5, road distance 3 km: `20 + 3 × 8.30 = 44.90`, rounded
up to **45.00**.

## Who sees what

| Field | Customer | Store | Delivery partner | Admin |
| --- | --- | --- | --- | --- |
| Fee, discount, road distance | Yes | No | Distance and `LIVE`/`CACHED` only | Yes |
| Rider payout, operational cost, subsidy, contribution | **No** | No | No | Yes (simulator, snapshot) |

## Admin simulator

`POST /api/v1/admin/pricing/simulate/` takes a store, a destination and a basket value, and runs the same
route lookup and `price_leg()` as checkout. Output includes the route source (`LIVE` or `CACHED`), eligibility
reasons, and the full internal breakdown. "Bypass cache" forces a fresh Google call.

## Turning on enforcement

`DELIVERY_QUOTES_ENFORCED` defaults to `False`, so existing checkout behaves as before. Enable it only after:

1. Both keys are set and the admin health check passes.
2. A pricing config is active.
3. Every delivery store has a confirmed pin (Admin → Store locations shows who needs fixing).
4. The React checkout (`/app/customer/checkout`) is how customers place delivery orders, since the older Django
   checkout does not create quotes.

## Compliance and cost notes

- Each uncached quote spends Routes quota. Cache lifetime is `GOOGLE_ROUTES_CACHE_TTL_SECONDS` (default 600;
  `0` disables). Google's terms limit caching and storing of Maps content, and route distance is not
  explicitly covered; have the terms reviewed. A saved order snapshot is kept for the order record.
- `TWO_WHEELER` support varies by region. If routes fail, try `DRIVE`.
- Prices change. Check current Routes pricing and set budget alerts.
