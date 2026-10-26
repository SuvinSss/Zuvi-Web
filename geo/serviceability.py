"""Store eligibility and delivery serviceability.

Order of checks: store state -> store location data -> confirmation -> straight-line
radius (cheap pre-filter) -> Google road distance (final decision, done by quotes).
"""

from dataclasses import dataclass, field

from django.conf import settings

from .coords import Coordinate, coordinate_issues, haversine_km, parse_coordinate
from .errors import InvalidCoordinates

MESSAGES = {
    "STORE_INACTIVE": "This store is not taking orders right now.",
    "STORE_NOT_APPROVED": "This store is not taking orders right now.",
    "STORE_LOCATION_MISSING": "This store's location is not set up yet.",
    "STORE_LOCATION_UNCONFIRMED": "This store is not ready to deliver yet.",
    "OUTSIDE_RADIUS": "This address is outside this store's delivery area.",
    "OUTSIDE_ROAD_RANGE": "This address is too far by road for delivery from this store.",
    "NO_ROUTE": "We could not find a road route from this store to your address.",
    "ROUTE_UNAVAILABLE": "We could not check the delivery distance right now. Please try again.",
}


@dataclass
class StoreEligibility:
    store_id: int
    store_name: str
    eligible: bool
    reasons: list = field(default_factory=list)  # [{"code", "message"}]
    straight_line_km: float | None = None
    approximate: bool = True

    def add(self, code):
        self.eligible = False
        self.reasons.append({"code": code, "message": MESSAGES[code]})


def store_coordinate(store):
    address = store.address
    if coordinate_issues(address.latitude, address.longitude) in (["missing"], ["invalid"], ["null_island"]):
        return None
    try:
        return parse_coordinate(address.latitude, address.longitude)
    except InvalidCoordinates:
        return None


def store_location_issues(store):
    """Issue codes shown to administrators for a store pin."""
    address = store.address
    issues = list(coordinate_issues(address.latitude, address.longitude))
    if store.location_confirmed_at is None:
        issues.append("unconfirmed")
    return issues


def evaluate_store(store, destination: Coordinate, *, require_confirmation=None) -> StoreEligibility:
    from stores.models import StoreStatus

    if require_confirmation is None:
        require_confirmation = settings.DELIVERY_QUOTES_ENFORCED
    result = StoreEligibility(store_id=store.pk, store_name=store.name, eligible=True)

    if not store.is_active:
        result.add("STORE_INACTIVE")
    if store.status != StoreStatus.ACTIVE:
        result.add("STORE_NOT_APPROVED")
    origin = store_coordinate(store)
    if origin is None:
        result.add("STORE_LOCATION_MISSING")
        return result
    if require_confirmation and store.location_confirmed_at is None:
        result.add("STORE_LOCATION_UNCONFIRMED")

    distance = haversine_km(origin, destination)
    result.straight_line_km = round(distance, 2)
    if distance > float(store.delivery_radius_km):
        result.add("OUTSIDE_RADIUS")
    return result
