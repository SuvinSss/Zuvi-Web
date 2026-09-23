from django.conf import settings

from customers.decorators import resolve_customer_portal_profile


def delivery_location(request):
    """Expose the shopper's session-selected delivery point to every template."""
    customer, _ = resolve_customer_portal_profile(request.user)
    return {
        "location_customer": customer,
        "location_addresses": (
            customer.addresses.filter(is_active=True).select_related("address")
            if customer else []
        ),
        "delivery_location": request.session.get("delivery_location"),
        "google_maps_config": {
            "apiKey": settings.GOOGLE_MAPS_API_KEY,
            "mapId": settings.GOOGLE_MAPS_MAP_ID,
        },
    }
