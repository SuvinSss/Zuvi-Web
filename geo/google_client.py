"""Thin, safe client for the Google Maps Platform web services Zuuvi uses.

Services (all called with the *server* key, never from the browser):
  * Geocoding API            GET  https://maps.googleapis.com/maps/api/geocode/json
  * Routes API computeRoutes POST https://routes.googleapis.com/directions/v2:computeRoutes
  * Routes API matrix        POST https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix
  * Address Validation API   POST https://addressvalidation.googleapis.com/v1:validateAddress

Rules enforced here:
  * The key is sent in a header where the API supports it (Routes, Address
    Validation) and as a query parameter only where required (Geocoding).
  * Exceptions from ``requests`` are never re-raised because their messages can
    contain the request URL (and therefore the key).
  * Every request asks only for the response fields the application needs.
  * Nothing here returns raw Google payloads to callers.
"""

import logging
import re
from dataclasses import dataclass
from decimal import Decimal

import requests

from .config import get_maps_config
from .coords import Coordinate
from .errors import (
    AmbiguousRoute,
    GeocodeNotFound,
    MapsBadResponse,
    MapsKeyRejected,
    MapsNetworkError,
    MapsNotConfigured,
    MapsQuotaExceeded,
    MapsTimeout,
    NoRouteFound,
)

logger = logging.getLogger("geo.google")

GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
MATRIX_URL = "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"
ADDRESS_VALIDATION_URL = "https://addressvalidation.googleapis.com/v1:validateAddress"

ROUTE_FIELD_MASK = "routes.distanceMeters,routes.duration"
MATRIX_FIELD_MASK = "originIndex,destinationIndex,duration,distanceMeters,status,condition"
MAX_MATRIX_ELEMENTS = 25

_DURATION_RE = re.compile(r"^(\d+)(?:\.\d+)?s$")


class GoogleTransport:
    """Network boundary. Tests replace this; normal tests must never reach Google."""

    def request(self, method, url, *, headers=None, params=None, json=None, timeout=5.0):
        try:
            response = requests.request(
                method, url, headers=headers, params=params, json=json, timeout=timeout
            )
        except requests.Timeout:
            raise MapsTimeout("request timed out") from None
        except requests.RequestException:
            raise MapsNetworkError("network failure") from None
        try:
            body = response.json()
        except ValueError:
            body = None
        return response.status_code, body


_transport = GoogleTransport()


def set_transport(transport):
    """Replace the network boundary (used by tests). Returns the previous one."""
    global _transport
    previous, _transport = _transport, transport
    return previous


def _require_server_key():
    key = get_maps_config().server_key
    if not key:
        raise MapsNotConfigured("GOOGLE_MAPS_SERVER_API_KEY is empty")
    return key


def _scrub(text, key=""):
    text = str(text or "")
    if key:
        text = text.replace(key, "[redacted]")
    return text[:300]


def _classify_http_error(status_code, body, key):
    """Map a Google error response to a domain error without leaking secrets."""
    error = (body or {}).get("error") if isinstance(body, dict) else None
    google_status = (error or {}).get("status", "")
    message = _scrub((error or {}).get("message", ""), key)
    logger.warning("Google API error http=%s status=%s message=%s", status_code, google_status, message)
    if status_code in (401, 403) or google_status in {"PERMISSION_DENIED", "UNAUTHENTICATED"}:
        raise MapsKeyRejected(f"{google_status or status_code}: {message}")
    if status_code == 429 or google_status == "RESOURCE_EXHAUSTED":
        raise MapsQuotaExceeded(f"{google_status or status_code}")
    if status_code == 404 or google_status == "NOT_FOUND":
        raise NoRouteFound(message)
    if status_code == 400 or google_status == "INVALID_ARGUMENT":
        raise MapsBadResponse(f"INVALID_ARGUMENT: {message}")
    raise MapsBadResponse(f"http {status_code}")


def parse_duration_seconds(value):
    if value is None:
        return None
    match = _DURATION_RE.match(str(value))
    if not match:
        raise MapsBadResponse("unparseable duration")
    return int(match.group(1))


# ---------------------------------------------------------------- Geocoding


@dataclass(frozen=True)
class GeocodeResult:
    formatted_address: str
    place_id: str
    latitude: Decimal
    longitude: Decimal
    location_type: str
    partial_match: bool
    components: dict

    @property
    def is_precise(self):
        return self.location_type in {"ROOFTOP", "RANGE_INTERPOLATED"} and not self.partial_match


