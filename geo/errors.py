"""Domain errors for Google Maps Platform integration.

Every error carries a stable machine ``code`` and a plain-language
``public_message`` that is safe to show to users. Raw Google responses, URLs and
API keys must never appear in ``public_message``.
"""


class MapsError(Exception):
    code = "MAPS_ERROR"
    http_status = 502
    public_message = "Location services are temporarily unavailable. Please try again."
    retryable = True

    def __init__(self, detail="", *, public_message=None):
        super().__init__(detail or self.code)
        self.detail = detail
        if public_message:
            self.public_message = public_message


class MapsNotConfigured(MapsError):
    code = "MAPS_NOT_CONFIGURED"
    http_status = 503
    retryable = False
    public_message = "Location services are not configured yet."


class MapsKeyRejected(MapsError):
    """Google rejected the key: invalid, restricted, API not enabled or billing off."""

    code = "MAPS_KEY_REJECTED"
    http_status = 503
    retryable = False
    public_message = "Location services are not available right now."


class MapsQuotaExceeded(MapsError):
    code = "MAPS_QUOTA_EXCEEDED"
    http_status = 503
    public_message = "Location services are busy. Please try again shortly."


class MapsTimeout(MapsError):
    code = "MAPS_TIMEOUT"
    http_status = 504
    public_message = "Location services took too long to respond. Please try again."


class MapsNetworkError(MapsError):
    code = "MAPS_NETWORK_ERROR"
    http_status = 503
    public_message = "Could not reach location services. Please try again."


class MapsBadResponse(MapsError):
    code = "MAPS_BAD_RESPONSE"
    http_status = 502
    public_message = "Location services returned an unexpected response."


class InvalidCoordinates(MapsError):
    code = "INVALID_COORDINATES"
    http_status = 400
    retryable = False
    public_message = "The selected location is not valid. Please choose it again."


class NoRouteFound(MapsError):
    code = "NO_ROUTE"
    http_status = 422
    retryable = False
    public_message = "No road route could be found to this location."


class AmbiguousRoute(MapsError):
    code = "AMBIGUOUS_ROUTE"
    http_status = 502
    retryable = False
    public_message = "The route for this location could not be confirmed."


class GeocodeNotFound(MapsError):
    code = "ADDRESS_NOT_FOUND"
    http_status = 404
    retryable = False
    public_message = "We could not find an address for this location."


class PricingNotConfigured(MapsError):
    code = "PRICING_NOT_CONFIGURED"
    http_status = 503
    retryable = False
    public_message = "Delivery pricing is not available right now."


class QuoteError(MapsError):
    """Quote cannot be used (expired, mismatched, already consumed, foreign)."""

    code = "QUOTE_INVALID"
    http_status = 409
    retryable = False
    public_message = "Your delivery quote is no longer valid. Please review the delivery fee."
