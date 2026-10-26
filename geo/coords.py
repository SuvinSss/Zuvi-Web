"""Coordinate validation and straight-line helpers.

Straight-line distance is used only to pre-filter candidates. It is never
presented as a road distance and never used as a price input.
"""

import math
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from .errors import InvalidCoordinates

# Rough bounding box of India, used only to flag *suspicious* store pins.
INDIA_LAT_RANGE = (6.0, 37.5)
INDIA_LNG_RANGE = (68.0, 97.5)
EARTH_RADIUS_KM = 6371.0088


@dataclass(frozen=True)
class Coordinate:
    latitude: Decimal
    longitude: Decimal

    def as_floats(self):
        return float(self.latitude), float(self.longitude)

    def key(self, places=5):
        return f"{round(float(self.latitude), places)},{round(float(self.longitude), places)}"


def parse_coordinate(latitude, longitude):
    """Return a validated Coordinate or raise InvalidCoordinates."""
    try:
        if isinstance(latitude, bool) or isinstance(longitude, bool):
            raise InvalidOperation
        lat = Decimal(str(latitude).strip())
        lng = Decimal(str(longitude).strip())
    except (InvalidOperation, TypeError, ValueError, AttributeError):
        raise InvalidCoordinates("coordinates are not numeric") from None
    if not lat.is_finite() or not lng.is_finite():
        raise InvalidCoordinates("coordinates are not finite")
    if not Decimal("-90") <= lat <= Decimal("90") or not Decimal("-180") <= lng <= Decimal("180"):
        raise InvalidCoordinates("coordinates out of range")
    quant = Decimal("0.000001")
    return Coordinate(lat.quantize(quant), lng.quantize(quant))


def coordinate_issues(latitude, longitude):
    """Return a list of human-readable problems with a stored coordinate pair."""
    if latitude is None or longitude is None:
        return ["missing"]
    try:
        coord = parse_coordinate(latitude, longitude)
    except InvalidCoordinates:
        return ["invalid"]
    issues = []
    lat, lng = coord.as_floats()
    if lat == 0.0 and lng == 0.0:
        issues.append("null_island")
    elif not (
        INDIA_LAT_RANGE[0] <= lat <= INDIA_LAT_RANGE[1]
        and INDIA_LNG_RANGE[0] <= lng <= INDIA_LNG_RANGE[1]
    ):
        issues.append("outside_india")
    return issues


def haversine_km(a: Coordinate, b: Coordinate) -> float:
    lat1, lng1 = map(math.radians, a.as_floats())
    lat2, lng2 = map(math.radians, b.as_floats())
    dlat, dlng = lat2 - lat1, lng2 - lng1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(h)))
