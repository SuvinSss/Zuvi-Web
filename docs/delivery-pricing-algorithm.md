# Delivery pricing algorithm

Code: `backend/logistics/engine.py` (pure, Decimal-only). Checkout, the admin simulator and the tests all call this one engine; the browser never calculates an authoritative fee.

Units: kilometres, Indian rupees, rates as fractions (0.10 = 10%). Internal precision is 4 decimal places; money is rounded to paise (half-up) only at the edges, and the customer fee is rounded with the configured rupee rule.

## Steps
For one delivery from a store to a customer (each store in a multi-store order is its own trip and gets its own fee):

| Step | Formula |
|---|---|
| A. Fuel per km | `fuel_cost_per_km = energy_price ÷ efficiency_km_per_unit` (₹/litre ÷ km/litre; EV: ₹/kWh ÷ km/kWh). Efficiency must be > 0. |
| B. Operational km | `operational_km = d × m`, `d` = one-way road km, `m` = operational distance factor (≥ 1; 1.6 default, 2.0 isolated return trip) |
| C. Direct cost | `fuel = operational_km × fuel_cost_per_km`; `maintenance = operational_km × maintenance_per_km`; `rider = per_order + per_km × d + fixed_daily ÷ expected_orders_per_day`; `overhead = overhead_per_order + overhead_per_km × operational_km`; `direct = fuel + maintenance + rider + overhead` |
| D. Failures | `failure_allowance = direct × failure_cost_rate` (an assumption until real failure data replaces it). A failed attempt that wasn't the rider's fault is also paid to the rider separately (`rider_pay_per_failed_attempt`), recorded as an earning, never double-counted in the order's cost. |
| E. Estimated cost | `estimated_cost = direct + failure_allowance + special_handling_cost (heavy orders only)` |
| F. Customer fee | See modes below; add surcharges (busy hours, hard-to-reach zone, heavy items); clamp to `[min_fee, max_fee]` (unless above-max is explicitly allowed); round; apply one discount (free delivery above a threshold, else a flat delivery discount), with its funder; add delivery tax only if configured. |
| G. Split | Report separately: estimated cost, fee before discount, fee after discount, delivery tax, rider payout, platform-funded promotion, store-funded promotion, **platform subsidy** = `max(0, estimated_cost − fee_after_discount − store_funded_promotion)` and **delivery contribution** = the opposite when positive. Nothing is called "profit". |

### Customer fee modes
- **Distance bands**: the first band whose `up_to_km ≥ d`; beyond the last band, last fee + `per_km_rate` × extra km.
- **Base + distance**: `base_fee + max(0, d − included_km) × per_km_rate`.
- **Cost-aware**: `max(base + distance tariff, estimated_cost × customer_recovery_ratio)`.
- **Hybrid**: `max(base + distance tariff, estimated_cost − max_platform_subsidy_per_order)`; Zuuvi never subsidises one delivery by more than the cap.

If the maximum fee stops the target being reached, the shortfall is recorded as `capped_by_max_fee` and as platform subsidy; it is never hidden.

## Worked example (covered by `logistics/tests_engine.py::WorkedExampleTests` and the simulator API test)
Petrol ₹115/litre, 40 km/litre, 5 km, factor 2.0, maintenance ₹1.50/km, rider ₹25, overhead ₹8, failure allowance 10%:

1. Fuel per km = 115 ÷ 40 = ₹2.875
2. Operational km = 5 × 2 = 10
3. Fuel = 10 × 2.875 = ₹28.75
4. Maintenance = 10 × 1.50 = ₹15.00
5. Direct = 28.75 + 15 + 25 + 8 = ₹76.75
6. Failure allowance = 76.75 × 10% = ₹7.675
7. Estimated cost = ₹84.425 → ₹84.43

If the customer pays ₹55, the platform subsidy is ₹29.43. The rider payout is ₹25, not ₹55. This isolated-trip example is not the universal cost; the default settings use a 1.6 factor.

## Shared routes (batching)
`allocate_shared_route(route_cost, stops, basis)` splits one route's cost by each order's own distance (or equally, or by weight); shares are rounded to paise and the rounding remainder goes to the largest share so they add up exactly. `batch_quote` prices one multi-drop route once (no per-order return factor) plus each order's own per-order pay and overhead. **Dispatch does not batch orders yet**; the admin simulator uses this to compare batched against isolated cost.

## Where amounts are frozen
At order placement each `StoreOrder` stores the full breakdown in `delivery_pricing` (JSON) with `delivery_pricing_version` and `delivery_distance_km`. Later fuel-price, setting or route changes never alter it. Rider earnings are created from that snapshot when the delivery completes.
