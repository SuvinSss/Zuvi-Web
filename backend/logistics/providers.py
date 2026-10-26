"""Geocoding and routing providers behind one small interface.

Configured with environment-backed settings (no keys in the frontend):

    LOCATION_GEOCODER = "none" | "nominatim" | "google"
    LOCATION_GEOCODER_URL = "https://nominatim.example.org"   # your own or a licensed instance
    LOCATION_GEOCODER_USER_AGENT = "Zuuvi/1.0 (ops@zuuvi.in)"  # required by Nominatim's usage policy
    LOCATION_ROUTER = "none" | "osrm" | "google"
    LOCATION_ROUTER_URL = "https://osrm.example.org"
    LOCATION_PROVIDER_TIMEOUT = 5
    GOOGLE_MAPS_SERVER_KEY = "..."   # server-only key: Places API (New), Geocoding API, Routes API

Google: search = Places API (New) Autocomplete (suggestions without coordinates, billed per
session), details = Place Details (New) with the same session token, reverse = Geocoding API,
road distance = Routes API computeRoutes (two-wheeler where available). Google content is not
cached beyond the request (only place ids may be stored), per the Maps Platform terms.

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
    secondary: str = ""

    def as_dict(self):
        data = self.__dict__.copy()
        # Suggestions from Google have no coordinates yet: clients fetch /geo/place/ for them.
        data["needs_details"] = not (self.latitude and self.longitude)
        return data


def _from_dict(data):
    fields = Place.__dataclass_fields__
    return Place(**{k: v for k, v in data.items() if k in fields})


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


def _http_post_json(url, body, headers, *, timeout=None):
    req = Request(url, data=json.dumps(body).encode(), method="POST",
                  headers={"Content-Type": "application/json", "Accept": "application/json", **headers})
    return _open(req, timeout)


def _http_get_json(url, params, headers, *, timeout=None):
    full = f"{url}?{urlencode(params)}" if params else url
    return _open(Request(full, headers={"Accept": "application/json", **headers}), timeout)


def _open(req, timeout):
    try:
        with urlopen(req, timeout=timeout or float(_setting("LOCATION_PROVIDER_TIMEOUT", 5))) as resp:  # noqa: S310 (fixed Google hosts)
            return json.loads(resp.read(2_000_000).decode("utf-8"))
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        # Never log the URL: Geocoding API keys travel in the query string.
        raise ProviderUnavailable(type(exc).__name__ + ": " + str(getattr(exc, "reason", "") or getattr(exc, "code", "") or "request failed")) from exc


def _key(*parts):
    return "loc:" + hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()


class Geocoder:
    name = "none"
    attribution = ""

    def search(self, query: str, limit: int = 6, *, session: str = "", near=None) -> list[Place]:
        raise ProviderUnavailable("Address search is not configured.")

    def details(self, place_id: str, *, session: str = "") -> Place:
        raise ProviderUnavailable("Place details are not available.")

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

    def search(self, query, limit=6, *, session="", near=None):
        key = _key("search", self.base, query.lower(), limit)
        hit = cache.get(key)
        if hit is not None:
            return [_from_dict(p) for p in hit]
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
            return _from_dict(hit)
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


# ------------------------------------------------------------------ Google Maps Platform

PLACES_URL = "https://places.googleapis.com/v1"
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"


def _components(items, *, long_key, short_key, types_key="types"):
    """Map Google address components to our fields. Works for Places (New) and Geocoding shapes."""
    out = {}
    for c in items or []:
        if not isinstance(c, dict):
            continue
        for t in c.get(types_key) or []:
            out.setdefault(t, (str(c.get(long_key) or ""), str(c.get(short_key) or "")))
    get = lambda *types: next((out[t][0] for t in types if t in out and out[t][0]), "")  # noqa: E731
    return {
        "line1": " ".join(x for x in (get("premise", "subpremise"), get("street_number"), get("route")) if x)[:255],
        "locality": get("sublocality_level_1", "sublocality", "neighborhood")[:120],
        "city": get("locality", "postal_town", "administrative_area_level_3")[:100],
        "district": get("administrative_area_level_2")[:100],
        "state": get("administrative_area_level_1")[:100],
        "postal_code": get("postal_code")[:20],
        "country": get("country")[:100] or "India",
    }


def _coord(value):
    try:
        out = str(Decimal(str(value)).quantize(Decimal("0.000001")))
    except (ArithmeticError, ValueError, TypeError):
        return None
    return out


class GoogleGeocoder(Geocoder):
    """Places API (New) for search and details, Geocoding API for reverse lookup."""

    name = "google"
    attribution = "Powered by Google"

    def __init__(self, key):
        self.key = key

    def _headers(self, mask=None):
        h = {"X-Goog-Api-Key": self.key}
        if mask:
            h["X-Goog-FieldMask"] = mask
        return h

    def search(self, query, limit=6, *, session="", near=None):
        body = {"input": query[:120], "includedRegionCodes": ["in"], "languageCode": "en"}
        if session:
            body["sessionToken"] = session[:64]
        if near and valid_coordinates(*near):
            body["locationBias"] = {"circle": {"center": {"latitude": float(near[0]), "longitude": float(near[1])}, "radius": 50000.0}}
        data = _http_post_json(f"{PLACES_URL}/places:autocomplete", body, self._headers())
        if not isinstance(data, dict):
            raise ProviderUnavailable("Unexpected autocomplete response.")
        if "error" in data:
            raise ProviderUnavailable(str(data["error"].get("status", "error")))
        places = []
        for s in data.get("suggestions") or []:
            p = (s or {}).get("placePrediction") if isinstance(s, dict) else None
            if not isinstance(p, dict) or not p.get("placeId"):
                continue
            fmt = p.get("structuredFormat") or {}
            places.append(Place(label=str((p.get("text") or {}).get("text", ""))[:255], latitude="", longitude="",
                                line1=str((fmt.get("mainText") or {}).get("text", ""))[:255],
                                secondary=str((fmt.get("secondaryText") or {}).get("text", ""))[:255],
                                place_id=str(p["placeId"])[:255]))
            if len(places) >= limit:
                break
        return places

    def details(self, place_id, *, session=""):
        if not place_id or len(place_id) > 255 or not all(ch.isalnum() or ch in "-_" for ch in place_id):
            raise ProviderUnavailable("Invalid place id.")
        params = {"languageCode": "en", "regionCode": "in"}
        if session:
            params["sessionToken"] = session[:64]
        data = _http_get_json(f"{PLACES_URL}/places/{place_id}", params, self._headers("id,formattedAddress,location,addressComponents"))
        if not isinstance(data, dict) or "error" in data:
            raise ProviderUnavailable("Place details failed.")
        loc = data.get("location") or {}
        lat, lon = _coord(loc.get("latitude")), _coord(loc.get("longitude"))
        if not lat or not lon or not valid_coordinates(lat, lon):
            raise ProviderUnavailable("Place has no valid location.")
        parts = _components(data.get("addressComponents"), long_key="longText", short_key="shortText")
        return Place(label=str(data.get("formattedAddress", ""))[:255], latitude=lat, longitude=lon, place_id=str(data.get("id") or place_id)[:255], **parts)

    def reverse(self, latitude, longitude):
        data = _http_get_json(GEOCODE_URL, {"latlng": f"{latitude},{longitude}", "key": self.key, "language": "en", "region": "in"}, {})
        if not isinstance(data, dict):
            raise ProviderUnavailable("Unexpected geocoding response.")
        if data.get("status") != "OK" or not data.get("results"):
            raise ProviderUnavailable(f"Geocoding: {data.get('status', 'no result')}")
        best = data["results"][0]
        loc = ((best.get("geometry") or {}).get("location")) or {}
        lat, lon = _coord(loc.get("lat")), _coord(loc.get("lng"))
        if not lat or not lon:
            raise ProviderUnavailable("No location in result.")
        parts = _components(best.get("address_components"), long_key="long_name", short_key="short_name")
        # Keep the customer's own pin, not Google's snapped point.
        return Place(label=str(best.get("formatted_address", ""))[:255], latitude=_coord(latitude), longitude=_coord(longitude),
                     place_id=str(best.get("place_id", ""))[:255], **parts)


class GoogleRouter(Router):
    """Routes API computeRoutes. Two-wheeler routing (available in India) matches how Zuuvi delivers."""

    name = "google"

    def __init__(self, key, travel_mode="TWO_WHEELER"):
        self.key, self.travel_mode = key, travel_mode

    def road_km(self, origin, destination):
        def point(p):
            return {"location": {"latLng": {"latitude": float(p[0]), "longitude": float(p[1])}}}
        body = {"origin": point(origin), "destination": point(destination), "travelMode": self.travel_mode,
                "routingPreference": "TRAFFIC_UNAWARE" if self.travel_mode in ("DRIVE", "TWO_WHEELER") else None, "units": "METRIC"}
        body = {k: v for k, v in body.items() if v is not None}
        data = _http_post_json(ROUTES_URL, body, {"X-Goog-Api-Key": self.key, "X-Goog-FieldMask": "routes.distanceMeters,routes.duration"})
        try:
            metres = Decimal(str(data["routes"][0]["distanceMeters"]))
        except (KeyError, IndexError, TypeError, ArithmeticError) as exc:
            raise ProviderUnavailable("No road route found.") from exc
        if metres < 0 or metres > 1_000_000:
            raise ProviderUnavailable("Implausible route distance.")
        return (metres / 1000).quantize(Decimal("0.001"))


def get_geocoder() -> Geocoder:
    choice = _setting("LOCATION_GEOCODER", "none")
    if choice == "google" and _setting("GOOGLE_MAPS_SERVER_KEY", ""):
        return GoogleGeocoder(_setting("GOOGLE_MAPS_SERVER_KEY", ""))
    if choice == "nominatim" and _setting("LOCATION_GEOCODER_URL", ""):
        return NominatimGeocoder(_setting("LOCATION_GEOCODER_URL", ""))
    return Geocoder()


def get_router() -> Router:
    choice = _setting("LOCATION_ROUTER", "none")
    if choice == "google" and _setting("GOOGLE_MAPS_SERVER_KEY", ""):
        return GoogleRouter(_setting("GOOGLE_MAPS_SERVER_KEY", ""), _setting("GOOGLE_ROUTES_TRAVEL_MODE", "TWO_WHEELER"))
    if choice == "osrm" and _setting("LOCATION_ROUTER_URL", ""):
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
