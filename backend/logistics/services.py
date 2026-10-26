"""Delivery pricing services: versions, zones, serviceability and per-store quotes."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.forms.models import model_to_dict
from django.utils import timezone

from core.audit import audit
from core.geo import valid_coordinates

from . import engine
from .models import DeliveryPricingVersion, PricingZone
from .providers import ProviderUnavailable, straight_line_km, travel_distance

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
VERSION_FIELDS = [
    f.name for f in DeliveryPricingVersion._meta.get_fields()
    if getattr(f, "concrete", False) and f.name not in {"id", "version", "created_by", "created_at", "currency", "zone"}
]


def local_now(now=None) -> datetime:
    return timezone.localtime(now or timezone.now(), ZoneInfo(getattr(settings, "BUSINESS_TIME_ZONE", "Asia/Kolkata")))


# ------------------------------------------------------------------ versions

def active_version(zone=None, now=None) -> DeliveryPricingVersion:
    now = now or timezone.now()
    qs = DeliveryPricingVersion.objects.filter(effective_from__lte=now)
    if zone is not None:
        found = qs.filter(zone=zone).order_by("-effective_from", "-version").first()
        if found:
            return found
    found = qs.filter(zone__isnull=True).order_by("-effective_from", "-version").first()
    if found is None:
        raise ValidationError({"detail": "Delivery pricing is not configured yet."})
    return found


def _check_settings(candidate: DeliveryPricingVersion):
    """Run the engine on sample distances so a version that cannot price an order is refused."""
    candidate.full_clean(exclude=["created_by", "version"])
    for km in ("0", "1", "3", "7.5"):
        if candidate.max_service_km is not None and Decimal(km) > candidate.max_service_km:
            continue
        engine.quote(candidate, engine.TripContext(distance_km=Decimal(km), items_subtotal=Decimal("0")))
    for item in candidate.peak_windows or []:
        if not isinstance(item, dict) or not set(item.get("days", [])) <= set(range(7)):
            raise ValidationError({"peak_windows": "Each window needs days 0–6 (Monday = 0)."})
        _hhmm(item.get("start")), _hhmm(item.get("end"))


def _hhmm(value):
    try:
        return datetime.strptime(str(value), "%H:%M").time()
    except ValueError:
        raise ValidationError({"peak_windows": "Times must look like 18:00."}) from None


@transaction.atomic
def create_version(*, actor, data: dict, zone=None, reason: str, effective_from=None, request=None) -> DeliveryPricingVersion:
    """New immutable version. Unknown keys are ignored; reason is required; audit records the diff."""
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError({"reason": "Say why the settings are changing."})
    effective_from = effective_from or timezone.now()
    if effective_from < timezone.now() - timezone.timedelta(minutes=5):
        raise ValidationError({"effective_from": "New settings cannot take effect in the past (placed orders keep their own prices)."})
    previous = DeliveryPricingVersion.objects.filter(zone=zone).order_by("-version").first()
    base = model_to_dict(previous, fields=VERSION_FIELDS) if previous else {}
    values = {**base, **{k: v for k, v in data.items() if k in VERSION_FIELDS}}
    values.pop("effective_from", None)
    values["reason"] = reason
    candidate = DeliveryPricingVersion(zone=zone, effective_from=effective_from, created_by=actor, **values)
    _check_settings(candidate)
    # Serialise version numbers per zone.
    list(DeliveryPricingVersion.objects.select_for_update().filter(zone=zone).values_list("pk", flat=True))
    candidate.version = (DeliveryPricingVersion.objects.filter(zone=zone).aggregate(m=Max("version"))["m"] or 0) + 1
    candidate.save()
    changes = {k: {"from": _plain(base.get(k)), "to": _plain(getattr(candidate, k))} for k in VERSION_FIELDS
               if previous is not None and _plain(base.get(k)) != _plain(getattr(candidate, k)) and k not in {"reason", "effective_from"}}
    audit(actor, "delivery_pricing.version_created", candidate, request=request,
          summary=f"Delivery pricing {candidate} effective {candidate.effective_from:%Y-%m-%d %H:%M}",
          reason=reason, zone=zone.pk if zone else None, changes=changes)
    return candidate


def _plain(value):
    if isinstance(value, Decimal):
        return str(value.normalize()) if value == value.to_integral() else str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def is_peak(version, now=None) -> bool:
    t = local_now(now)
    for w in version.peak_windows or []:
        if t.weekday() in w.get("days", []) and _hhmm(w["start"]) <= t.time() < _hhmm(w["end"]):
            return True
    return False


# ------------------------------------------------------------------ zones

def point_in_polygon(lat, lon, polygon) -> bool:
    """Ray casting on [[lat, lon], ...]. Fine for city-scale zones."""
    if not polygon or len(polygon) < 3:
        return False
    x, y = float(lon), float(lat)
    inside = False
    pts = [(float(p[1]), float(p[0])) for p in polygon]
    j = len(pts) - 1
    for i, (xi, yi) in enumerate(pts):
        xj, yj = pts[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def validate_polygon(polygon):
    if polygon in (None, []):
        return []
    if not isinstance(polygon, list) or len(polygon) < 3 or len(polygon) > 500:
        raise ValidationError({"polygon": "A zone needs 3 to 500 points."})
    clean = []
    for p in polygon:
        if not isinstance(p, (list, tuple)) or len(p) != 2 or not valid_coordinates(p[0], p[1]):
            raise ValidationError({"polygon": "Each point must be [latitude, longitude]."})
        clean.append([round(float(p[0]), 6), round(float(p[1]), 6)])
    return clean


def zone_for_point(lat, lon):
    for zone in PricingZone.objects.filter(is_active=True).exclude(polygon=[]):
        if point_in_polygon(lat, lon, zone.polygon):
            return zone
    return None


# ------------------------------------------------------------------ serviceability

def store_point(store):
    a = getattr(store, "address", None)
    if a is None or a.latitude is None or a.longitude is None or (not a.latitude and not a.longitude):
        return None
    return (a.latitude, a.longitude)


def store_location_problems(store) -> list[str]:
    """Plain-language reasons a store cannot be priced for delivery (shown to admins and the store)."""
    problems = []
    point = store_point(store)
    if point is None:
        problems.append("Map location is missing. Set the store's latitude and longitude on its profile.")
    elif not valid_coordinates(*point):
        problems.append("Map location is invalid.")
    elif not (Decimal("8") <= Decimal(point[0]) <= Decimal("13") and Decimal("74") <= Decimal(point[1]) <= Decimal("78")):
        problems.append("Map location is outside Kerala. Check the latitude and longitude are not swapped.")
    if getattr(settings, "STORE_PIN_CONFIRMATION_REQUIRED", False) and point is not None and not store.location_confirmed_at:
        problems.append("The map pin has not been confirmed. Check it sits at the pickup door, then confirm it.")
    if store.offers_delivery:
        if store.service_mode == "ZONE":
            if not store.service_zone_id or len((store.service_zone.polygon if store.service_zone_id else []) or []) < 3:
                problems.append("Service mode is 'zone' but no zone with a drawn area is selected.")
        elif not store.service_radius_km:
            problems.append("Delivery radius is not set.")
    return problems


def store_open_now(store, now=None):
    """(open, message). Stores without configured hours are treated as open (legacy behaviour)."""
    t = local_now(now)
    if any(c.get("date") == t.date().isoformat() for c in (store.closures or [])):
        return False, "Closed today."
    hours = store.opening_hours or {}
    if not any(hours.get(d) for d in DAYS):
        return True, ""
    slots = hours.get(DAYS[t.weekday()]) or []
    now_s = t.strftime("%H:%M")
    for slot in slots:
        if slot["open"] <= now_s < slot["close"]:
            return True, ""
    later = [s["open"] for s in slots if s["open"] > now_s]
    return False, f"Closed now. Opens at {min(later)}." if later else "Closed for today."


def serviceability(store, lat, lon, now=None) -> dict:
    """Can this store deliver to this point right now? Uses straight-line distance only as a pre-check."""
    reasons = []
    from stores.models import StoreStatus
    if store.status != StoreStatus.ACTIVE or not store.is_active:
        reasons.append("Store is not active.")
    if not store.offers_delivery:
        reasons.append("Store does not deliver (pickup only).")
    if not (store.accepts_orders and store.ordering_enabled):
        reasons.append("Store is not taking orders right now.")
    open_now, closed_msg = store_open_now(store, now)
    if not open_now:
        reasons.append(closed_msg)
    origin = store_point(store)
    straight = None
    if origin is None:
        reasons.append("Store location is not set.")
    elif getattr(settings, "STORE_PIN_CONFIRMATION_REQUIRED", False) and not store.location_confirmed_at:
        reasons.append("Store location has not been confirmed yet.")
    else:
        straight = straight_line_km(origin, (lat, lon))
        if store.service_mode == "ZONE" and store.service_zone_id:
            if not point_in_polygon(lat, lon, store.service_zone.polygon):
                reasons.append("Address is outside this store's delivery zone.")
        elif store.service_radius_km is not None and straight > store.service_radius_km:
            reasons.append(f"Address is {straight.quantize(Decimal('0.1'))} km away; this store delivers within {store.service_radius_km.normalize()} km.")
    return {"store_id": store.pk, "serviceable": not reasons, "reasons": reasons, "open_now": open_now,
            "straight_line_km": None if straight is None else str(straight.quantize(Decimal("0.01")))}


def quote_for_store(store, lat, lon, *, items_subtotal=Decimal("0"), now=None, heavy=False, check_service=True, estimate_only=False) -> dict:
    """Full delivery quote for one store and destination, or a ValidationError explaining why not."""
    if not valid_coordinates(lat, lon) or (not Decimal(str(lat)) and not Decimal(str(lon))):
        raise ValidationError({"address": "This address has no valid map location. Pin it on the map."})
    if check_service:
        svc = serviceability(store, lat, lon, now)
        if not svc["serviceable"]:
            raise ValidationError({"detail": f"{store.name}: " + " ".join(svc["reasons"])})
    zone = zone_for_point(lat, lon)
    version = active_version(zone=zone, now=now)
    try:
        if estimate_only:
            # Browsing lists use the straight-line estimate so every store shown does not cost a paid routing call.
            straight = straight_line_km(store_point(store), (lat, lon))
            km = (straight * Decimal(str(version.road_fallback_factor))).quantize(Decimal("0.001"))
            source, note = "estimated", ""
        else:
            km, source, note = travel_distance(store_point(store), (lat, lon), fallback_factor=version.road_fallback_factor,
                                               allow_estimate=version.allow_estimated_distance)
    except ProviderUnavailable:
        raise ValidationError({"detail": "We can't work out the road distance right now, so delivery can't be priced. Try again shortly or choose pickup."}) from None
    ctx = engine.TripContext(distance_km=km, items_subtotal=Decimal(items_subtotal), is_peak=is_peak(version, now),
                             zone_surcharge=zone.service_area_surcharge if zone else Decimal("0"), heavy=heavy,
                             distance_source=source, notes=[note] if note else [])
    result = engine.quote(version, ctx)
    result.update({"pricing_version_id": version.pk, "pricing_version": str(version), "zone": zone.name if zone else None,
                   "is_illustrative": version.is_illustrative, "eta_minutes": eta_minutes(store, km)})
    return jsonable(result)


def eta_minutes(store, km):
    """Prep time + ride at 20 km/h city speed. Shown as an estimate only."""
    return int(store.prep_time_minutes + (Decimal(km) / Decimal("20") * 60).to_integral_value())


def jsonable(value):
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [jsonable(v) for v in value]
    if isinstance(value, Decimal):
        return str(value)
    return value


def customer_view(q: dict) -> dict:
    """What a customer may see: distance, fee, discount, tax. No cost, rider pay or subsidy."""
    keys = ("distance_km", "distance_source", "customer_fee_before_discount", "delivery_discount", "discount_reason",
            "customer_fee", "delivery_tax", "customer_total", "surcharges", "eta_minutes", "notes")
    out = {k: q.get(k) for k in keys}
    out["explanation"] = "Delivery fee based on distance" + (" (estimated distance)" if q.get("distance_source") == "estimated" else "")
    return out
