"""Provider error classification, admin Maps diagnostics and store pin confirmation. No network, no billing."""
from decimal import Decimal
from unittest import mock
from urllib.error import HTTPError, URLError

from django.contrib.auth.models import Permission
from django.test import SimpleTestCase, override_settings
from rest_framework.test import APIClient

from accounts.models import Role, User
from logistics import providers
from logistics.models import MapsHealthCheck
from logistics.tests_api import NEAR, Base
from logistics.providers import ProviderUnavailable as PU

GOOGLE = dict(LOCATION_GEOCODER="google", LOCATION_ROUTER="google", GOOGLE_MAPS_SERVER_KEY="test-key")


class ErrorClassificationTests(SimpleTestCase):
    def call(self, side_effect):
        with mock.patch.object(providers, "urlopen", side_effect=side_effect):
            with self.assertRaises(PU) as ctx:
                providers._http_get_json("https://maps.googleapis.com/x", {"key": "SECRET"}, {})
        self.assertNotIn("SECRET", str(ctx.exception))
        return ctx.exception.code

    def test_http_statuses(self):
        for status, code in ((403, PU.KEY_REJECTED), (401, PU.KEY_REJECTED), (429, PU.QUOTA_EXCEEDED), (500, PU.BAD_RESPONSE)):
            err = HTTPError("https://maps.googleapis.com/x?key=SECRET", status, "x", {}, None)
            self.assertEqual(self.call(err), code, status)

    def test_timeouts_and_network(self):
        self.assertEqual(self.call(TimeoutError("slow")), PU.TIMEOUT)
        self.assertEqual(self.call(URLError(TimeoutError("slow"))), PU.TIMEOUT)
        self.assertEqual(self.call(URLError("dns")), PU.NETWORK)

    def test_google_status_strings(self):
        geocoder = providers.GoogleGeocoder("k")
        for status, code in (("REQUEST_DENIED", PU.KEY_REJECTED), ("OVER_QUERY_LIMIT", PU.QUOTA_EXCEEDED),
                             ("ZERO_RESULTS", PU.NO_RESULT), ("UNKNOWN_ERROR", PU.BAD_RESPONSE)):
            with mock.patch.object(providers, "_http_get_json", return_value={"status": status, "results": []}):
                with self.assertRaises(PU) as ctx:
                    geocoder.reverse(Decimal("9.9"), Decimal("76.2"))
            self.assertEqual(ctx.exception.code, code, status)

    def test_places_error_bodies(self):
        geocoder = providers.GoogleGeocoder("k")
        with mock.patch.object(providers, "_http_post_json", return_value={"error": {"status": "PERMISSION_DENIED"}}):
            with self.assertRaises(PU) as ctx:
                geocoder.search("kochi")
        self.assertEqual(ctx.exception.code, PU.KEY_REJECTED)
        with mock.patch.object(providers, "_http_get_json", return_value={"error": {"status": "RESOURCE_EXHAUSTED"}}):
            with self.assertRaises(PU) as ctx:
                geocoder.details("ChIJabc123")
        self.assertEqual(ctx.exception.code, PU.QUOTA_EXCEEDED)

    def test_unconfigured_providers(self):
        for call in (lambda: providers.Geocoder().search("x"), lambda: providers.Router().road_km((1, 1), (2, 2))):
            with self.assertRaises(PU) as ctx:
                call()
            self.assertEqual(ctx.exception.code, PU.NOT_CONFIGURED)


