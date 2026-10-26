"""Admin diagnostics for the Google Maps integration.

``maps_status`` reports what is configured (never the keys) and the last recorded check of each
Google service. ``run_health_checks`` makes one small live request per service, so it costs a
little quota; it is only reachable from an admin endpoint and is throttled there.
"""
from __future__ import annotations

import time
from decimal import Decimal

from django.conf import settings

from .models import MapsHealthCheck
from .providers import ProviderUnavailable, get_geocoder, get_router

# Two fixed points in Kochi, Kerala. They are only used to prove the APIs respond.
CHECK_POINT_A = (Decimal("9.931233"), Decimal("76.267304"))
CHECK_POINT_B = (Decimal("9.973000"), Decimal("76.285000"))

PUBLIC_MESSAGES = {
    ProviderUnavailable.NOT_CONFIGURED: "Not configured. Set the server key and switch the provider to google.",
    ProviderUnavailable.KEY_REJECTED: "Google rejected the key. Check the key, its API restrictions and that this API is enabled.",
    ProviderUnavailable.QUOTA_EXCEEDED: "Google quota or rate limit reached. Check quotas and billing.",
    ProviderUnavailable.TIMEOUT: "Google did not answer in time.",
    ProviderUnavailable.NETWORK: "Could not reach Google from the server.",
    ProviderUnavailable.BAD_RESPONSE: "Google returned something unexpected.",
    ProviderUnavailable.NO_RESULT: "Google found no result for the test request.",
}


def _record(service, ok, code="", message="", latency_ms=None, user=None):
    return MapsHealthCheck.objects.create(
        service=service, ok=ok, error_code=code[:24], message=message[:200], latency_ms=latency_ms,
        checked_by=user if getattr(user, "pk", None) else None,
    )


def _entry(row):
    return None if row is None else {
        "ok": row.ok, "error_code": row.error_code, "message": row.message, "latency_ms": row.latency_ms,
        "checked_at": row.checked_at.isoformat(),
    }


def maps_status() -> dict:
    geocoder, router = get_geocoder(), get_router()
    last = {}
    for service in MapsHealthCheck.Service.values:
        latest = MapsHealthCheck.objects.filter(service=service).first()
        last_ok = MapsHealthCheck.objects.filter(service=service, ok=True).first()
        last[service] = {"latest": _entry(latest), "last_success_at": last_ok.checked_at.isoformat() if last_ok else None}
    return {
        # "present" only means a value is set; the checks below show whether Google accepts it.
        "configuration": {
            "server_key_present": bool(getattr(settings, "GOOGLE_MAPS_SERVER_KEY", "")),
            "browser_key_present": bool(getattr(settings, "GOOGLE_MAPS_BROWSER_KEY", "")),
            "map_id_present": bool(getattr(settings, "GOOGLE_MAPS_MAP_ID", "")),
            "geocoder": geocoder.name,
            "router": router.name,
            "travel_mode": getattr(settings, "GOOGLE_ROUTES_TRAVEL_MODE", "TWO_WHEELER"),
            "timeout_seconds": float(getattr(settings, "LOCATION_PROVIDER_TIMEOUT", 5)),
            "store_pin_confirmation_required": bool(getattr(settings, "STORE_PIN_CONFIRMATION_REQUIRED", False)),
        },
        "checks": last,
    }


def _timed(call):
    started = time.monotonic()
    call()
    return int((time.monotonic() - started) * 1000)


def run_health_checks(user=None) -> dict:
    geocoder, router = get_geocoder(), get_router()
    plan = (
        (MapsHealthCheck.Service.PLACES, geocoder, lambda: geocoder.search("Kochi", 1)),
        (MapsHealthCheck.Service.GEOCODING, geocoder, lambda: geocoder.reverse(*CHECK_POINT_A)),
        (MapsHealthCheck.Service.ROUTES, router, lambda: router.road_km(CHECK_POINT_A, CHECK_POINT_B)),
    )
    results = {}
    for service, provider, call in plan:
        if provider.name != "google":
            row = _record(service, False, ProviderUnavailable.NOT_CONFIGURED,
                          PUBLIC_MESSAGES[ProviderUnavailable.NOT_CONFIGURED], user=user)
        else:
            try:
                row = _record(service, True, "", "Responded normally.", _timed(call), user)
            except ProviderUnavailable as exc:
                row = _record(service, False, exc.code, PUBLIC_MESSAGES.get(exc.code, PUBLIC_MESSAGES[ProviderUnavailable.BAD_RESPONSE]), user=user)
        results[service] = _entry(row)
    return results