def _component(components, *types):
    for part in components:
        if any(t in part.get("types", []) for t in types):
            return part.get("long_name", "")
    return ""


def _normalise_geocode(result):
    geometry = result.get("geometry", {})
    loc = geometry.get("location", {})
    parts = result.get("address_components", [])
    street = " ".join(
        p for p in (_component(parts, "street_number"), _component(parts, "route")) if p
    )
    return GeocodeResult(
        formatted_address=result.get("formatted_address", ""),
        place_id=result.get("place_id", ""),
        latitude=Decimal(str(loc.get("lat"))).quantize(Decimal("0.000001")),
        longitude=Decimal(str(loc.get("lng"))).quantize(Decimal("0.000001")),
        location_type=geometry.get("location_type", ""),
        partial_match=bool(result.get("partial_match", False)),
        components={
            "line1": street or _component(parts, "premise", "sublocality_level_1", "sublocality"),
            "locality": _component(parts, "locality", "administrative_area_level_3"),
            "district": _component(parts, "administrative_area_level_2"),
            "state": _component(parts, "administrative_area_level_1"),
            "postal_code": _component(parts, "postal_code"),
            "country": _component(parts, "country"),
        },
    )


def _geocode_call(params):
    key = _require_server_key()
    cfg = get_maps_config()
    query = {**params, "key": key, "language": cfg.language, "region": cfg.region.lower()}
    status_code, body = _transport.request("GET", GEOCODE_URL, params=query, timeout=cfg.timeout)
    if not isinstance(body, dict):
        raise MapsBadResponse("geocode: non-JSON response")
    status = body.get("status")
    if status == "OK":
        results = body.get("results") or []
        if not results:
            raise GeocodeNotFound("OK with no results")
        return results
    if status == "ZERO_RESULTS":
        raise GeocodeNotFound("ZERO_RESULTS")
    if status in {"OVER_QUERY_LIMIT", "OVER_DAILY_LIMIT"}:
        raise MapsQuotaExceeded(status)
    if status == "REQUEST_DENIED":
        logger.warning("Geocoding REQUEST_DENIED: %s", _scrub(body.get("error_message"), key))
        raise MapsKeyRejected("REQUEST_DENIED")
    if status == "INVALID_REQUEST":
        raise MapsBadResponse("INVALID_REQUEST")
    raise MapsBadResponse(f"geocode status {status}")


def reverse_geocode(point: Coordinate) -> GeocodeResult:
    results = _geocode_call({"latlng": f"{point.latitude},{point.longitude}"})
    return _normalise_geocode(results[0])


def geocode_address(address: str) -> GeocodeResult:
    address = (address or "").strip()
    if not address or len(address) > 300:
        raise GeocodeNotFound("empty or oversize address")
    results = _geocode_call({"address": address, "components": f"country:{get_maps_config().region}"})
    return _normalise_geocode(results[0])


# ------------------------------------------------------------------- Routes


def _waypoint(point: Coordinate):
    return {
        "waypoint": {
            "location": {
                "latLng": {"latitude": float(point.latitude), "longitude": float(point.longitude)}
            }
        }
    }


def _routes_headers(key, field_mask):
    return {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": key,
        "X-Goog-FieldMask": field_mask,
    }


def _routing_body(cfg):
    body = {
        "travelMode": cfg.travel_mode,
        "units": "METRIC",
        "regionCode": cfg.region,
        "languageCode": cfg.language,
    }
    # Operational estimates must not move with live traffic between a quote and
    # its refresh, and TWO_WHEELER does not take a traffic-aware preference.
    body["routingPreference"] = "TRAFFIC_UNAWARE"
    return body


@dataclass(frozen=True)
class RawRoute:
    distance_meters: int
    duration_seconds: int


