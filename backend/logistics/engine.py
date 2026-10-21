"""Delivery pricing engine: pure, deterministic, Decimal-only.

Everything here is a function of a settings object (a ``DeliveryPricingVersion``
or any object with the same attributes) and the trip inputs. No database, no
clock, no network: callers pass ``now``/``is_peak`` and the distance. That keeps
checkout, the admin simulator and the tests on exactly the same code.

Units: distances in kilometres, money in INR, rates as fractions (0.10 = 10%).
See docs/delivery-pricing-algorithm.md for the formulas and the worked example.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal, InvalidOperation

from django.core.exceptions import ValidationError

ZERO = Decimal("0")
CENT = Decimal("0.01")
FINE = Decimal("0.0001")  # internal precision; money is rounded to paise only at the edges


class Mode:
    BANDS = "BANDS"
    BASE_PLUS_DISTANCE = "BASE_PLUS_DISTANCE"
    COST_AWARE = "COST_AWARE"
    HYBRID = "HYBRID"
    CHOICES = [
        (BANDS, "Distance bands"),
        (BASE_PLUS_DISTANCE, "Base fee + per-km beyond included distance"),
        (COST_AWARE, "Cost-aware (recover a share of estimated cost)"),
        (HYBRID, "Hybrid (distance tariff, platform subsidy capped per order)"),
    ]


class Rounding:
    NONE = "NONE"
    NEAREST_RUPEE = "NEAREST_RUPEE"
    UP_RUPEE = "UP_RUPEE"
    CHOICES = [(NONE, "Paise (no rupee rounding)"), (NEAREST_RUPEE, "Nearest rupee"), (UP_RUPEE, "Round up to the rupee")]


class Funder:
    PLATFORM = "PLATFORM"
    STORE = "STORE"
    CHOICES = [(PLATFORM, "Zuuvi (platform)"), (STORE, "Store")]


def D(value, field_name="value") -> Decimal:
    if value is None or value == "":
        raise ValidationError({field_name: "This value is required."})
    try:
        out = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError({field_name: "Enter a valid number."}) from None
    if not out.is_finite():
        raise ValidationError({field_name: "Enter a valid number."})
    return out


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _fine(value: Decimal) -> Decimal:
    return value.quantize(FINE, rounding=ROUND_HALF_UP)


def round_fee(value: Decimal, policy: str) -> Decimal:
    if policy == Rounding.NEAREST_RUPEE:
        return value.quantize(Decimal("1"), rounding=ROUND_HALF_UP).quantize(CENT)
    if policy == Rounding.UP_RUPEE:
        return value.quantize(Decimal("1"), rounding=ROUND_CEILING).quantize(CENT)
    return money(value)


def validate_distance(distance_km) -> Decimal:
    d = D(distance_km, "distance_km")
    if d < 0:
        raise ValidationError({"distance_km": "Distance cannot be negative."})
    if d > Decimal("1000"):
        raise ValidationError({"distance_km": "Distance is not plausible for a local delivery."})
    return d


def fuel_cost_per_km(s) -> Decimal:
    """Energy price per unit ÷ distance per unit. Petrol: ₹/litre ÷ km/litre. EV: ₹/kWh ÷ km/kWh."""
    price = D(s.energy_price, "energy_price")
    efficiency = D(s.efficiency_km_per_unit, "efficiency_km_per_unit")
    if efficiency <= 0:
        raise ValidationError({"efficiency_km_per_unit": "Mileage or efficiency must be greater than zero."})
    if price < 0:
        raise ValidationError({"energy_price": "Fuel or energy price cannot be negative."})
    return price / efficiency


def rider_compensation(s, distance_km: Decimal) -> dict:
    """Per-order pay + per-km incentive on the delivery distance + fixed daily pay spread over expected orders.

    Each component is counted once. Failed-attempt pay is not part of a normal order;
    it is added only to an attempt that actually failed (see ``failed_attempt_payout``).
    """
    per_order = D(s.rider_pay_per_order, "rider_pay_per_order")
    per_km = D(s.rider_pay_per_km, "rider_pay_per_km") * distance_km
    fixed_share = ZERO
    if D(s.rider_fixed_daily_pay, "rider_fixed_daily_pay") > 0:
        orders = D(s.rider_expected_orders_per_day, "rider_expected_orders_per_day")
        if orders <= 0:
            raise ValidationError({"rider_expected_orders_per_day": "Expected orders per day must be above zero to share fixed pay."})
        fixed_share = D(s.rider_fixed_daily_pay) / orders
    return {"per_order": per_order, "per_km": per_km, "fixed_share": fixed_share, "total": per_order + per_km + fixed_share}


def estimate_cost(s, distance_km, *, heavy=False) -> dict:
    """Steps A–E: the estimated cost to fulfil one isolated delivery. Not the customer fee."""
    d = validate_distance(distance_km)
    multiplier = D(s.operational_multiplier, "operational_multiplier")
    if multiplier < 1:
        raise ValidationError({"operational_multiplier": "The operational distance factor cannot be below 1."})
    per_km = fuel_cost_per_km(s)
    op_km = d * multiplier
    fuel = op_km * per_km
    maintenance = op_km * D(s.maintenance_per_km, "maintenance_per_km")
    rider = rider_compensation(s, d)
    overhead = D(s.overhead_per_order, "overhead_per_order") + D(s.overhead_per_km, "overhead_per_km") * op_km
    direct = fuel + maintenance + rider["total"] + overhead
    rate = D(s.failure_cost_rate, "failure_cost_rate")
    if rate < 0 or rate > 1:
        raise ValidationError({"failure_cost_rate": "Failure allowance must be between 0 and 100%."})
    failure = direct * rate
    extra = D(s.special_handling_cost, "special_handling_cost") if heavy else ZERO
    total = direct + failure + extra
    return {
        "distance_km": d, "operational_multiplier": multiplier, "operational_km": op_km,
        "fuel_cost_per_km": per_km, "fuel_cost": fuel, "maintenance_cost": maintenance,
        "rider_compensation": rider["total"], "rider_breakdown": rider, "overhead": overhead,
        "direct_operating_cost": direct, "failure_allowance": failure, "extra_costs": extra,
        "estimated_cost": total,
    }


def distance_tariff(s, d: Decimal) -> Decimal:
    """The pure distance price for the configured mode (bands or base + per-km)."""
    if s.pricing_mode == Mode.BANDS:
        bands = sorted(s.distance_bands or [], key=lambda b: D(b["up_to_km"], "distance_bands"))
        if not bands:
            raise ValidationError({"distance_bands": "Add at least one distance band."})
        for band in bands:
            if d <= D(band["up_to_km"], "distance_bands"):
                return D(band["fee"], "distance_bands")
        # Beyond the last band: last band fee + per-km for the extra distance.
        last = bands[-1]
        return D(last["fee"]) + (d - D(last["up_to_km"])) * D(s.per_km_rate, "per_km_rate")
    included = D(s.included_km, "included_km")
    return D(s.base_fee, "base_fee") + max(ZERO, d - included) * D(s.per_km_rate, "per_km_rate")


@dataclass
class TripContext:
    distance_km: Decimal
    items_subtotal: Decimal = ZERO
    is_peak: bool = False
    zone_surcharge: Decimal = ZERO
    heavy: bool = False
    distance_source: str = "road"   # "road" | "estimated" (straight line × fallback factor) | "manual" (simulator)
    notes: list = field(default_factory=list)


def quote(s, ctx: TripContext) -> dict:
    """Steps A–G for one store-to-customer delivery. Returns every amount separately.

    customer_fee_before_discount → discounts (with funder) → customer_fee → tax → customer_total.
    Partner payout, platform-funded promotion, store-funded promotion and the platform's
    subsidy (or contribution) are reported separately and never netted into one "profit".
    """
    cost = estimate_cost(s, ctx.distance_km, heavy=ctx.heavy)
    d = cost["distance_km"]
    max_km = s.max_service_km
    if max_km is not None and d > D(max_km, "max_service_km"):
        raise ValidationError({"distance_km": f"This address is {money(d)} km away; the maximum delivery distance is {money(D(max_km))} km."})

    tariff = distance_tariff(s, d) if s.pricing_mode in (Mode.BANDS, Mode.BASE_PLUS_DISTANCE) else _base_plus(s, d)
    recovery_target = None
    if s.pricing_mode == Mode.COST_AWARE:
        ratio = D(s.customer_recovery_ratio, "customer_recovery_ratio")
        if ratio < 0 or ratio > 2:
            raise ValidationError({"customer_recovery_ratio": "Recovery ratio must be between 0 and 200%."})
        recovery_target = cost["estimated_cost"] * ratio
        tariff = max(tariff, recovery_target)
    elif s.pricing_mode == Mode.HYBRID:
        cap = D(s.max_platform_subsidy_per_order, "max_platform_subsidy_per_order")
        recovery_target = max(ZERO, cost["estimated_cost"] - cap)
        tariff = max(tariff, recovery_target)

    surcharges = {
        "peak": D(s.peak_surcharge, "peak_surcharge") if ctx.is_peak else ZERO,
        "service_area": D(ctx.zone_surcharge or 0, "zone_surcharge"),
        "special_handling": D(s.heavy_surcharge, "heavy_surcharge") if ctx.heavy else ZERO,
    }
    raw = tariff + sum(surcharges.values())

    min_fee, max_fee = D(s.min_fee, "min_fee"), D(s.max_fee, "max_fee")
    if max_fee < min_fee:
        raise ValidationError({"max_fee": "Maximum fee must be at least the minimum fee."})
    capped_by_max = ZERO
    clamped = max(raw, min_fee)
    if clamped > max_fee and not s.allow_above_max_fee:
        capped_by_max = clamped - max_fee
        clamped = max_fee
    fee_before = round_fee(clamped, s.rounding)

    # Discounts: free delivery first (it removes the whole fee), otherwise a flat delivery discount.
    subtotal = D(ctx.items_subtotal or 0, "items_subtotal")
    discount, funder, reason = ZERO, None, ""
    threshold = s.free_delivery_threshold
    if threshold is not None and subtotal >= D(threshold, "free_delivery_threshold"):
        discount, funder, reason = fee_before, s.free_delivery_funded_by, f"Free delivery on orders of ₹{money(D(threshold))} or more"
    elif D(s.delivery_discount_amount or 0, "delivery_discount_amount") > 0 and subtotal >= D(s.delivery_discount_min_order or 0, "delivery_discount_min_order"):
        discount, funder, reason = min(fee_before, D(s.delivery_discount_amount)), s.delivery_discount_funded_by, "Delivery discount"
    fee_after = money(fee_before - discount)

    tax_rate = D(s.delivery_tax_rate or 0, "delivery_tax_rate")
    tax = money(fee_after * tax_rate)
    platform_promo = discount if funder == Funder.PLATFORM else ZERO
    store_promo = discount if funder == Funder.STORE else ZERO

    rider = cost["rider_compensation"]
    # Zuuvi recovers the customer's fee (excl. tax, which is passed on) and any store-funded promotion.
    recovered = fee_after + store_promo
    gap = cost["estimated_cost"] - recovered
    out = {
        "distance_km": money(d), "distance_source": ctx.distance_source,
        "pricing_mode": s.pricing_mode,
        "cost": {k: (money(v) if isinstance(v, Decimal) and k != "fuel_cost_per_km" else v) for k, v in cost.items() if k != "rider_breakdown"},
        "rider_breakdown": {k: money(v) for k, v in cost["rider_breakdown"].items()},
        "distance_tariff": money(tariff if recovery_target is None else distance_tariff(s, d) if s.pricing_mode in (Mode.BANDS, Mode.BASE_PLUS_DISTANCE) else _base_plus(s, d)),
        "recovery_target": None if recovery_target is None else money(recovery_target),
        "surcharges": {k: money(v) for k, v in surcharges.items()},
        "raw_fee": money(raw),
        "capped_by_max_fee": money(capped_by_max),
        "customer_fee_before_discount": fee_before,
        "delivery_discount": money(discount),
        "discount_funded_by": funder,
        "discount_reason": reason,
        "customer_fee": fee_after,
        "delivery_tax_rate": tax_rate,
        "delivery_tax": tax,
        "customer_total": money(fee_after + tax),
        "partner_payout": money(rider),
        "platform_funded_promotion": money(platform_promo),
        "store_funded_promotion": money(store_promo),
        "estimated_cost": money(cost["estimated_cost"]),
        "platform_subsidy": money(max(ZERO, gap)),
        "delivery_contribution": money(max(ZERO, -gap)),
        "notes": list(ctx.notes),
    }
    out["cost"]["fuel_cost_per_km"] = _fine(cost["fuel_cost_per_km"])
    out["cost"]["operational_km"] = _fine(cost["operational_km"])
    return out


def _base_plus(s, d):
    included = D(s.included_km, "included_km")
    return D(s.base_fee, "base_fee") + max(ZERO, d - included) * D(s.per_km_rate, "per_km_rate")


def failed_attempt_payout(s) -> Decimal:
    """What a rider earns for an attempt that failed through no fault of theirs."""
    return money(D(s.rider_pay_per_failed_attempt, "rider_pay_per_failed_attempt"))


def allocate_shared_route(route_cost, stops, *, basis="distance"):
    """Split one route's cost across the orders actually carried on it.

    ``stops``: [{"key": ..., "distance_km": ..., "weight": optional}]. ``basis`` is
    "distance" (each order's own store-to-door distance), "equal" or "weight".
    Shares are rounded to paise; any rounding remainder goes to the largest share
    so the shares always add up to the route cost exactly.
    """
    total = money(D(route_cost, "route_cost"))
    if total < 0:
        raise ValidationError({"route_cost": "Route cost cannot be negative."})
    if not stops:
        raise ValidationError({"stops": "Add at least one order to the route."})
    if basis == "equal":
        weights = [Decimal(1)] * len(stops)
    elif basis == "weight":
        weights = [D(s.get("weight"), "weight") for s in stops]
    else:
        weights = [validate_distance(s.get("distance_km")) for s in stops]
    if any(w < 0 for w in weights):
        raise ValidationError({"stops": "Weights cannot be negative."})
    total_w = sum(weights)
    if total_w == 0:
        weights, total_w = [Decimal(1)] * len(stops), Decimal(len(stops))
    shares = [money(total * w / total_w) for w in weights]
    diff = total - sum(shares)
    if diff:
        shares[max(range(len(shares)), key=lambda i: shares[i])] += diff
    return [{"key": s.get("key"), "share": share} for s, share in zip(stops, shares)]


def batch_quote(s, *, route_km, stops, basis="distance"):
    """Cost of one multi-drop route, allocated per order (used by the simulator).

    The route's operational cost is computed once from the real route length
    (no per-order return-trip multiplier), plus each order's own rider per-order pay.
    """
    route_km = validate_distance(route_km)
    per_km = fuel_cost_per_km(s)
    shared = route_km * per_km + route_km * D(s.maintenance_per_km) + route_km * D(s.overhead_per_km) + route_km * D(s.rider_pay_per_km)
    shared += shared * D(s.failure_cost_rate)
    allocations = allocate_shared_route(shared, stops, basis=basis)
    per_order_fixed = money((D(s.rider_pay_per_order) + D(s.overhead_per_order)) * (1 + D(s.failure_cost_rate)))
    for a in allocations:
        a["per_order_costs"] = per_order_fixed
        a["estimated_cost"] = money(a["share"] + per_order_fixed)
    isolated = [money(estimate_cost(s, st["distance_km"])["estimated_cost"]) for st in stops]
    return {"route_km": money(route_km), "shared_route_cost": money(shared), "allocations": allocations,
            "batched_total": money(sum(a["estimated_cost"] for a in allocations)), "isolated_total": money(sum(isolated))}
