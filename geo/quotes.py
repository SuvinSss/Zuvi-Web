"""Delivery quote lifecycle: create, validate at checkout, consume.

A quote binds one customer, one delivery address (by coordinates), one basket
shape (stores and their item subtotals) and one pricing version. Any change to
those invalidates it. Clients never supply prices: checkout recomputes the
fingerprint from the live cart and compares.
"""

import hashlib
import json
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import routing
from .coords import parse_coordinate
from .errors import MapsError, QuoteError
from .models import DeliveryQuote, DeliveryQuoteLeg, QuoteStatus
from .pricing import get_active_config, price_leg
from .serviceability import MESSAGES, evaluate_store, store_coordinate


class NotServiceable(MapsError):
    code = "NOT_SERVICEABLE"
    http_status = 422
    retryable = False
    public_message = "We can't deliver the items in your basket to this address."

    def __init__(self, reasons):
        super().__init__("not serviceable")
        self.reasons = reasons


def basket_shape(customer):
    """[(store_id, store_name, items_subtotal)] from the live cart, server side."""
    from orders.services import build_checkout_preview

    preview = build_checkout_preview(customer)
    if preview["is_empty"]:
        raise QuoteError("empty cart", public_message="Your basket is empty.")
    return [(g["store_id"], g["store_name"], g["items_subtotal"]) for g in preview["store_groups"]]


