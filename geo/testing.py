"""Test helpers: a fake Google network boundary and response builders.

Importing this module never touches the network.
"""

from django.core.cache import cache
from django.test import override_settings

from . import google_client

TEST_SERVER_KEY = "test-server-key-NOT-A-REAL-KEY"
TEST_BROWSER_KEY = "test-browser-key-NOT-A-REAL-KEY"

GOOGLE_SETTINGS = dict(
    GOOGLE_MAPS_SERVER_API_KEY=TEST_SERVER_KEY,
    GOOGLE_MAPS_BROWSER_API_KEY=TEST_BROWSER_KEY,
    GOOGLE_MAPS_MAP_ID="TEST_MAP_ID",
    GOOGLE_ROUTES_CACHE_TTL_SECONDS=600,
)


def coord(lat, lng):
    from .coords import parse_coordinate

    return parse_coordinate(lat, lng)


class FakeTransport:
    """Returns queued responses in order, or calls ``handler(method, url, **kw)``."""

    def __init__(self, handler=None):
        self.calls = []
        self.queue = []
        self.handler = handler

    def push(self, status, body=None, *, raises=None):
        self.queue.append((status, body, raises))
        return self

    def request(self, method, url, *, headers=None, params=None, json=None, timeout=5.0):
        self.calls.append({"method": method, "url": url, "headers": headers or {}, "params": params or {},
                           "json": json, "timeout": timeout})
        if self.handler:
            return self.handler(method, url, headers=headers, params=params, json=json)
        if not self.queue:
            raise AssertionError(f"Unexpected Google call to {url}")
        status, body, raises = self.queue.pop(0)
        if raises:
            raise raises
        return status, body


class GoogleFakeMixin:
    """Install a FakeTransport and a clean cache for each test."""

    google_overrides = GOOGLE_SETTINGS

    def setUp(self):
        super().setUp()
        cache.clear()
        self._settings = override_settings(**self.google_overrides)
        self._settings.enable()
        self.google = FakeTransport()
        self._previous = google_client.set_transport(self.google)

    def tearDown(self):
        google_client.set_transport(self._previous)
        self._settings.disable()
        cache.clear()
        super().tearDown()


def route_ok(meters=3200, seconds=480):
    return 200, {"routes": [{"distanceMeters": meters, "duration": f"{seconds}s"}]}


def matrix_ok(rows):
    """rows: list of (origin_index, destination_index, meters, seconds) -> element dicts."""
    return 200, [
        {"originIndex": o, "destinationIndex": d, "status": {}, "condition": "ROUTE_EXISTS",
         "distanceMeters": m, "duration": f"{s}s"}
        for o, d, m, s in rows
    ]


def geocode_ok(address="12 Test Road, Paravur, Kerala 691301, India", lat=8.8139, lng=76.6672,
               location_type="ROOFTOP", place_id="ChIJtestPlaceId1234567"):
    return 200, {
        "status": "OK",
        "results": [{
            "formatted_address": address,
            "place_id": place_id,
            "geometry": {"location": {"lat": lat, "lng": lng}, "location_type": location_type},
            "address_components": [
                {"long_name": "12", "types": ["street_number"]},
                {"long_name": "Test Road", "types": ["route"]},
                {"long_name": "Paravur", "types": ["locality"]},
                {"long_name": "Kollam", "types": ["administrative_area_level_2"]},
                {"long_name": "Kerala", "types": ["administrative_area_level_1"]},
                {"long_name": "691301", "types": ["postal_code"]},
                {"long_name": "India", "types": ["country"]},
            ],
        }],
    }


# --------------------------------------------------------------- database fixtures

def make_pricing_config(**overrides):
    from decimal import Decimal

    from .models import DeliveryPricingConfig

    values = dict(
        version=1, name="Test pricing", is_active=True,
        fuel_price_per_litre=Decimal("100"), vehicle_mileage_km_per_litre=Decimal("40"),
        maintenance_cost_per_km=Decimal("0.50"), operational_distance_multiplier=Decimal("2"),
        rider_base_payout=Decimal("10"), rider_payout_per_km=Decimal("2"), other_cost_per_delivery=Decimal("1"),
        customer_base_fee=Decimal("20"), customer_free_distance_km=Decimal("1"), customer_fee_per_km=Decimal("8"),
        customer_minimum_fee=Decimal("25"), customer_maximum_fee=Decimal("80"), fee_rounding_step=Decimal("1"),
        max_road_distance_km=Decimal("15"),
    )
    values.update(overrides)
    if values["is_active"]:
        DeliveryPricingConfig.objects.filter(is_active=True).update(is_active=False)
    return DeliveryPricingConfig.objects.create(**values)


class DeliveryFixtureMixin:
    """A customer with a saved address and a basket from stores in a small Kerala-like area."""

    STORE_LAT, STORE_LNG = "8.813900", "76.667200"
    HOME_LAT, HOME_LNG = "8.830000", "76.700000"

    _customer_serial = 0

    def make_customer(self, username="geo-customer"):
        from customers.models import RegistrationSource
        from customers.services import create_customer_with_user

        DeliveryFixtureMixin._customer_serial += 1
        phone = f"90000{DeliveryFixtureMixin._customer_serial:05d}"
        return create_customer_with_user(
            user_data={"username": username, "email": f"{username}@example.com", "first_name": "Geo",
                       "last_name": "Customer", "phone_number": phone, "password": "secure-password-123"},
            registration_source=RegistrationSource.WEBSITE,
        )

    def make_address(self, customer, lat=None, lng=None, **extra):
        from customers.models import AddressLabel
        from customers.services import create_customer_delivery_address

        return create_customer_delivery_address(
            customer=customer,
            data={"label": AddressLabel.HOME, "recipient_name": "Geo Customer", "phone_number": "9000000500",
                  "line1": "5 Test Lane", "line2": "", "landmark": "", "city": "Paravur", "district": "Kollam",
                  "state": "Kerala", "postal_code": "691301", "latitude": lat or self.HOME_LAT,
                  "longitude": lng or self.HOME_LNG, "delivery_instructions": "", "is_default": True, **extra},
        )

    def confirm_store(self, store, lat=None, lng=None):
        from decimal import Decimal

        from django.utils import timezone

        store.address.latitude = Decimal(lat or self.STORE_LAT)
        store.address.longitude = Decimal(lng or self.STORE_LNG)
        store.address.save()
        store.location_confirmed_at = timezone.now()
        store.save()
        return store

    # --- users for the other roles
    def _user(self, username, role, **extra):
        from django.contrib.auth import get_user_model

        return get_user_model().objects.create_user(
            username=username, email=f"{username}@example.com", password="secure-password-123", role=role, **extra
        )

    def make_super_admin(self, username="geo-super"):
        from accounts.models import Role

        return self._user(username, Role.SUPER_ADMIN, is_staff=True, is_superuser=True)

    def make_admin(self, *codenames, username="geo-admin"):
        from django.contrib.auth.models import Permission

        from accounts.models import Role

        user = self._user(username, Role.ADMIN, is_staff=True)
        for codename in codenames:
            user.user_permissions.add(Permission.objects.get(content_type__app_label="geo", codename=codename))
        return type(user).objects.get(pk=user.pk)

    def make_store_user(self, store, username="geo-store-user"):
        from accounts.models import Role
        from stores.models import StoreUser

        user = self._user(username, Role.STORE_USER)
        StoreUser.objects.create(store=store, user=user, is_primary=True, is_active=True)
        return user

    def make_agent(self, username="geo-agent"):
        from accounts.models import Role

        return self._user(username, Role.DELIVERY_AGENT)
