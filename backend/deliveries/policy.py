"""Tunable delivery rules, read from settings so they are never hard-coded."""
from datetime import timedelta

from django.conf import settings


def _get(name, default):
    return getattr(settings, name, default)


def offer_ttl() -> timedelta:
    return timedelta(seconds=_get("DELIVERY_OFFER_TTL_SECONDS", 120))


def stale_after() -> timedelta:
    return timedelta(seconds=_get("DELIVERY_STALE_SECONDS", 90))


def min_ping_interval() -> timedelta:
    return timedelta(seconds=_get("DELIVERY_MIN_PING_INTERVAL_SECONDS", 2))


def max_ping_accuracy_m() -> float:
    return float(_get("DELIVERY_MAX_PING_ACCURACY_M", 500))


def max_rejections() -> int:
    """Automatic offers stop after this many rejections/timeouts; an admin must step in."""
    return int(_get("DELIVERY_MAX_REJECTIONS", 5))


def max_attempts() -> int:
    return int(_get("DELIVERY_MAX_ATTEMPTS", 3))


def max_active_per_partner() -> int:
    return int(_get("DELIVERY_MAX_ACTIVE_PER_PARTNER", 1))


def max_assignment_radius_m():
    value = _get("DELIVERY_MAX_ASSIGNMENT_RADIUS_M", None)
    return float(value) if value else None


def location_tolerance_m() -> float:
    return float(_get("DELIVERY_LOCATION_TOLERANCE_M", 300))


def enforce_tolerance() -> bool:
    return bool(_get("DELIVERY_ENFORCE_LOCATION_TOLERANCE", False))


def require_otp() -> bool:
    return bool(_get("DELIVERY_REQUIRE_OTP", False))


def max_otp_failures() -> int:
    return int(_get("DELIVERY_MAX_OTP_FAILURES", 5))


def min_photos() -> int:
    return int(_get("DELIVERY_MIN_EVIDENCE_PHOTOS", 1))


def max_photos() -> int:
    return int(_get("DELIVERY_MAX_EVIDENCE_PHOTOS", 5))