def make_fingerprint(*, customer_id, destination, config_id, shape):
    payload = {
        "c": customer_id,
        "d": [str(destination.latitude), str(destination.longitude)],
        "p": config_id,
        "s": sorted((sid, str(Decimal(sub).quantize(Decimal("0.01")))) for sid, _, sub in shape),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def create_quote(customer, customer_address) -> DeliveryQuote:
    """Price delivery for the customer's current basket to one of their addresses."""
    from stores.models import Store

    config = get_active_config()
    address = customer_address.address
    destination = parse_coordinate(address.latitude, address.longitude)
    shape = basket_shape(customer)
    stores = {
        s.pk: s for s in Store.objects.filter(pk__in=[sid for sid, _, _ in shape]).select_related("address")
    }

    reasons, eligible = [], []
    for store_id, store_name, subtotal in shape:
        store = stores.get(store_id)
        if store is None:
            reasons.append({"store_id": store_id, "store_name": store_name, "code": "STORE_INACTIVE",
                            "message": MESSAGES["STORE_INACTIVE"]})
            continue
        verdict = evaluate_store(store, destination)
        if not verdict.eligible:
            for reason in verdict.reasons:
                reasons.append({"store_id": store_id, "store_name": store_name, **reason})
            continue
        eligible.append((store, subtotal))
    if reasons:
        raise NotServiceable(reasons)

    # Final distance decision uses Google road routing (one call, or one matrix).
    routes = routing.get_routes_from_origins(
        [(str(store.pk), store_coordinate(store)) for store, _ in eligible],
        destination,
        destination_ref=f"address:{customer_address.pk}",
    )
    legs, max_km = [], Decimal(config.max_road_distance_km)
    for store, subtotal in eligible:
        route = routes[str(store.pk)]
        if isinstance(route, routing.RouteFailure):
            code = "NO_ROUTE" if route.error.code == "NO_ROUTE" else "ROUTE_UNAVAILABLE"
            reasons.append({"store_id": store.pk, "store_name": store.name, "code": code,
                            "message": MESSAGES[code]})
            continue
        if route.distance_km > max_km:
            reasons.append({"store_id": store.pk, "store_name": store.name, "code": "OUTSIDE_ROAD_RANGE",
                            "message": MESSAGES["OUTSIDE_ROAD_RANGE"]})
            continue
        legs.append((store, subtotal, route, price_leg(config, road_distance_meters=route.distance_meters,
                                                       items_subtotal=subtotal)))
    if reasons:
        # A transient routing failure is reported as such rather than as "too far".
        unavailable = [r for r in reasons if r["code"] == "ROUTE_UNAVAILABLE"]
        if unavailable and len(unavailable) == len(reasons):
            first = next(r for r in routes.values() if isinstance(r, routing.RouteFailure))
            raise first.error
        raise NotServiceable(reasons)

    now = timezone.now()
    total_before = sum((p.fee_before_discount for *_, p in legs), Decimal("0.00"))
    total_discount = sum((p.discount for *_, p in legs), Decimal("0.00"))
    total_fee = sum((p.fee_after_discount for *_, p in legs), Decimal("0.00"))

    with transaction.atomic():
        DeliveryQuote.objects.select_for_update().filter(
            customer=customer, status=QuoteStatus.ACTIVE
        ).update(status=QuoteStatus.SUPERSEDED)
        quote = DeliveryQuote.objects.create(
            customer=customer,
            customer_address=customer_address,
            destination_latitude=destination.latitude,
            destination_longitude=destination.longitude,
            pricing_config=config,
            fingerprint=make_fingerprint(
                customer_id=customer.pk, destination=destination, config_id=config.pk, shape=shape
            ),
            delivery_fee_before_discount=total_before,
            delivery_discount=total_discount,
            delivery_fee=total_fee,
            expires_at=now + timedelta(seconds=settings.DELIVERY_QUOTE_TTL_SECONDS),
        )
        for store, subtotal, route, pricing in legs:
            DeliveryQuoteLeg.objects.create(
                quote=quote,
                store=store,
                store_code=store.store_code,
                items_subtotal=subtotal,
                route_distance_meters=route.distance_meters,
                route_duration_seconds=route.duration_seconds,
                route_source=route.source,
                route_provider=route.provider,
                route_travel_mode=route.travel_mode,
                route_calculated_at=route.calculated_at,
                operational_distance_km=pricing.operational_distance_km,
                operational_cost=pricing.operational_cost,
                rider_payout=pricing.rider_payout,
                fee_before_discount=pricing.fee_before_discount,
                discount=pricing.discount,
                fee_after_discount=pricing.fee_after_discount,
                platform_subsidy=pricing.platform_subsidy,
                store_funded_discount=pricing.store_funded_discount,
                unrecovered_cost=pricing.unrecovered_cost,
            )
    return quote


def lock_valid_quote(customer, quote_id, customer_address) -> DeliveryQuote:
    """Return the locked quote if it may be used now, else raise QuoteError.

    Must be called inside the order transaction. Ownership is part of the query so
    another customer's quote id is indistinguishable from a missing one.
    """
    try:
        quote_id = int(quote_id)
    except (TypeError, ValueError):
        raise QuoteError("bad id") from None
    quote = (
        DeliveryQuote.objects.select_for_update()
        .select_related("pricing_config")
        .filter(pk=quote_id, customer=customer)
        .first()
    )
    if quote is None:
        raise QuoteError("not found")
    if quote.status != QuoteStatus.ACTIVE:
        raise QuoteError(f"status {quote.status}")
    if quote.expires_at <= timezone.now():
        raise QuoteError("expired", public_message="Your delivery quote expired. Please review the delivery fee.")
    if not quote.pricing_config.is_active:
        raise QuoteError("pricing version changed")
    address = customer_address.address
    destination = parse_coordinate(address.latitude, address.longitude)
    shape = basket_shape(customer)
    expected = make_fingerprint(
        customer_id=customer.pk, destination=destination, config_id=quote.pricing_config_id, shape=shape
    )
    if expected != quote.fingerprint or quote.customer_address_id != customer_address.pk:
        raise QuoteError("basket or address changed")
    return quote


def build_order_snapshot(quote) -> dict:
    """Immutable evidence stored on the Order. Contains internal costs; never serialised to customers."""
    return {
        "quote_id": quote.pk,
        "pricing_version": quote.pricing_config.version,
        "created_at": quote.created_at.isoformat(),
        "destination": [str(quote.destination_latitude), str(quote.destination_longitude)],
        "delivery_fee_before_discount": str(quote.delivery_fee_before_discount),
        "delivery_discount": str(quote.delivery_discount),
        "delivery_fee": str(quote.delivery_fee),
        "legs": [
            {
                "store_code": leg.store_code,
                "items_subtotal": str(leg.items_subtotal),
                "route": {
                    "distance_meters": leg.route_distance_meters,
                    "duration_seconds": leg.route_duration_seconds,
                    "source": leg.route_source,
                    "provider": leg.route_provider,
                    "travel_mode": leg.route_travel_mode,
                    "calculated_at": leg.route_calculated_at.isoformat(),
                },
                "operational_distance_km": str(leg.operational_distance_km),
                "operational_cost": str(leg.operational_cost),
                "rider_payout": str(leg.rider_payout),
                "fee_before_discount": str(leg.fee_before_discount),
                "discount": str(leg.discount),
                "fee_after_discount": str(leg.fee_after_discount),
                "platform_subsidy": str(leg.platform_subsidy),
                "store_funded_discount": str(leg.store_funded_discount),
                "unrecovered_cost": str(leg.unrecovered_cost),
            }
            for leg in quote.legs.all()
        ],
    }


def consume_quote(quote, order):
    quote.status = QuoteStatus.CONSUMED
    quote.save(update_fields=["status"])
    return quote