def compute_route(origin: Coordinate, destination: Coordinate) -> RawRoute:
    key = _require_server_key()
    cfg = get_maps_config()
    body = {
        "origin": _waypoint(origin)["waypoint"],
        "destination": _waypoint(destination)["waypoint"],
        **_routing_body(cfg),
    }
    status_code, payload = _transport.request(
        "POST", ROUTES_URL, headers=_routes_headers(key, ROUTE_FIELD_MASK), json=body, timeout=cfg.timeout
    )
    if status_code != 200:
        _classify_http_error(status_code, payload, key)
    if not isinstance(payload, dict):
        raise MapsBadResponse("routes: non-JSON response")
    routes = payload.get("routes") or []
    if not routes:
        raise NoRouteFound("empty routes list")
    if len(routes) > 1:
        raise AmbiguousRoute("more than one route returned for a single-route request")
    route = routes[0]
    duration = parse_duration_seconds(route.get("duration"))
    if duration is None:
        raise AmbiguousRoute("route has no duration")
    # Protobuf JSON omits zero-valued fields; a present duration with no
    # distance is a genuine 0 m route (same position), not a missing value.
    distance = route.get("distanceMeters", 0)
    if not isinstance(distance, int) or distance < 0:
        raise MapsBadResponse("route distance not an integer")
    return RawRoute(distance_meters=distance, duration_seconds=duration)


@dataclass(frozen=True)
class MatrixElement:
    origin_index: int
    destination_index: int
    ok: bool
    condition: str
    distance_meters: int | None
    duration_seconds: int | None
    error: str = ""


def compute_route_matrix(origins, destinations):
    """Return a MatrixElement for every (origin, destination) pair.

    Missing elements are reported as failed instead of being assumed valid.
    """
    if not origins or not destinations:
        return []
    if len(origins) * len(destinations) > MAX_MATRIX_ELEMENTS:
        raise MapsBadResponse("matrix request exceeds the configured element cap")
    key = _require_server_key()
    cfg = get_maps_config()
    body = {
        "origins": [_waypoint(p) for p in origins],
        "destinations": [_waypoint(p) for p in destinations],
        **_routing_body(cfg),
    }
    status_code, payload = _transport.request(
        "POST", MATRIX_URL, headers=_routes_headers(key, MATRIX_FIELD_MASK), json=body, timeout=cfg.timeout
    )
    if status_code != 200:
        _classify_http_error(status_code, payload, key)
    if not isinstance(payload, list):
        raise MapsBadResponse("matrix: expected a JSON array")

    found = {}
    for raw in payload:
        if not isinstance(raw, dict):
            continue
        oi, di = raw.get("originIndex", 0), raw.get("destinationIndex", 0)
        if not (isinstance(oi, int) and isinstance(di, int)) or oi >= len(origins) or di >= len(destinations):
            continue
        status = raw.get("status") or {}
        condition = raw.get("condition", "")
        if status.get("code") or condition != "ROUTE_EXISTS":
            found[(oi, di)] = MatrixElement(
                oi, di, False, condition or "UNKNOWN", None, None,
                error=_scrub(status.get("message") or condition or "no route"),
            )
            continue
        try:
            duration = parse_duration_seconds(raw.get("duration"))
        except MapsBadResponse:
            duration = None
        if duration is None:
            found[(oi, di)] = MatrixElement(oi, di, False, condition, None, None, error="missing duration")
            continue
        found[(oi, di)] = MatrixElement(oi, di, True, condition, int(raw.get("distanceMeters", 0)), duration)

    elements = []
    for oi in range(len(origins)):
        for di in range(len(destinations)):
            elements.append(
                found.get((oi, di))
                or MatrixElement(oi, di, False, "MISSING", None, None, error="element missing from response")
            )
    return elements


# --------------------------------------------------------- Address Validation


def validate_address(lines, region_code=None):
    """Optional Address Validation API call. Returns a small, safe verdict dict."""
    cfg = get_maps_config()
    if not cfg.address_validation_enabled:
        raise MapsNotConfigured("Address Validation is disabled")
    key = _require_server_key()
    body = {
        "address": {
            "regionCode": region_code or cfg.region,
            "addressLines": [str(line)[:200] for line in lines if line][:5],
        }
    }
    status_code, payload = _transport.request(
        "POST",
        ADDRESS_VALIDATION_URL,
        headers={"Content-Type": "application/json", "X-Goog-Api-Key": key},
        json=body,
        timeout=cfg.timeout,
    )
    if status_code != 200:
        _classify_http_error(status_code, payload, key)
    result = (payload or {}).get("result") or {}
    verdict = result.get("verdict") or {}
    return {
        "address_complete": bool(verdict.get("addressComplete", False)),
        "has_unconfirmed_components": bool(verdict.get("hasUnconfirmedComponents", False)),
        "has_inferred_components": bool(verdict.get("hasInferredComponents", False)),
        "validation_granularity": verdict.get("validationGranularity", ""),
    }
