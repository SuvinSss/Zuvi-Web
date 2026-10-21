"""Small geographic helpers. Provider-neutral: no external routing/maps API is used."""
from decimal import Decimal
from math import asin, cos, radians, sin, sqrt

EARTH_RADIUS_M = 6_371_000


def valid_coordinates(latitude, longitude) -> bool:
    try:
        return -90 <= float(latitude) <= 90 and -180 <= float(longitude) <= 180
    except (TypeError, ValueError):
        return False


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    """Great-circle distance in metres between two points."""
    lat1, lon1, lat2, lon2 = (float(Decimal(str(v))) for v in (lat1, lon1, lat2, lon2))
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_M * asin(sqrt(a))
