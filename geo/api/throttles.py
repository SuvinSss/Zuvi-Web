from rest_framework.throttling import AnonRateThrottle, UserRateThrottle


class GeocodeThrottle(UserRateThrottle):
    scope = "geo_geocode"


class RouteThrottle(UserRateThrottle):
    scope = "geo_route"


class QuoteThrottle(UserRateThrottle):
    scope = "geo_quote"


class AdminGeoThrottle(UserRateThrottle):
    scope = "geo_admin"


class PublicGeoThrottle(AnonRateThrottle):
    """Keyed by IP for visitors who are not signed in. Never reaches a paid API."""

    scope = "geo_public"


class LoginThrottle(AnonRateThrottle):
    scope = "auth_login"
