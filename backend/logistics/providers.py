"""Geocoding and routing providers behind one small interface.

Configured with environment-backed settings (no keys in the frontend):

    LOCATION_GEOCODER = "none" | "nominatim"
    LOCATION_GEOCODER_URL = "https://nominatim.example.org"   # your own or a licensed instance
    LOCATION_GEOCODER_USER_AGENT = "Zuuvi/1.0 (ops@zuuvi.in)"  # required by Nominatim's usage policy
    LOCATION_ROUTER = "none" | "osrm"
    LOCATION_ROUTER_URL = "https://osrm.example.org"
    LOCATION_PROVIDER_TIMEOUT = 5

"none" is the default: search/reverse report "unavailable" and distances fall back to a
clearly labelled estimate. Public demo servers are not production services; point these at
an instance you are allowed to use. Responses are validated and cached; failures never raise
to the caller as 500s.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from decimal import Decimal
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.cache import cache

from core.geo import haversine_m, valid_coordinates

logger = logging.getLogger(__name__)
CACHE_SECONDS = 24 * 3600


class ProviderUnavailable(Exception):
    """The provider is not configured, timed out or returned something unusable."""


@dataclass
class Place:
    label: str
    latitude: str
    longitude: str
    line1: str = ""
    locality: str = ""
    city: str = ""
    district: str = ""
    state: str = ""
    postal_code: str = ""
    country: str = "India"
    place_id: str = ""

    def as_dict(self):
        return self.__dict__.copy()


def _setting(name, default):
    return getattr(settings, name, default)


def _http_json(url, params, *, timeout=None):
    full = f"{url}?{urlencode(params)}" if params else url
    req = Request(full, headers={"User-Agent": _setting("LOCATION_GEOCODER_USER_AGENT", "Zuuvi/1.0"), "Accept": "application/json"})
    try:
        with urlopen(req, timeout=timeout or float(_setting("LOCATION_PROVIDER_TIMEOUT", 5))) as resp:  # noqa: S310 (configured URL)
            if resp.status != 200:
                raise ProviderUnavailable(f"HTTP {resp.status}")
            return json.loads(resp.read(2_000_000).decode("utf-8"))
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        raise ProviderUnavailable(str(exc)) from exc


def _key(*parts):
    return "loc:" + hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()


class Geocoder:
    name = "none"

    def search(self, query: str, limit: int = 6) -> list[Place]:
        raise ProviderUnavailable("Address search is not configured.")

    def reverse(self, latitude, longitude) -> Place:
        raise ProviderUnavailable("Address lookup is not configured.")


class NominatimGeocoder(Geocoder):
    """OpenStreetMap Nominatim-compatible API, limited to India."""

    name = "nominatim"

    def __init__(self, base_url):
        self.base = base_url.rstrip("/")

    @staticmethod
    def _place(item) -> Place | None:
        try:
            lat, lon = str(Decimal(str(item["lat"])).quantize(Decimal("0.000001"))), str(Decimal(str(item["lon"])).quantize(Decimal("0.000001")))
        except (KeyError, ArithmeticError, ValueError, TypeError):
            return None
        if not valid_coordinates(lat, lon):
            return None
        a = item.get("address") or {}
        line1 = " ".join(x for x in (a.get("house_number"), a.get("house_name"), a.get("road")) if x)
        return Place(
            label=str(item.get("display_name", ""))[:255], latitude=lat, longitude=lon, line1=line1[:255],
            locality=(a.get("suburb") or a.get("neighbourhood") or a.get("village") or a.get("hamlet") or "")[:120],
            city=(a.get("city") or a.get("town") or a.get("village") or a.get("municipality") or "")[:100],
            district=(a.get("state_district") or a.get("county") or "")[:100], state=(a.get("state") or "")[:100],
            postal_code=(a.get("postcode") or "")[:20], country=(a.get("country") or "India")[:100],
            place_id=str(item.get("osm_type", ""))[:1] + str(item.get("osm_id", "")),
        )

    def search(self, query, limit=6):
        key = _key("search", self.base, query.lower(), limit)
        hit = cache.get(key)
        if hit is not None:
            return [Place(**p) for p in hit]
        data = _http_json(f"{self.base}/search", {"q": query, "format": "jsonv2", "addressdetails": 1, "countrycodes": "in", "limit": limit})
        if not isinstance(data, list):
            raise ProviderUnavailable("Unexpected search response.")
        places = [p for p in (self._place(i) for i in data[:limit] if isinstance(i, dict)) if p]
        cache.set(key, [p.as_dict() for p in places], CACHE_SECONDS)
        return places

    def reverse(self, latitude, longitude):
        key = _key("reverse", self.base, round(float(latitude), 5), round(float(longitude), 5))
        hit = cache.get(key)
        if hit is not None:
            return Place(**hit)
        data = _http_json(f"{self.base}/reverse", {"lat": latitude, "lon": longitude, "format": "jsonv2", "addressdetails": 1})
        place = self._place(data) if isinstance(data, dict) else None
        if place is None:
            raise ProviderUnavailable("No address found for this point.")
        cache.set(key, place.as_dict(), CACHE_SECONDS)
        return place


class Router:
    name = "none"

    def road_km(self, origin, destination) -> Decimal:
        raise ProviderUnavailable("Road routing is not configured.")


class OSRMRouter(Router):
    name = "osrm"

    def __init__(self, base_url):
        self.base = base_url.rstrip("/")

    def road_km(self, origin, destination):
        (lat1, lon1), (lat2, lon2) = origin, destination
        key = _key("route", self.base, round(float(lat1), 5), round(float(lon1), 5), round(float(lat2), 5), round(float(lon2), 5))
        hit = cache.get(key)
        if hit is not None:
            return Decimal(hit)
        data = _http_json(f"{self.base}/route/v1/driving/{lon1},{lat1};{lon2},{lat2}", {"overview": "false"})
        try:
            if data.get("code") != "Ok":
                raise ProviderUnavailable(f"Routing failed: {data.get('code')}")
            metres = Decimal(str(data["routes"][0]["distance"]))
        except (KeyError, IndexError, TypeError, ArithmeticError, AttributeError) as exc:
            raise ProviderUnavailable("Unexpected routing response.") from exc
        if metres < 0 or metres > 1_000_000:
            raise ProviderUnavailable("Implausible route distance.")
        km = (metres / 1000).quantize(Decimal("0.001"))
        cache.set(key, str(km), CACHE_SECONDS)
        return km


def get_geocoder() -> Geocoder:
    if _setting("LOCATION_GEOCODER", "none") == "nominatim" and _setting("LOCATION_GEOCODER_URL", ""):
        return NominatimGeocoder(_setting("LOCATION_GEOCODER_URL", ""))
    return Geocoder()


def get_router() -> Router:
    if _setting("LOCATION_ROUTER", "none") == "osrm" and _setting("LOCATION_ROUTER_URL", ""):
        return OSRMRouter(_setting("LOCATION_ROUTER_URL", ""))
    return Router()


def straight_line_km(origin, destination) -> Decimal:
    return (Decimal(str(haversine_m(origin[0], origin[1], destination[0], destination[1]))) / 1000).quantize(Decimal("0.001"))


def travel_distance(origin, destination, *, fallback_factor, allow_estimate=True):
    """(km, source, note). Road distance from the router, else an explicit estimate, else ProviderUnavailable."""
    try:
        return get_router().road_km(origin, destination), "road", ""
    except ProviderUnavailable as exc:
        if get_router().name != "none":
            logger.warning("Routing unavailable, using estimate: %s", exc)
        if not allow_estimate:
            raise
        straight = straight_line_km(origin, destination)
        km = (straight * Decimal(str(fallback_factor))).quantize(Decimal("0.001"))
        return km, "estimated", f"Road route unavailable; distance estimated as {straight} km straight-line × {fallback_factor}."
