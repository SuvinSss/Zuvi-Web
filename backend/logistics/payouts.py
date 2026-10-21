"""Delivery partner earnings, created from the order's frozen pricing snapshot."""
from decimal import Decimal

from django.db import IntegrityError, transaction

from core.geo import haversine_m

from . import engine
from .models import PartnerEarning
from .services import active_version

# Failure reasons that are the rider's own responsibility are not paid.
UNPAID_FAILURE_REASONS = {"VEHICLE_PROBLEM"}


def _snapshot(delivery):
    return delivery.store_order.delivery_pricing or {}


def _create(**kwargs):
    try:
        with transaction.atomic():
            return PartnerEarning.objects.create(**kwargs)
    except IntegrityError:  # already recorded (retry of the same event)
        return None


def record_delivery_earning(delivery):
    """Called when a delivery is completed. Idempotent per delivery attempt."""
    if delivery.partner_id is None:
        return None
    snap = _snapshot(delivery)
    if snap.get("partner_payout") is not None:
        amount = Decimal(snap["partner_payout"])
        breakdown = {"source": "order snapshot", "pricing_version": snap.get("pricing_version"),
                     "distance_km": snap.get("distance_km"), "distance_source": snap.get("distance_source"),
                     **{f"rider_{k}": v for k, v in (snap.get("rider_breakdown") or {}).items()}}
    else:
        # Orders placed before delivery pricing existed: price the rider pay now and say so.
        version = active_version()
        km = Decimal("0")
        if None not in (delivery.pickup_latitude, delivery.dropoff_latitude):
            km = Decimal(str(haversine_m(delivery.pickup_latitude, delivery.pickup_longitude,
                                         delivery.dropoff_latitude, delivery.dropoff_longitude))) / 1000 * version.road_fallback_factor
        rider = engine.rider_compensation(version, km)
        amount = engine.money(rider["total"])
        breakdown = {"source": "estimated at completion (order had no pricing snapshot)", "pricing_version": str(version),
                     "distance_km": str(engine.money(km)), **{f"rider_{k}": str(engine.money(v)) for k, v in rider.items()}}
    return _create(partner_id=delivery.partner_id, delivery=delivery, attempt_number=delivery.attempt_number,
                   kind=PartnerEarning.Kind.DELIVERY, amount=amount, breakdown=breakdown)


def record_failed_attempt_earning(delivery, reason):
    """Pay a failed attempt that was not the rider's fault, using the order's pricing version."""
    if delivery.partner_id is None or reason in UNPAID_FAILURE_REASONS:
        return None
    version = delivery.store_order.delivery_pricing_version or active_version()
    amount = engine.failed_attempt_payout(version)
    if amount <= 0:
        return None
    return _create(partner_id=delivery.partner_id, delivery=delivery, attempt_number=delivery.attempt_number,
                   kind=PartnerEarning.Kind.FAILED_ATTEMPT, amount=amount,
                   breakdown={"source": "failed attempt", "reason": reason, "pricing_version": str(version)})
