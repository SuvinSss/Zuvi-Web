import json
import logging
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from accounts.models import Role

from .api.throttles import GeocodeThrottle
from .testing import (
    TEST_BROWSER_KEY,
    TEST_SERVER_KEY,
    DeliveryFixtureMixin,
    GoogleFakeMixin,
    geocode_ok,
)


class ConfigAndSessionTests(GoogleFakeMixin, DeliveryFixtureMixin, TestCase):
    def test_browser_config_contains_the_browser_key_and_never_the_server_key(self):
        response = APIClient().get("/api/v1/config/maps/")
        self.assertEqual(response.status_code, 200)
        body = json.dumps(response.json())
        self.assertIn(TEST_BROWSER_KEY, body)
        self.assertNotIn(TEST_SERVER_KEY, body)
        self.assertNotIn("serverKey", body)
        self.assertEqual(response.json()["mapId"], "TEST_MAP_ID")
        self.assertTrue(response.json()["serverConfigured"])
        self.assertEqual(response["Cache-Control"], "no-store")

    @override_settings(GOOGLE_MAPS_BROWSER_API_KEY="", GOOGLE_MAPS_SERVER_API_KEY="", GOOGLE_MAPS_MAP_ID="")
    def test_unconfigured_state_is_reported_honestly(self):
        data = APIClient().get("/api/v1/config/maps/").json()
        self.assertFalse(data["browserConfigured"])
        self.assertFalse(data["serverConfigured"])
        self.assertEqual(data["browserKey"], "")

    def test_session_is_anonymous_by_default_and_sets_a_csrf_cookie(self):
        response = APIClient().get("/api/v1/auth/session/")
        self.assertEqual(response.json()["authenticated"], False)
        self.assertIn("csrftoken", response.cookies)

    def test_login_for_each_portal_and_wrong_portal_is_refused(self):
        customer, user = self.make_customer()
        client = APIClient()
        wrong = client.post("/api/v1/auth/login/", {"username": user.username, "password": "secure-password-123",
                                                    "portal": "admin"}, format="json")
        self.assertEqual(wrong.status_code, 403)
        self.assertEqual(wrong.json()["error"]["code"], "WRONG_PORTAL")
        ok = client.post("/api/v1/auth/login/", {"username": user.username, "password": "secure-password-123",
                                                 "portal": "customer"}, format="json")
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json()["portal"], "customer")
        self.assertEqual(client.get("/api/v1/auth/session/").json()["authenticated"], True)

    def test_bad_credentials(self):
        self.make_customer()
        response = APIClient().post("/api/v1/auth/login/", {"username": "geo-customer", "password": "nope",
                                                            "portal": "customer"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "BAD_CREDENTIALS")

    def test_login_requires_csrf(self):
        _, user = self.make_customer()
        client = APIClient(enforce_csrf_checks=True)
        response = client.post("/api/v1/auth/login/", {"username": user.username, "password": "secure-password-123",
                                                       "portal": "customer"}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_each_role_resolves_to_its_own_portal(self):
        customer, cu = self.make_customer()
        store = self.confirm_store(self._store())
        roles = {
            "customer": cu,
            "store": self.make_store_user(store),
            "delivery": self.make_agent(),
            "admin": self.make_super_admin(),
        }
        for portal, user in roles.items():
            client = APIClient()
            client.force_login(user)
            self.assertEqual(client.get("/api/v1/auth/session/").json()["portal"], portal)

    def test_logout(self):
        _, user = self.make_customer()
        client = APIClient()
        client.force_login(user)
        self.assertEqual(client.post("/api/v1/auth/logout/").status_code, 204)
        self.assertEqual(client.get("/api/v1/auth/session/").json()["authenticated"], False)

    def _store(self):
        from orders.tests_checkout import CheckoutTestMixin

        class M(CheckoutTestMixin):
            pass

        return M().create_store()


class GeocodeEndpointTests(GoogleFakeMixin, DeliveryFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.customer, self.user = self.make_customer()
        self.client = APIClient()
        self.client.force_login(self.user)

    def test_anonymous_users_cannot_spend_paid_quota(self):
        response = APIClient().post("/api/v1/geo/reverse-geocode/", {"latitude": "8.8", "longitude": "76.6"},
                                    format="json")
        self.assertIn(response.status_code, (401, 403))
        self.assertEqual(self.google.calls, [])

    def test_reverse_geocode(self):
        self.google.push(*geocode_ok())
        response = self.client.post("/api/v1/geo/reverse-geocode/", {"latitude": "8.8139", "longitude": "76.6672"},
                                    format="json")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["components"]["locality"], "Paravur")
        self.assertTrue(data["precise"])
        self.assertEqual(data["place_id"], "ChIJtestPlaceId1234567")
        self.assertNotIn(TEST_SERVER_KEY, json.dumps(data))

    def test_invalid_and_malicious_coordinates_never_reach_google(self):
        for lat, lng in (("91", "10"), ("10", "181"), ("abc", "10"), ("NaN", "10"), ("Infinity", "1"),
                         ("1; DROP TABLE", "1"), ("", "")):
            response = self.client.post("/api/v1/geo/reverse-geocode/", {"latitude": lat, "longitude": lng},
                                        format="json")
            self.assertEqual(response.status_code, 400, (lat, lng))
        self.assertEqual(self.google.calls, [])

    def test_forward_geocode(self):
        self.google.push(*geocode_ok())
        response = self.client.post("/api/v1/geo/geocode/", {"address": "12 Test Road Paravur"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.google.calls[0]["params"]["components"], "country:IN")

    def test_google_rejecting_the_key_is_reported_without_details(self):
        self.google.push(200, {"status": "REQUEST_DENIED", "error_message": f"The key {TEST_SERVER_KEY} is bad"})
        with self.assertLogs("geo.google", level=logging.WARNING):
            response = self.client.post("/api/v1/geo/reverse-geocode/", {"latitude": "8.8", "longitude": "76.6"},
                                        format="json")
        self.assertEqual(response.status_code, 503)
        body = json.dumps(response.json())
        self.assertNotIn(TEST_SERVER_KEY, body)
        self.assertNotIn("REQUEST_DENIED", body)
        self.assertEqual(response.json()["error"]["code"], "MAPS_KEY_REJECTED")

    @override_settings(GOOGLE_MAPS_SERVER_API_KEY="")
    def test_missing_server_key_gives_a_clear_not_configured_error(self):
        response = self.client.post("/api/v1/geo/reverse-geocode/", {"latitude": "8.8", "longitude": "76.6"},
                                    format="json")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "MAPS_NOT_CONFIGURED")

    def test_repeated_requests_are_rate_limited(self):
        cache.clear()
        with patch.dict(GeocodeThrottle.THROTTLE_RATES, {"geo_geocode": "2/min"}):
            self.google.handler = lambda *a, **k: geocode_ok()
            codes = [
                self.client.post("/api/v1/geo/reverse-geocode/", {"latitude": "8.8", "longitude": "76.6"},
                                 format="json").status_code
                for _ in range(4)
            ]
        self.assertEqual(codes, [200, 200, 429, 429])
        self.assertEqual(len(self.google.calls), 2)

    def test_geocoding_results_are_not_stored(self):
        from locations.models import Address

        self.google.push(*geocode_ok())
        self.client.post("/api/v1/geo/reverse-geocode/", {"latitude": "8.8139", "longitude": "76.6672"}, format="json")
        self.assertEqual(Address.objects.count(), 0)


class NearbyStoresTests(GoogleFakeMixin, DeliveryFixtureMixin, TestCase):
    def test_public_straight_line_results_never_call_google(self):
        from orders.tests_checkout import CheckoutTestMixin

        class M(CheckoutTestMixin):
            pass

        m = M()
        near = self.confirm_store(m.create_store(name="Near"))
        far = self.confirm_store(m.create_store(name="Far"), "10.500000", "78.500000")
        data = APIClient().get("/api/v1/stores/nearby/", {"lat": "8.83", "lng": "76.70"}).json()
        names = [s["name"] for s in data["stores"]]
        self.assertEqual(names, ["Near"])
        self.assertTrue(data["approximate"])
        self.assertEqual(self.google.calls, [])
        self.assertNotIn("address", json.dumps(data).lower())
        self.assertTrue(near and far)

    def test_invalid_point(self):
        self.assertEqual(APIClient().get("/api/v1/stores/nearby/", {"lat": "x", "lng": "1"}).status_code, 400)
        self.assertEqual(APIClient().get("/api/v1/stores/nearby/").status_code, 400)