class AdminMapsTests(Base):
    def setUp(self):
        # Safety net: nothing may reach the network.
        patcher = mock.patch.object(providers, "urlopen", side_effect=URLError("network disabled in tests"))
        patcher.start()
        self.addCleanup(patcher.stop)
        super().setUp()

    def admin_with(self, *codenames):
        user = User.objects.create_user(username="maps-admin", email="maps@example.com", password="x", role=Role.ADMIN, is_staff=True)
        for name in codenames:
            user.user_permissions.add(Permission.objects.get(codename=name))
        c = APIClient()
        c.force_authenticate(User.objects.get(pk=user.pk))
        return c

    @override_settings(**GOOGLE)
    def test_status_reports_presence_never_the_key(self):
        data = self.boss_api().get("/api/v1/admin/maps/status/").json()
        self.assertTrue(data["configuration"]["server_key_present"])
        self.assertEqual((data["configuration"]["geocoder"], data["configuration"]["router"]), ("google", "google"))
        self.assertNotIn("test-key", str(data))
        self.assertEqual(data["checks"]["ROUTES"]["latest"], None)

    def test_permissions(self):
        for user in (self.customer_user, self.store_user):
            c = APIClient()
            c.force_authenticate(user)
            self.assertEqual(c.get("/api/v1/admin/maps/status/").status_code, 403)
            self.assertEqual(c.post("/api/v1/admin/maps/health-check/").status_code, 403)
        self.assertIn(APIClient().get("/api/v1/admin/maps/status/").status_code, (401, 403))
        viewer = self.admin_with("view_delivery_operations")
        self.assertEqual(viewer.get("/api/v1/admin/maps/status/").status_code, 200)
        self.assertEqual(viewer.post("/api/v1/admin/maps/health-check/").status_code, 403)
        self.assertEqual(MapsHealthCheck.objects.count(), 0)

    def test_health_check_without_configuration_makes_no_calls(self):
        with mock.patch.object(providers, "urlopen") as net:
            r = self.boss_api().post("/api/v1/admin/maps/health-check/")
        net.assert_not_called()
        self.assertEqual(r.status_code, 200)
        self.assertEqual({k: v["error_code"] for k, v in r.json().items()}, {"PLACES": "NOT_CONFIGURED", "GEOCODING": "NOT_CONFIGURED", "ROUTES": "NOT_CONFIGURED"})

    @override_settings(**GOOGLE)
    def test_health_check_records_success_and_failure(self):
        with mock.patch.object(providers, "_http_post_json", side_effect=[
                {"suggestions": []}, {"routes": [{"distanceMeters": 4000}]}]), \
             mock.patch.object(providers, "_http_get_json", return_value={"status": "REQUEST_DENIED", "results": []}):
            r = self.boss_api().post("/api/v1/admin/maps/health-check/").json()
        self.assertTrue(r["PLACES"]["ok"])
        self.assertTrue(r["ROUTES"]["ok"])
        self.assertFalse(r["GEOCODING"]["ok"])
        self.assertEqual(r["GEOCODING"]["error_code"], "KEY_REJECTED")
        self.assertIn("rejected", r["GEOCODING"]["message"])
        self.assertNotIn("test-key", str(r))
        status = self.boss_api().get("/api/v1/admin/maps/status/").json()["checks"]
        self.assertIsNotNone(status["PLACES"]["last_success_at"])
        self.assertIsNone(status["GEOCODING"]["last_success_at"])
        self.assertEqual(MapsHealthCheck.objects.count(), 3)

    @override_settings(**GOOGLE, API_THROTTLE_MAPS_CHECK="1/hour")
    def test_health_check_is_throttled(self):
        from django.core.cache import cache
        cache.clear()
        from rest_framework.throttling import ScopedRateThrottle
        with mock.patch.dict(ScopedRateThrottle.THROTTLE_RATES, {"maps_check": "1/hour"}), \
             mock.patch.object(providers, "_http_post_json", return_value={"suggestions": [], "routes": [{"distanceMeters": 1}]}), \
             mock.patch.object(providers, "_http_get_json", return_value={"status": "ZERO_RESULTS", "results": []}):
            c = self.boss_api()
            self.assertEqual(c.post("/api/v1/admin/maps/health-check/").status_code, 200)
            self.assertEqual(c.post("/api/v1/admin/maps/health-check/").status_code, 429)


class StorePinConfirmationTests(Base):
    def patch_address(self, **address):
        return self.boss_api().patch(f"/api/v1/admin/stores/{self.store.pk}/", {"address": address}, format="json")

    def refresh(self):
        self.store.refresh_from_db()
        return self.store

    def test_confirming_records_who_and_when(self):
        self.assertIsNone(self.store.location_confirmed_at)
        r = self.patch_address(confirm_location=True)
        self.assertEqual(r.status_code, 200, r.content)
        store = self.refresh()
        self.assertIsNotNone(store.location_confirmed_at)
        self.assertEqual(store.location_confirmed_by, self.super_admin)
        detail = self.boss_api().get(f"/api/v1/admin/stores/{self.store.pk}/").json()["location"]
        self.assertTrue(detail["confirmed"])
        self.assertEqual(detail["confirmed_by"], self.super_admin.get_username())

    def test_moving_the_pin_clears_confirmation_unless_reconfirmed(self):
        self.patch_address(confirm_location=True)
        self.patch_address(latitude="9.940000", longitude="76.270000")
        self.assertIsNone(self.refresh().location_confirmed_at)
        self.patch_address(latitude="9.941000", longitude="76.271000", confirm_location=True)
        self.assertIsNotNone(self.refresh().location_confirmed_at)
        self.patch_address(line1="New line")  # unrelated change keeps it
        self.assertIsNotNone(self.refresh().location_confirmed_at)

    def test_cannot_confirm_an_unset_pin(self):
        a = self.store.address
        a.latitude = a.longitude = Decimal("0")
        a.save()
        r = self.patch_address(confirm_location=True)
        self.assertEqual(r.status_code, 400)
        self.assertIsNone(self.refresh().location_confirmed_at)

    def test_not_required_by_default(self):
        self.add_cart()
        r = self.quote()
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["stores"][0]["ok"])

    @override_settings(STORE_PIN_CONFIRMATION_REQUIRED=True)
    def test_when_required_unconfirmed_stores_are_not_serviceable(self):
        listing = self.client.get(f"/api/v1/delivery/stores/?lat={NEAR[0]}&lon={NEAR[1]}").json()
        mine = next(s for s in listing["stores"] if s["id"] == self.store.pk)
        self.assertFalse(mine["serviceable"])
        self.assertTrue(any("not been confirmed" in m for m in mine["reasons"]))
        self.add_cart()
        self.assertFalse(self.quote().json()["stores"][0]["ok"])
        self.patch_address(confirm_location=True)
        self.add_cart()
        self.assertTrue(self.quote().json()["stores"][0]["ok"])
