"""Google Maps URLs (https://developers.google.com/maps/documentation/urls) helpers.

These open the Google Maps app/site for turn-by-turn navigation. They call no
paid API and need no key. They are only generated for locations the caller is
already authorised to see.
"""

from urllib.parse import urlencode

DIRECTIONS_BASE = "https://www.google.com/maps/dir/"


def navigation_url(latitude, longitude, *, place_id="", travel_mode="two-wheeler"):
    params = {
        "api": "1",
        "destination": f"{latitude},{longitude}",
        "travelmode": travel_mode,
    }
    if place_id:
        params["destination_place_id"] = place_id
    return f"{DIRECTIONS_BASE}?{urlencode(params)}"
