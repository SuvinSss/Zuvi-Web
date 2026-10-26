import json
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from cart.services import add_product_to_cart
from geo import quotes
from geo.models import DeliveryPricingConfig, MapsHealthCheck
from geo.pricing import get_active_config, price_leg
from orders.checkout import place_customer_order
from orders.models import DeliveryAssignment, FulfillmentType, PaymentMethod, StoreOrderStatus
from orders.tests_checkout import CheckoutTestMixin

from .testing import (
    TEST_SERVER_KEY,
    DeliveryFixtureMixin,
    GoogleFakeMixin,
    geocode_ok,
    make_pricing_config,
    route_ok,
)

SAMPLE_LOCATION = {
    "line1": "1 Market Road", "city": "Paravur", "state": "Kerala", "postal_code": "691301",
    "latitude": "8.815000", "longitude": "76.668000", "google_place_id": "ChIJtestPlaceId1234567",
}


def login(user):
    client = APIClient()
    client.force_login(user)
    return client


class OpsBase(GoogleFakeMixin, DeliveryFixtureMixin, CheckoutTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.store = self.create_store(name="Ops Store")
        self.store.address.latitude, self.store.address.longitude = Decimal(self.STORE_LAT), Decimal(self.STORE_LNG)
        self.store.address.save()


class StoreLocationApiTests(OpsBase):
    def test_store_user_sees_and_updates_only_their_own_store(self):
        other_store = self.create_store(name="Other")
        user = self.make_store_user(self.store)
        client = login(user)
        report = client.get("/api/v1/store/location/").json()
        self.assertEqual(report["id"], self.store.pk)
        self.assertIn("unconfirmed", [i["code"] for i in report["issues"]])
        self.assertFalse(report["can_take_delivery_orders"])
        updated = client.patch("/api/v1/store/location/", {**SAMPLE_LOCATION, "confirm": True}, format="json")
        self.assertEqual(updated.status_code, 200, updated.content)
        self.assertTrue(updated.json()["can_take_delivery_orders"])
        self.store.refresh_from_db()
        self.assertEqual(self.store.location_confirmed_by_id, user.pk)
        other_store.refresh_from_db()
        self.assertIsNone(other_store.location_confirmed_at)  # a client id cannot redirect the edit

    def test_moving_the_pin_without_confirming_clears_confirmation(self):
        self.confirm_store(self.store)
        client = login(self.make_store_user(self.store))
        response = client.patch("/api/v1/store/location/", SAMPLE_LOCATION, format="json")
        self.assertIsNone(response.json()["location_confirmed_at"])
        self.assertIn("unconfirmed", [i["code"] for i in response.json()["issues"]])

    def test_suspicious_pins_cannot_be_confirmed(self):
        client = login(self.make_store_user(self.store))
        for lat, lng in (("0", "0"), ("51.5", "-0.12")):
            response = client.patch("/api/v1/store/location/", {**SAMPLE_LOCATION, "latitude": lat, "longitude": lng,
                                                                "confirm": True}, format="json")
            self.assertEqual(response.status_code, 400, (lat, lng))

    def test_store_user_cannot_change_the_delivery_radius(self):
        client = login(self.make_store_user(self.store))
        client.patch("/api/v1/store/location/", {**SAMPLE_LOCATION, "delivery_radius_km": "90"}, format="json")
        self.store.refresh_from_db()
        self.assertEqual(self.store.delivery_radius_km, Decimal("10.00"))

    def test_other_roles_are_refused(self):
        customer, user = self.make_customer()
        self.assertEqual(login(user).get("/api/v1/store/location/").status_code, 403)
        self.assertEqual(login(self.make_agent()).get("/api/v1/store/location/").status_code, 403)
        self.assertIn(APIClient().get("/api/v1/store/location/").status_code, (401, 403))


class AdminMapsApiTests(OpsBase):
    def test_permissions_are_enforced_per_capability(self):
        plain_admin = login(self.make_admin(username="plain"))
        maps_admin = login(self.make_admin("manage_maps_operations", username="maps"))
        self.assertEqual(plain_admin.get("/api/v1/admin/maps/status/").status_code, 403)
        self.assertEqual(maps_admin.get("/api/v1/admin/maps/status/").status_code, 200)
        self.assertEqual(maps_admin.get("/api/v1/admin/pricing/configs/").status_code, 403)
        self.assertEqual(login(self.make_super_admin()).get("/api/v1/admin/pricing/configs/").status_code, 200)
        _, customer_user = self.make_customer()
        self.assertEqual(login(customer_user).get("/api/v1/admin/maps/status/").status_code, 403)
        self.assertEqual(login(self.make_store_user(self.store)).get("/api/v1/admin/stores/locations/").status_code, 403)

    def test_status_never_exposes_keys_and_separates_present_from_working(self):
        client = login(self.make_super_admin())
        body = client.get("/api/v1/admin/maps/status/").json()
        text = json.dumps(body)
        self.assertNotIn(TEST_SERVER_KEY, text)
        self.assertTrue(body["configuration"]["server_key_present"])
        # A key being present proves nothing: no health check has run yet.
        self.assertIsNone(body["health"]["GEOCODING"]["ok"])
        self.assertIsNone(body["health"]["GEOCODING"]["last_success_at"])
        self.assertFalse(body["pricing_configured"])

    def test_health_check_makes_real_calls_and_records_results(self):
        client = login(self.make_super_admin())
        self.google.push(*geocode_ok()).push(*route_ok(2000, 300))
        result = client.post("/api/v1/admin/maps/health-check/").json()
        self.assertTrue(result["GEOCODING"]["ok"] and result["ROUTES"]["ok"])
        self.assertEqual(MapsHealthCheck.objects.count(), 2)
        health = client.get("/api/v1/admin/maps/status/").json()["health"]
        self.assertTrue(health["ROUTES"]["ok"])
        self.assertIsNotNone(health["ROUTES"]["last_success_at"])

    def test_failed_health_check_is_recorded_with_a_safe_message(self):
        client = login(self.make_super_admin())
        self.google.push(200, {"status": "REQUEST_DENIED", "error_message": TEST_SERVER_KEY})
        self.google.push(403, {"error": {"status": "PERMISSION_DENIED", "message": TEST_SERVER_KEY}})
        with self.assertLogs("geo.google", level="WARNING"):
            result = client.post("/api/v1/admin/maps/health-check/").json()
        self.assertFalse(result["GEOCODING"]["ok"])
        self.assertEqual(result["ROUTES"]["error_code"], "MAPS_KEY_REJECTED")
        stored = " ".join(MapsHealthCheck.objects.values_list("message", flat=True))
        self.assertNotIn(TEST_SERVER_KEY, stored + json.dumps(result))

    def test_store_location_report_flags_problems_and_duplicates(self):
        good = self.confirm_store(self.create_store(name="Good"), "8.9", "76.7")
        pinless = self.create_store(name="Pinless")
        pinless.address.latitude = pinless.address.longitude = Decimal("0")
        pinless.address.save()
        abroad = self.confirm_store(self.create_store(name="Abroad"), "51.5", "-0.12")
        twin_a = self.confirm_store(self.create_store(name="TwinA"), "9.1", "76.9")
        twin_b = self.confirm_store(self.create_store(name="TwinB"), "9.1", "76.9")
        data = login(self.make_super_admin()).get("/api/v1/admin/stores/locations/").json()
        by_name = {s["name"]: {i["code"] for i in s["issues"]} for s in data["stores"]}
        self.assertEqual(by_name["Good"], set())
        self.assertIn("null_island", by_name["Pinless"])
        self.assertIn("outside_india", by_name["Abroad"])
        self.assertIn("duplicate_location", by_name["TwinA"])
        self.assertIn("duplicate_location", by_name["TwinB"])
        self.assertIn("unconfirmed", by_name["Ops Store"])
        self.assertTrue(all(i["action"] for s in data["stores"] for i in s["issues"]))
        self.assertGreaterEqual(data["needs_attention"], 5)
        self.assertTrue(good and twin_a and twin_b and abroad)

    def test_admin_can_correct_a_store_pin_and_radius(self):
        client = login(self.make_super_admin())
        response = client.patch(f"/api/v1/admin/stores/{self.store.pk}/location/",
                                {**SAMPLE_LOCATION, "confirm": True, "delivery_radius_km": "7.5"}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.store.refresh_from_db()
        self.assertEqual(self.store.delivery_radius_km, Decimal("7.50"))
        self.assertIsNotNone(self.store.location_confirmed_at)
        self.assertEqual(client.patch("/api/v1/admin/stores/99999/location/", SAMPLE_LOCATION, format="json").status_code, 404)

    def test_pricing_versions_are_append_only_and_one_is_active(self):
        client = login(self.make_super_admin())
        body = dict(fuel_price_per_litre="100", vehicle_mileage_km_per_litre="40", customer_base_fee="20")
        first = client.post("/api/v1/admin/pricing/configs/", body, format="json").json()
        second = client.post("/api/v1/admin/pricing/configs/", {**body, "customer_base_fee": "30"}, format="json").json()
        self.assertEqual((first["version"], second["version"]), (1, 2))
        self.assertEqual(list(DeliveryPricingConfig.objects.filter(is_active=True).values_list("version", flat=True)), [2])
        self.assertEqual(DeliveryPricingConfig.objects.get(version=1).customer_base_fee, Decimal("20.00"))
        invalid = client.post("/api/v1/admin/pricing/configs/", {**body, "vehicle_mileage_km_per_litre": "0"}, format="json")
        self.assertEqual(invalid.status_code, 400)

    def test_simulator_uses_the_checkout_pricing_function_and_labels_the_route(self):
        make_pricing_config()
        client = login(self.make_super_admin())
        self.google.push(*route_ok(4000, 600))
        body = {"store_id": self.store.pk, "latitude": "8.83", "longitude": "76.70", "items_subtotal": "250"}
        live = client.post("/api/v1/admin/pricing/simulate/", body, format="json").json()
        expected = price_leg(get_active_config(), road_distance_meters=4000, items_subtotal=Decimal("250"))
        self.assertEqual(live["pricing"]["customer_fee"], str(expected.fee_after_discount))
        self.assertEqual(live["pricing"]["rider_payout"], str(expected.rider_payout))
        self.assertEqual(live["pricing"]["operational_cost"], str(expected.operational_cost))
        self.assertEqual(live["pricing"]["contribution"], str(expected.contribution))
        self.assertEqual(live["route"]["source"], "LIVE")
        self.assertTrue(live["route"]["is_live"])
        self.assertEqual(live["input"]["kind"], "SIMULATED_DESTINATION")
        cached = client.post("/api/v1/admin/pricing/simulate/", body, format="json").json()
        self.assertEqual(cached["route"]["source"], "CACHED")
        self.assertFalse(cached["route"]["is_live"])
        self.assertEqual(len(self.google.calls), 1)
        self.google.push(*route_ok(4500, 650))
        forced = client.post("/api/v1/admin/pricing/simulate/", {**body, "refresh": True}, format="json").json()
        self.assertEqual(forced["route"]["source"], "LIVE")

    def test_simulator_matches_a_real_quote_for_the_same_route(self):
        make_pricing_config()
        customer, user = self.make_customer()
        address = self.make_address(customer)
        self.confirm_store(self.store)
        product = self.create_public_product(store=self.store, stock=Decimal("20"))
        add_product_to_cart(customer=customer, product_code=product.product_code, quantity=Decimal("2"))
        self.google.push(*route_ok(4000, 600))
        quote = quotes.create_quote(customer, address)
        sim = login(self.make_super_admin()).post(
            "/api/v1/admin/pricing/simulate/",
            {"store_id": self.store.pk, "latitude": self.HOME_LAT, "longitude": self.HOME_LNG,
             "items_subtotal": str(quote.legs.get().items_subtotal)}, format="json").json()
        self.assertEqual(sim["pricing"]["customer_fee"], str(quote.delivery_fee))

    def test_simulator_without_pricing_or_with_bad_input(self):
        client = login(self.make_super_admin())
        body = {"store_id": self.store.pk, "latitude": "8.83", "longitude": "76.70", "items_subtotal": "10"}
        self.assertEqual(client.post("/api/v1/admin/pricing/simulate/", body, format="json").json()["error"]["code"],
                         "PRICING_NOT_CONFIGURED")
        make_pricing_config()
        self.assertEqual(client.post("/api/v1/admin/pricing/simulate/", {**body, "latitude": "99"}, format="json").status_code, 400)
        self.assertEqual(client.post("/api/v1/admin/pricing/simulate/", {**body, "store_id": 424242}, format="json").status_code, 404)
        self.assertEqual(client.post("/api/v1/admin/pricing/simulate/", {**body, "items_subtotal": "-5"}, format="json").status_code, 400)


class DeliveryPartnerApiTests(OpsBase):
    def setUp(self):
        super().setUp()
        make_pricing_config()
        self.confirm_store(self.store)
        self.customer, self.customer_user = self.make_customer("rider-customer")
        self.address = self.make_address(self.customer, delivery_instructions="Ring twice")
        product = self.create_public_product(store=self.store, stock=Decimal("20"))
        add_product_to_cart(customer=self.customer, product_code=product.product_code, quantity=Decimal("2"))
        self.google.push(*route_ok(4000, 600))
        quote = quotes.create_quote(self.customer, self.address)
        self.order = place_customer_order(
            customer=self.customer, checkout_token="rider-1", fulfillment_type=FulfillmentType.DELIVERY,
            payment_method=PaymentMethod.COD, delivery_address_id=self.address.pk, actor=self.customer_user,
            delivery_quote_id=quote.pk)
        self.store_order = self.order.store_orders.get()
        self.agent = self.make_agent("agent-one")
        self.other_agent = self.make_agent("agent-two")
        self.admin = login(self.make_super_admin())

    def set_status(self, status):
        type(self.store_order).objects.filter(pk=self.store_order.pk).update(status=status)

    def assign(self, agent=None):
        return self.admin.post("/api/v1/admin/assignments/", {
            "store_order_number": self.store_order.store_order_number, "agent_id": (agent or self.agent).pk},
            format="json")

    def test_assignment_rules(self):
        self.assertEqual(self.assign().status_code, 400)  # still PENDING at the store
        self.set_status(StoreOrderStatus.ACCEPTED)
        self.assertEqual(self.assign().status_code, 201)
        self.assertEqual(self.assign(self.other_agent).status_code, 400)  # one partner per store order
        self.assertEqual(DeliveryAssignment.objects.count(), 1)
        _, customer_user = self.make_customer()
        self.assertEqual(login(customer_user).post("/api/v1/admin/assignments/", {}, format="json").status_code, 403)
        not_agent = self.admin.post("/api/v1/admin/assignments/", {
            "store_order_number": self.store_order.store_order_number, "agent_id": self.customer_user.pk}, format="json")
        self.assertEqual(not_agent.status_code, 400)

    def test_partner_sees_pickup_dropoff_navigation_and_route_for_their_assignment_only(self):
        self.set_status(StoreOrderStatus.ACCEPTED)
        self.assign()
        mine = login(self.agent)
        listing = mine.get("/api/v1/rider/assignments/").json()["assignments"]
        self.assertEqual(len(listing), 1)
        detail = mine.get(f"/api/v1/rider/assignments/{listing[0]['id']}/").json()
        self.assertEqual(detail["pickup"]["navigation_url"].split("?")[0], "https://www.google.com/maps/dir/")
        self.assertIn("destination=8.813900%2C76.667200", detail["pickup"]["navigation_url"])
        self.assertIn("destination=8.830000%2C76.700000", detail["dropoff"]["navigation_url"])
        self.assertIn("travelmode=two-wheeler", detail["dropoff"]["navigation_url"])
        self.assertEqual(detail["dropoff"]["recipient_name"], "Geo Customer")
        self.assertEqual(detail["delivery_instructions"], self.order.delivery_instructions)
        self.assertEqual(detail["route"], {"distance_km": "4.0", "duration_minutes": 10, "source": "LIVE"})
        self.assertEqual(detail["next_action"]["code"], "WAIT")
        text = json.dumps(detail).lower()
        for secret in ("payout", "fee", "operational", "subsidy"):
            self.assertNotIn(secret, text)
        stranger = login(self.other_agent)
        self.assertEqual(stranger.get(f"/api/v1/rider/assignments/{listing[0]['id']}/").status_code, 404)
        self.assertEqual(stranger.post(f"/api/v1/rider/assignments/{listing[0]['id']}/advance/").status_code, 404)
        self.assertEqual(stranger.get("/api/v1/rider/assignments/").json()["assignments"], [])

    def test_partner_progress_and_no_way_to_change_money(self):
        self.set_status(StoreOrderStatus.ACCEPTED)
        pk = self.assign().json()["id"]
        mine = login(self.agent)
        self.assertEqual(mine.post(f"/api/v1/rider/assignments/{pk}/advance/").status_code, 400)  # store not ready
        self.set_status(StoreOrderStatus.READY)
        self.assertEqual(mine.post(f"/api/v1/rider/assignments/{pk}/advance/").json()["status"], "PICKED_UP")
        self.assertEqual(mine.post(f"/api/v1/rider/assignments/{pk}/advance/").json()["status"], "ARRIVED")
        self.assertEqual(mine.post(f"/api/v1/rider/assignments/{pk}/advance/").status_code, 400)
        before = (self.order.delivery_charge, self.order.grand_total)
        mine.patch(f"/api/v1/rider/assignments/{pk}/", {"delivery_charge": "0"}, format="json")
        self.order.refresh_from_db()
        self.assertEqual((self.order.delivery_charge, self.order.grand_total), before)

    def test_customer_details_disappear_once_the_delivery_is_finished(self):
        self.set_status(StoreOrderStatus.READY)
        self.assign()
        self.set_status(StoreOrderStatus.COMPLETED)
        mine = login(self.agent)
        self.assertEqual(mine.get("/api/v1/rider/assignments/").json()["assignments"], [])
        pk = DeliveryAssignment.objects.get().pk
        detail = mine.get(f"/api/v1/rider/assignments/{pk}/").json()
        self.assertNotIn("dropoff", detail)
        self.assertIsNone(detail["next_action"])

    def test_non_partners_cannot_use_rider_endpoints(self):
        self.assertEqual(login(self.customer_user).get("/api/v1/rider/assignments/").status_code, 403)
        self.assertEqual(self.admin.get("/api/v1/rider/assignments/").status_code, 403)
        self.assertIn(APIClient().get("/api/v1/rider/assignments/").status_code, (401, 403))

    def test_store_sees_customer_dropoff_only_after_accepting(self):
        store_client = login(self.make_store_user(self.store))
        pending = store_client.get("/api/v1/store/orders/").json()["orders"][0]
        self.assertNotIn("dropoff", pending)
        self.assertIn("navigation_url", pending["pickup"])
        self.set_status(StoreOrderStatus.ACCEPTED)
        accepted = store_client.get("/api/v1/store/orders/").json()["orders"][0]
        self.assertEqual(accepted["dropoff"]["recipient_name"], "Geo Customer")
        self.set_status(StoreOrderStatus.REJECTED)
        self.assertNotIn("dropoff", store_client.get("/api/v1/store/orders/").json()["orders"][0])

    def test_another_stores_orders_are_never_listed(self):
        other_store = self.confirm_store(self.create_store(name="Rival"), "8.9", "76.8")
        rival = login(self.make_store_user(other_store, "rival-user"))
        self.assertEqual(rival.get("/api/v1/store/orders/").json()["orders"], [])
