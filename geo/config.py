"""Single place that reads Google Maps configuration from Django settings."""

from dataclasses import dataclass

from django.conf import settings


@dataclass(frozen=True)
class MapsConfig:
    browser_key: str
    server_key: str
    map_id: str
    region: str
    language: str
    travel_mode: str
    timeout: float
    route_cache_ttl: int
    address_validation_enabled: bool

    @property
    def browser_configured(self):
        return bool(self.browser_key)

    @property
    def server_configured(self):
        return bool(self.server_key)

    @property
    def map_id_configured(self):
        return bool(self.map_id)


def get_maps_config() -> MapsConfig:
    return MapsConfig(
        browser_key=(settings.GOOGLE_MAPS_BROWSER_API_KEY or "").strip(),
        server_key=(settings.GOOGLE_MAPS_SERVER_API_KEY or "").strip(),
        map_id=(settings.GOOGLE_MAPS_MAP_ID or "").strip(),
        region=settings.GOOGLE_MAPS_REGION,
        language=settings.GOOGLE_MAPS_LANGUAGE,
        travel_mode=settings.GOOGLE_ROUTES_TRAVEL_MODE,
        timeout=float(settings.GOOGLE_HTTP_TIMEOUT_SECONDS),
        route_cache_ttl=int(settings.GOOGLE_ROUTES_CACHE_TTL_SECONDS),
        address_validation_enabled=bool(settings.GOOGLE_ADDRESS_VALIDATION_ENABLED),
    )


def browser_client_config() -> dict:
    """What the React app may know. Contains the *browser* key only.

    A browser key is public by design and is protected by HTTP-referrer and API
    restrictions in Google Cloud. The server key is never included here.
    """
    cfg = get_maps_config()
    return {
        "browserKey": cfg.browser_key,
        "mapId": cfg.map_id,
        "region": cfg.region,
        "language": cfg.language,
        "browserConfigured": cfg.browser_configured,
        "serverConfigured": cfg.server_configured,
    }
