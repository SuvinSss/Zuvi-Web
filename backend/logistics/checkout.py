"""Delivery fees at checkout: per-store quotes, the customer-facing quote token and the order snapshot."""
from __future__ import annotations

import hashlib
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import CheckoutQuote
from .services import customer_view, quote_for_store

ZERO = Decimal("0.00")


class PriceChanged(ValidationError):
    """The price the customer confirmed no longer applies. Carries a fresh comparison."""


def address_point(address):
    """(lat, lon) for a CustomerAddress, or None when it was never pinned."""
    a = address.address
    if a.latitude is None or a.longitude is None or (not a.latitude and not a.longitude):
        return None
    return (a.latitude, a.longitude)


def store_quotes(groups, address, *, now=None) -> dict:
    """groups: [(store, items_subtotal)]. Returns per-store results; never raises for one bad store."""
    point = address_point(address) if address is not None else None
    results, total, ok = [], ZERO, True
    for store, subtotal in groups:
        entry = {"store_id": store.pk, "store_name": store.name}
        if point is None:
            entry.update(ok=False, error="This address has no map pin. Edit it and confirm the location on the map.")
        else:
            try:
                q = quote_for_store(store, point[0], point[1], items_subtotal=subtotal, now=now)
                entry.update(ok=True, quote=q, customer=customer_view(q))
                total += Decimal(q["customer_total"])
            except ValidationError as exc:
                msgs = exc.message_dict if hasattr(exc, "error_dict") else {"detail": exc.messages}
                entry.update(ok=False, error=" ".join(m for v in msgs.values() for m in v))
        ok = ok and entry["ok"]
        results.append(entry)
    return {"stores": results, "delivery_total": total.quantize(Decimal("0.01")), "all_ok": ok}


def fingerprint(lines, address, fulfillment_type) -> str:
    """Cart contents + address + method. A change means a new quote is needed."""
    parts = [fulfillment_type]
    if address is not None:
        a = address.address
        parts += [str(address.pk), str(a.latitude), str(a.longitude), address.updated_at.isoformat()]
    parts += sorted(f"{pid}:{qty}:{price}" for pid, qty, price in lines)
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def save_quote(*, customer, address, fulfillment_type, fp, result, items_subtotal) -> CheckoutQuote:
    ttl = int(getattr(settings, "CHECKOUT_QUOTE_TTL_SECONDS", 600))
    grand = (Decimal(items_subtotal) + result["delivery_total"]).quantize(Decimal("0.01"))
    return CheckoutQuote.objects.create(
        customer=customer, address=address, fulfillment_type=fulfillment_type, fingerprint=fp,
        data={"stores": [{k: v for k, v in s.items() if k != "quote"} | ({"quote": s["quote"]} if "quote" in s else {}) for s in result["stores"]]},
        delivery_total=result["delivery_total"], grand_total=grand, expires_at=timezone.now() + timedelta(seconds=ttl),
    )


def check_quote(*, customer, token, fp, result, items_subtotal):
    """Raise PriceChanged with a plain explanation if what the customer confirmed no longer holds."""
    quote = CheckoutQuote.objects.filter(customer=customer, token=token).first()
    if quote is None:
        raise ValidationError({"quote_token": "This price check was not found. Review your order again."})
    if quote.order_id is not None:
        raise ValidationError({"quote_token": "This price check was already used for an order."})
    if quote.expires_at < timezone.now():
        raise PriceChanged({"quote_token": "Prices were checked too long ago. Please review the updated total."})
    if quote.fingerprint != fp:
        raise PriceChanged({"quote_token": "Your cart or address changed since the price check. Please review the updated total."})
    new_grand = (Decimal(items_subtotal) + result["delivery_total"]).quantize(Decimal("0.01"))
    if new_grand != quote.grand_total or result["delivery_total"] != quote.delivery_total:
        reasons = []
        old = {s["store_id"]: s for s in quote.data.get("stores", [])}
        for s in result["stores"]:
            before = old.get(s["store_id"], {}).get("customer") or {}
            after = s.get("customer") or {}
            if before.get("customer_total") != after.get("customer_total"):
                why = ""
                if Decimal(before.get("delivery_discount") or 0) > 0 and Decimal(after.get("delivery_discount") or 0) == 0:
                    why = f" ({before.get('discount_reason') or 'the delivery offer'} no longer applies)"
                reasons.append(f"{s['store_name']}: delivery ₹{before.get('customer_total')} → ₹{after.get('customer_total')}{why}")
        raise PriceChanged({"quote_token": "The total changed from ₹{} to ₹{}. {}".format(quote.grand_total, new_grand, "; ".join(reasons)).strip()})
    return quote


def snapshot_for_store_order(entry) -> dict:
    """Everything needed to explain this fee later. Stored on the StoreOrder."""
    q = entry["quote"]
    return {**q, "captured_at": timezone.now().isoformat()}
