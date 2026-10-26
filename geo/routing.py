"""Reusable road-routing service on top of the Google Routes API.

Returns a normalised ``RouteResult``. Results are tagged ``LIVE`` or ``CACHED``.
There is no straight-line fallback: when Google cannot give a route the caller
receives a ``MapsError`` and decides how to explain it. A straight-line number
is never labelled as a Google road route.
"""

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

from django.core.cache import cache

from . import google_client
from .config import get_maps_config
from .coords import Coordinate
from .errors import MapsError

logger = logging.getLogger("geo.routing")

PROVIDER = "google_routes_v2"
SOURCE_LIVE = "LIVE"
SOURCE_CACHED = "CACHED"


@dataclass(frozen=True)
class RouteResult:
    origin_ref: str
    destination_ref: str
    distance_meters: int
    duration_seconds: int
    travel_mode: str
    calculated_at: datetime
    source: str
    provider: str = PROVIDER
    status: str = "OK"

    @property
    def distance_km(self) -> Decimal:
        return (Decimal(self.distance_meters) / Decimal(1000)).quantize(Decimal("0.001"))

    def as_dict(self):
        return {
            "origin_ref": self.origin_ref,
            "destination_ref": self.destination_ref,
            "distance_meters": self.distance_meters,
            "distance_km": str(self.distance_km),
            "duration_seconds": self.duration_seconds,
            "travel_mode": self.travel_mode,
            "calculated_at": self.calculated_at.isoformat(),
            "source": self.source,
            "provider": self.provider,
            "status": self.status,
        }


@dataclass
class RouteFailure:
    origin_ref: str
    error: MapsError = field(repr=False)


def _cache_key(origin: Coordinate, destination: Coordinate, mode: str) -> str:
    raw = f"route:v1:{mode}:{origin.key()}:{destination.key()}"
    return "geo:" + hashlib.sha256(raw.encode()).hexdigest()


def _to_cache(result: RouteResult):
    return {
        "distance_meters": result.distance_meters,
        "duration_seconds": result.duration_seconds,
        "calculated_at": result.calculated_at.isoformat(),
        "travel_mode": result.travel_mode,
    }


def _from_cache(data, origin_ref, destination_ref):
    return RouteResult(
        origin_ref=origin_ref,
        destination_ref=destination_ref,
        distance_meters=data["distance_meters"],
        duration_seconds=data["duration_seconds"],
        travel_mode=data["travel_mode"],
        calculated_at=datetime.fromisoformat(data["calculated_at"]),
        source=SOURCE_CACHED,
    )


def _store(origin, destination, result, ttl):
    if ttl > 0:
        cache.set(_cache_key(origin, destination, result.travel_mode), _to_cache(result), ttl)


def get_route(origin: Coordinate, destination: Coordinate, *, origin_ref="", destination_ref="",
              use_cache=True) -> RouteResult:
    """Road distance and duration for one origin and destination."""
    cfg = get_maps_config()
    ttl = cfg.route_cache_ttl
    if use_cache and ttl > 0:
        hit = cache.get(_cache_key(origin, destination, cfg.travel_mode))
        if hit:
            return _from_cache(hit, origin_ref, destination_ref)
    raw = google_client.compute_route(origin, destination)
    result = RouteResult(
        origin_ref=origin_ref,
        destination_ref=destination_ref,
        distance_meters=raw.distance_meters,
        duration_seconds=raw.duration_seconds,
        travel_mode=cfg.travel_mode,
        calculated_at=datetime.now(timezone.utc),
        source=SOURCE_LIVE,
    )
    _store(origin, destination, result, ttl)
    return result


def get_routes_from_origins(origins, destination: Coordinate, *, destination_ref="", use_cache=True):
    """Routes from several stores to one customer.

    ``origins`` is a list of ``(origin_ref, Coordinate)``. Cached pairs are served
    from cache; if two or more remain they are fetched with one matrix call,
    otherwise with a single route call. Returns ``{origin_ref: RouteResult | RouteFailure}``.
    Per-element failures never poison the other origins.
    """
    cfg = get_maps_config()
    ttl = cfg.route_cache_ttl
    out = {}
    pending = []
    for ref, coord in origins:
        hit = cache.get(_cache_key(coord, destination, cfg.travel_mode)) if use_cache and ttl > 0 else None
        if hit:
            out[ref] = _from_cache(hit, ref, destination_ref)
        else:
            pending.append((ref, coord))

    if len(pending) == 1:
        ref, coord = pending[0]
        try:
            out[ref] = get_route(coord, destination, origin_ref=ref, destination_ref=destination_ref, use_cache=False)
        except MapsError as exc:
            out[ref] = RouteFailure(ref, exc)
    elif pending:
        try:
            elements = google_client.compute_route_matrix([c for _, c in pending], [destination])
        except MapsError as exc:
            for ref, _ in pending:
                out[ref] = RouteFailure(ref, exc)
            return out
        now = datetime.now(timezone.utc)
        by_origin = {e.origin_index: e for e in elements}
        for index, (ref, coord) in enumerate(pending):
            element = by_origin.get(index)
            if element is None or not element.ok:
                from .errors import NoRouteFound

                out[ref] = RouteFailure(ref, NoRouteFound(element.error if element else "missing"))
                continue
            result = RouteResult(
                origin_ref=ref,
                destination_ref=destination_ref,
                distance_meters=element.distance_meters,
                duration_seconds=element.duration_seconds,
                travel_mode=cfg.travel_mode,
                calculated_at=now,
                source=SOURCE_LIVE,
            )
            _store(coord, destination, result, ttl)
            out[ref] = result
    return out
