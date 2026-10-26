"""Store location maintenance shared by the Store portal and the admin area."""

import logging
from collections import defaultdict

from django.db import transaction
from django.utils import timezone

from .coords import coordinate_issues
from .serviceability import store_location_issues

logger = logging.getLogger("geo.stores")

ISSUE_TEXT = {
    "missing": ("The store has no coordinates.", "Search for the address and place the pin."),
    "invalid": ("The coordinates are not valid.", "Place the pin on the map again."),
    "null_island": ("The pin is at 0, 0, which is not a real location.", "Place the pin at the store."),
    "outside_india": ("The pin is outside India.", "Check the pin and move it to the store."),
    "unconfirmed": ("The location has not been confirmed.", "Check the pin, then confirm the location."),
    "duplicate_location": (
        "Another store has exactly the same pin.",
        "Check both pins; one of them is probably wrong.",
    ),
}


def duplicate_location_ids(stores):
    groups = defaultdict(list)
    for store in stores:
        a = store.address
        if a.latitude is not None and a.longitude is not None:
            groups[(round(float(a.latitude), 5), round(float(a.longitude), 5))].append(store.pk)
    return {pk for ids in groups.values() if len(ids) > 1 for pk in ids}


def store_location_report(store, duplicates=frozenset()):
    codes = store_location_issues(store)
    if store.pk in duplicates:
        codes.append("duplicate_location")
    a = store.address
    return {
        "id": store.pk,
        "name": store.name,
        "store_code": store.store_code,
        "status": store.status,
        "is_active": store.is_active,
        "latitude": str(a.latitude) if a.latitude is not None else None,
        "longitude": str(a.longitude) if a.longitude is not None else None,
        "line1": a.line1,
        "line2": a.line2,
        "landmark": a.landmark,
        "city": a.city,
        "district": a.district,
        "state": a.state,
        "postal_code": a.postal_code,
        "google_place_id": a.google_place_id,
        "delivery_radius_km": str(store.delivery_radius_km),
        "location_confirmed_at": store.location_confirmed_at.isoformat() if store.location_confirmed_at else None,
        "can_take_delivery_orders": not [c for c in codes if c != "duplicate_location"],
        "issues": [
            {"code": c, "message": ISSUE_TEXT[c][0], "action": ISSUE_TEXT[c][1]} for c in codes
        ],
    }


@transaction.atomic
def update_store_location(store, data, *, actor, allow_radius=False):
    """Apply a pin and address change. Moving the pin clears confirmation unless re-confirmed."""
    address = store.address
    moved = (
        address.latitude is None
        or address.longitude is None
        or round(float(address.latitude), 6) != round(float(data["latitude"]), 6)
        or round(float(address.longitude), 6) != round(float(data["longitude"]), 6)
    )
    for field in ("line1", "line2", "landmark", "city", "district", "state", "postal_code"):
        setattr(address, field, data.get(field, getattr(address, field)))
    address.latitude = data["latitude"]
    address.longitude = data["longitude"]
    address.google_place_id = data.get("google_place_id", "")
    address.location_source = data.get("location_source", address.location_source)
    address.full_clean()
    address.save()

    if data.get("confirm"):
        if coordinate_issues(address.latitude, address.longitude):
            from .errors import InvalidCoordinates

            raise InvalidCoordinates("cannot confirm a suspicious pin")
        store.location_confirmed_at = timezone.now()
        store.location_confirmed_by = actor
        address.location_confirmed_at = store.location_confirmed_at
        address.save(update_fields=["location_confirmed_at", "updated_at"])
    elif moved:
        store.location_confirmed_at = None
        store.location_confirmed_by = None
        address.location_confirmed_at = None
        address.save(update_fields=["location_confirmed_at", "updated_at"])
    if allow_radius and data.get("delivery_radius_km") is not None:
        store.delivery_radius_km = data["delivery_radius_km"]
    store.save()
    logger.info("store %s location updated by user %s (moved=%s)", store.pk, getattr(actor, "pk", None), moved)
    return store
