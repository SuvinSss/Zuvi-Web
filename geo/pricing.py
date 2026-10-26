"""Delivery pricing calculation.

Pure Decimal arithmetic over a ``DeliveryPricingConfig``. This is the only
place delivery prices are computed; checkout quotes and the admin simulator
both call ``price_leg``. Nothing here trusts client-supplied amounts.
"""

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

from .errors import PricingNotConfigured

CENT = Decimal("0.01")


def _q(value):
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class LegPricing:
    road_distance_km: Decimal
    operational_distance_km: Decimal
    operational_cost: Decimal
    rider_payout: Decimal
    fee_before_discount: Decimal
    discount: Decimal
    fee_after_discount: Decimal
    platform_subsidy: Decimal
    store_funded_discount: Decimal
    unrecovered_cost: Decimal
    contribution: Decimal  # customer fee + store funded discount - operational cost; may be negative

    def customer_view(self):
        """Fields that may be shown to a customer. No internal cost data."""
        return {
            "delivery_fee_before_discount": str(self.fee_before_discount),
            "delivery_discount": str(self.discount),
            "delivery_fee": str(self.fee_after_discount),
        }


def get_active_config():
    from .models import DeliveryPricingConfig

    config = DeliveryPricingConfig.objects.filter(is_active=True).first()
    if config is None:
        raise PricingNotConfigured("no active DeliveryPricingConfig")
    return config


def _round_to_step(amount, step):
    if step <= 0:
        return _q(amount)
    return _q((amount / step).to_integral_value(rounding=ROUND_CEILING) * step)


def price_leg(config, *, road_distance_meters, items_subtotal) -> LegPricing:
    road_km = Decimal(road_distance_meters) / Decimal(1000)

    # Operational model
    operational_km = max(
        road_km * config.operational_distance_multiplier, config.minimum_operational_distance_km
    )
    fuel_cost = operational_km / config.vehicle_mileage_km_per_litre * config.fuel_price_per_litre
    maintenance = operational_km * config.maintenance_cost_per_km
    rider_payout = config.rider_base_payout + road_km * config.rider_payout_per_km
    operational_cost = fuel_cost + maintenance + rider_payout + config.other_cost_per_delivery

    # Customer tariff
    chargeable_km = max(Decimal("0"), road_km - config.customer_free_distance_km)
    fee = config.customer_base_fee + chargeable_km * config.customer_fee_per_km
    fee = max(fee, config.customer_minimum_fee)
    if config.customer_maximum_fee is not None:
        fee = min(fee, config.customer_maximum_fee)
    fee_before = _round_to_step(fee, config.fee_rounding_step)
    if config.customer_maximum_fee is not None:
        fee_before = min(fee_before, _q(config.customer_maximum_fee))

    # Offers
    discount = Decimal("0.00")
    if config.free_delivery_threshold is not None and items_subtotal >= config.free_delivery_threshold:
        discount = fee_before
    fee_after = _q(fee_before - discount)
    store_funded = _q(discount * config.store_funded_discount_percent / Decimal(100))
    platform_subsidy = _q(discount - store_funded)

    income = fee_after + store_funded
    contribution = _q(income - operational_cost)
    unrecovered = _q(max(Decimal("0"), operational_cost - income))

    return LegPricing(
        road_distance_km=road_km.quantize(Decimal("0.001")),
        operational_distance_km=operational_km.quantize(Decimal("0.001")),
        operational_cost=_q(operational_cost),
        rider_payout=_q(rider_payout),
        fee_before_discount=fee_before,
        discount=_q(discount),
        fee_after_discount=fee_after,
        platform_subsidy=platform_subsidy,
        store_funded_discount=store_funded,
        unrecovered_cost=unrecovered,
        contribution=contribution,
    )
