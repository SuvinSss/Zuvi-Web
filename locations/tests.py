from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase

from locations.models import Address


class AddressModelTests(TestCase):
    def test_create_valid_address(self):
        address = Address(
            line1="12 MG Road",
            city="Bengaluru",
            state="Karnataka",
            postal_code="560001",
            latitude=Decimal("12.971600"),
            longitude=Decimal("77.594600"),
        )
        address.full_clean()
        address.save()
        self.assertEqual(str(address), "12 MG Road, Bengaluru, Karnataka, 560001, India")
        self.assertEqual(address.country, "India")

    def test_latitude_out_of_range_rejected(self):
        address = Address(
            line1="12 MG Road",
            city="Bengaluru",
            state="Karnataka",
            postal_code="560001",
            latitude=Decimal("95.000000"),
            longitude=Decimal("77.594600"),
        )
        with self.assertRaises(ValidationError) as ctx:
            address.full_clean()
        self.assertIn("latitude", ctx.exception.message_dict)

    def test_longitude_out_of_range_rejected(self):
        address = Address(
            line1="12 MG Road",
            city="Bengaluru",
            state="Karnataka",
            postal_code="560001",
            latitude=Decimal("12.971600"),
            longitude=Decimal("-181.000000"),
        )
        with self.assertRaises(ValidationError) as ctx:
            address.full_clean()
        self.assertIn("longitude", ctx.exception.message_dict)

    def test_boundary_coordinates_are_valid(self):
        address = Address(
            line1="Edge",
            city="Test",
            state="Test",
            postal_code="000000",
            latitude=Decimal("-90.000000"),
            longitude=Decimal("180.000000"),
        )
        address.full_clean()
        address.save()
        self.assertEqual(address.latitude, Decimal("-90.000000"))


class LocationSelectionTests(TestCase):
    def setUp(self):
        from django.test import Client
        from django.urls import reverse
        self.client = Client(enforce_csrf_checks=True)
        self.set_url = reverse("locations:set_delivery_location")
        self.clear_url = reverse("locations:clear_delivery_location")
        self.client.get(reverse("customers:customer_portal_login"))
        self.csrf = self.client.cookies["csrftoken"].value
        self.saved = {"latitude": "12.971600", "longitude": "77.594600", "label": "Existing synthetic point"}
        session = self.client.session
        session["delivery_location"] = self.saved.copy()
        session.save()

    def _post(self, url, data=None):
        return self.client.post(url, data or {}, HTTP_X_CSRFTOKEN=self.csrf, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

    def test_set_and_clear_require_post_and_enforced_csrf(self):
        for url in (self.set_url, self.clear_url):
            self.assertEqual(self.client.get(url).status_code, 405)
            self.assertEqual(self.client.post(url, self.saved).status_code, 403)
            self.assertEqual(self.client.post(url, self.saved, HTTP_X_CSRFTOKEN="x" * 32).status_code, 403)
            self.assertEqual(self.client.session["delivery_location"], self.saved)
        response = self._post(self.set_url, {**self.saved, "label": "Intentional new point"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True, "label": "Intentional new point"})
        self.assertEqual(self._post(self.clear_url).status_code, 200)
        self.assertNotIn("delivery_location", self.client.session)

    def test_invalid_attempts_preserve_existing_valid_location(self):
        for point in ({}, {"latitude": "invalid", "longitude": "77"}, {"latitude": "91", "longitude": "77"}, {"latitude": "12", "longitude": "181"}, {"latitude": "12"}):
            response = self._post(self.set_url, point)
            self.assertEqual(response.status_code, 400)
            self.assertFalse(response.json()["ok"])
            self.assertEqual(self.client.session["delivery_location"], self.saved)

    def test_browsing_preserves_location_and_sessions_are_isolated(self):
        from django.test import Client
        for url in ("/", "/products/?q=synthetic", "/customer/login/"):
            self.assertEqual(self.client.get(url).status_code, 200)
            self.assertEqual(self.client.session["delivery_location"], self.saved)
        other = Client(enforce_csrf_checks=True)
        self.assertEqual(other.get("/products/").status_code, 200)
        self.assertNotIn("delivery_location", other.session)
        self.assertEqual(self.client.session["delivery_location"], self.saved)

    def test_optional_dialog_contract_and_lazy_map_resources(self):
        response = self.client.get("/customer/login/")
        for value in ('aria-label="Close location selection"', 'Continue browsing', 'data-bs-dismiss="modal"', 'data-open-location-gate', 'role="alert"', 'role="status"', 'modal-dialog-scrollable', 'does not confirm delivery availability'):
            self.assertContains(response, value)
        for value in ('data-bs-keyboard="false"', 'data-bs-backdrop="static"', 'ZOOP_HAS_DELIVERY_LOCATION', "We'll use this to show what's available near you."):
            self.assertNotContains(response, value)
        from html.parser import HTMLParser
        class ResourceParser(HTMLParser):
            def handle_starttag(self, tag, attrs):
                if tag in ("script", "link"):
                    for key, value in attrs:
                        if key in ("src", "href"):
                            if "leaflet" in value:
                                raise AssertionError("Map resources must not block initial page load")
        ResourceParser().feed(response.content.decode())

    def test_saved_addresses_link_only_for_customer(self):
        from django.contrib.auth import get_user_model
        from accounts.models import Role
        from django.urls import reverse
        from django.template.loader import render_to_string
        from django.test import RequestFactory
        from django.contrib.auth.models import AnonymousUser
        request = RequestFactory().get("/")
        for role in (None, Role.ADMIN, Role.STORE_USER, Role.CUSTOMER):
            request.user = AnonymousUser() if role is None else get_user_model()(role=role)
            html = render_to_string("locations/includes/location_gate.html", {"request": request})
            self.assertEqual(reverse("customers:customer_portal_address_list") in html, role == Role.CUSTOMER)
