import json
from decimal import Decimal

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from cart.services import add_product_to_cart
from customers.models import CustomerAddress
from locations.models import Address
from orders.models import Order
from orders.tests_checkout import CheckoutTestMixin

from .models import DeliveryQuote
from .testing import DeliveryFixtureMixin, GoogleFakeMixin, make_pricing_config, route_ok

PAYLOAD = {
    "label": "HOME", "recipient_name": "Asha", "phone_number": "9000000777", "line1": "12 Beach Road",
    "city": "Paravur", "district": "Kollam", "state": "Kerala", "postal_code": "691301",
    "latitude": "8.813900", "longitude": "76.667200", "location_confirmed": True,
    "location_source": "PLACE_SEARCH", "google_place_id": "ChIJtestPlaceId1234567",
}


class AddressApiTests(GoogleFakeMixin, DeliveryFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.customer, self.user = self.make_customer("alice")
        self.other, self.other_user = self.make_customer("bob")
        self.client = APIClient()
        self.client.force_login(self.user)

    def post(self, **over):
        return self.client.post("/api/v1/customer/addresses/", {**PAYLOAD, **over}, format="json")

    def test_create_stores_structured_fields_place_id_and_confirmation(self):
        response = self.post()
        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()
        self.assertEqual(data["google_place_id"], "ChIJtestPlaceId1234567")
        self.assertEqual(data["location_source"], "PLACE_SEARCH")
        self.assertTrue(data["location_confirmed"])
        self.assertTrue(data["is_default"])  # first address is the default
        address = Address.objects.get()
        self.assertIsNotNone(address.location_confirmed_at)
        self.assertEqual(CustomerAddress.objects.get().customer_id, self.customer.pk)

    def test_unconfirmed_pin_cannot_be_saved(self):
        self.assertEqual(self.post(location_confirmed=False).status_code, 400)
        self.assertEqual(Address.objects.count(), 0)

    def test_invalid_input_is_rejected(self):
        for over in ({"latitude": "100"}, {"longitude": "abc"}, {"label": "PALACE"},
                     {"google_place_id": "x'; drop table"}, {"location_source": "TELEPATHY"}, {"line1": ""}):
            self.assertEqual(self.post(**over).status_code, 400, over)

    def test_mass_assignment_cannot_change_owner_or_state(self):
        response = self.post(customer=self.other.pk, customer_id=self.other.pk, is_active=False, id=9999,
                             user=self.other_user.pk)
        self.assertEqual(response.status_code, 201)
        created = CustomerAddress.objects.get()
        self.assertEqual(created.customer_id, self.customer.pk)
        self.assertTrue(created.is_active)
        self.assertNotEqual(created.pk, 9999)

    def test_list_returns_only_my_active_addresses(self):
        self.post()
        mine_other = self.make_address(self.other)
        data = self.client.get("/api/v1/customer/addresses/").json()
        self.assertEqual(len(data["addresses"]), 1)
        self.assertNotIn(mine_other.pk, [a["id"] for a in data["addresses"]])

    def test_other_customers_address_is_not_found_for_every_verb(self):
        theirs = self.make_address(self.other)
        base = f"/api/v1/customer/addresses/{theirs.pk}/"
        self.assertEqual(self.client.get(base).status_code, 404)
        self.assertEqual(self.client.patch(base, {"line1": "hijacked"}, format="json").status_code, 404)
        self.assertEqual(self.client.delete(base).status_code, 404)
        self.assertEqual(self.client.post(base + "default/").status_code, 404)
        theirs.refresh_from_db()
        self.assertTrue(theirs.is_active)
        self.assertNotEqual(theirs.address.line1, "hijacked")

    def test_edit_moving_the_pin_requires_reconfirmation(self):
        created = self.post().json()
        url = f"/api/v1/customer/addresses/{created['id']}/"
        self.assertEqual(self.client.patch(url, {"landmark": "Near temple"}, format="json").status_code, 200)
        self.assertEqual(self.client.patch(url, {"latitude": "8.82"}, format="json").status_code, 400)
        moved = self.client.patch(url, {"latitude": "8.820000", "location_confirmed": True,
                                        "location_source": "MAP_PIN"}, format="json")
        self.assertEqual(moved.status_code, 200)
        self.assertEqual(moved.json()["latitude"], "8.820000")
        self.assertEqual(moved.json()["location_source"], "MAP_PIN")

    def test_default_switching_and_soft_delete(self):
        first = self.post().json()
        second = self.post(label="WORK", line1="Office").json()
        self.assertFalse(second["is_default"])
        self.client.post(f"/api/v1/customer/addresses/{second['id']}/default/")
        listing = {a["id"]: a for a in self.client.get("/api/v1/customer/addresses/").json()["addresses"]}
        self.assertTrue(listing[second["id"]]["is_default"])
        self.assertFalse(listing[first["id"]]["is_default"])
        self.assertEqual(self.client.delete(f"/api/v1/customer/addresses/{second['id']}/").status_code, 204)
        remaining = self.client.get("/api/v1/customer/addresses/").json()["addresses"]
        self.assertEqual([a["id"] for a in remaining], [first["id"]])
        self.assertTrue(remaining[0]["is_default"])  # promoted
        self.assertTrue(CustomerAddress.objects.filter(pk=second["id"], is_active=False).exists())

    def test_other_roles_and_anonymous_are_refused(self):
        self.assertIn(APIClient().get("/api/v1/customer/addresses/").status_code, (401, 403))
        agent = APIClient()
        agent.force_login(self.make_agent())
        self.assertEqual(agent.get("/api/v1/customer/addresses/").status_code, 403)
        admin = APIClient()
        admin.force_login(self.make_super_admin())
        self.assertEqual(admin.post("/api/v1/customer/addresses/", PAYLOAD, format="json").status_code, 403)

    def test_post_requires_csrf_for_signed_in_users(self):
        client = APIClient(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post("/api/v1/customer/addresses/", PAYLOAD, format="json").status_code, 403)


class QuoteAndCheckoutApiTests(GoogleFakeMixin, DeliveryFixtureMixin, CheckoutTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.customer, self.user = self.make_customer("carol")
        self.address = self.make_address(self.customer)
        self.store = self.confirm_store(self.create_store(name="API Store"))
        self.product = self.create_public_product(store=self.store, stock=Decimal("30"))
        add_product_to_cart(customer=self.customer, product_code=self.product.product_code, quantity=Decimal("2"))
        make_pricing_config()
        self.client = APIClient()
        self.client.force_login(self.user)

    def quote(self, meters=4000):
        self.google.push(*route_ok(meters, 600))
        return self.client.post("/api/v1/customer/delivery-quote/", {"address_id": self.address.pk}, format="json")

    def test_quote_is_customer_safe(self):
        response = self.quote()
        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()
        self.assertEqual(data["delivery_fee"], "44.00")
        self.assertEqual(data["legs"][0]["road_distance_km"], "4.0")
        text = json.dumps(data).lower()
        for secret in ("operational", "rider", "payout", "subsidy", "unrecovered", "mileage", "fuel", "provider"):
            self.assertNotIn(secret, text)
        self.assertIn("google", data["distance_note"].lower())

    def test_quote_for_someone_elses_address_is_not_found(self):
        other, _ = self.make_customer("dave")
        theirs = self.make_address(other)
        response = self.client.post("/api/v1/customer/delivery-quote/", {"address_id": theirs.pk}, format="json")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.google.calls, [])

    def test_unserviceable_address_gets_reasons_and_a_clear_message(self):
        far = self.make_address(self.customer, lat="9.700000", lng="77.700000", is_default=False)
        response = self.client.post("/api/v1/customer/delivery-quote/", {"address_id": far.pk}, format="json")
        self.assertEqual(response.status_code, 422)
        error = response.json()["error"]
        self.assertEqual(error["code"], "NOT_SERVICEABLE")
        self.assertEqual(error["reasons"][0]["code"], "OUTSIDE_RADIUS")
        self.assertIn("outside", error["reasons"][0]["message"].lower())

    def test_route_quota_error_is_graceful(self):
        self.google.push(429, {"error": {"status": "RESOURCE_EXHAUSTED", "message": "quota"}})
        response = self.client.post("/api/v1/customer/delivery-quote/", {"address_id": self.address.pk}, format="json")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "MAPS_QUOTA_EXCEEDED")
        self.assertTrue(response.json()["error"]["retryable"])

    def test_full_checkout_flow_charges_the_server_fee(self):
        summary = self.client.get("/api/v1/customer/checkout/summary/").json()
        self.assertEqual(summary["cart"]["stores"][0]["store_id"], self.store.pk)
        quote_id = self.quote().json()["id"]
        response = self.client.post(
            "/api/v1/customer/checkout/",
            {"address_id": self.address.pk, "quote_id": quote_id, "checkout_token": summary["checkout_token"]},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        order = Order.objects.get()
        self.assertEqual(order.delivery_charge, Decimal("44.00"))
        self.assertEqual(response.json()["delivery_charge"], "44.00")

    def test_client_supplied_prices_are_ignored(self):
        summary = self.client.get("/api/v1/customer/checkout/summary/").json()
        quote_id = self.quote().json()["id"]
        response = self.client.post(
            "/api/v1/customer/checkout/",
            {"address_id": self.address.pk, "quote_id": quote_id, "checkout_token": summary["checkout_token"],
             "delivery_fee": "0.00", "delivery_charge": "0", "grand_total": "1", "items_subtotal": "1",
             "discount_total": "999"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        order = Order.objects.get()
        self.assertEqual(order.delivery_charge, Decimal("44.00"))
        self.assertEqual(order.discount_total, Decimal("0.00"))
        self.assertEqual(order.grand_total, order.items_subtotal + Decimal("44.00"))

    def test_tampered_quote_id_is_refused(self):
        summary = self.client.get("/api/v1/customer/checkout/summary/").json()
        self.quote()
        for bad in (999999,):
            response = self.client.post(
                "/api/v1/customer/checkout/",
                {"address_id": self.address.pk, "quote_id": bad, "checkout_token": summary["checkout_token"]},
                format="json")
            self.assertEqual(response.status_code, 400)
            self.assertIn("quote", json.dumps(response.json()).lower())
        self.assertEqual(Order.objects.count(), 0)

    def test_wrong_checkout_token(self):
        quote_id = self.quote().json()["id"]
        self.client.get("/api/v1/customer/checkout/summary/")
        response = self.client.post(
            "/api/v1/customer/checkout/",
            {"address_id": self.address.pk, "quote_id": quote_id, "checkout_token": "guess"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Order.objects.count(), 0)

    def test_double_submit_creates_one_order(self):
        summary = self.client.get("/api/v1/customer/checkout/summary/").json()
        quote_id = self.quote().json()["id"]
        body = {"address_id": self.address.pk, "quote_id": quote_id, "checkout_token": summary["checkout_token"]}
        first = self.client.post("/api/v1/customer/checkout/", body, format="json")
        second = self.client.post("/api/v1/customer/checkout/", body, format="json")
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 400)
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(DeliveryQuote.objects.filter(status="CONSUMED").count(), 1)

    @override_settings(DELIVERY_QUOTES_ENFORCED=True)
    def test_enforced_checkout_without_a_quote_fails(self):
        summary = self.client.get("/api/v1/customer/checkout/summary/").json()
        response = self.client.post(
            "/api/v1/customer/checkout/",
            {"address_id": self.address.pk, "quote_id": 1, "checkout_token": summary["checkout_token"]},
            format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Order.objects.count(), 0)

    def test_tracking_is_private_and_shows_no_rider_data(self):
        summary = self.client.get("/api/v1/customer/checkout/summary/").json()
        quote_id = self.quote().json()["id"]
        number = self.client.post(
            "/api/v1/customer/checkout/",
            {"address_id": self.address.pk, "quote_id": quote_id, "checkout_token": summary["checkout_token"]},
            format="json").json()["order_number"]
        tracking = self.client.get(f"/api/v1/customer/orders/{number}/tracking/")
        self.assertEqual(tracking.status_code, 200)
        body = tracking.json()
        self.assertEqual(body["delivery"]["latitude"], self.address.address.latitude.__str__())
        text = json.dumps(body).lower()
        for secret in ("payout", "operational", "agent", "rider", "snapshot"):
            self.assertNotIn(secret, text)
        self.assertIn("don't estimate", body["delivery_time_note"])
        stranger = APIClient()
        _, other_user = self.make_customer("eve")
        stranger.force_login(other_user)
        self.assertEqual(stranger.get(f"/api/v1/customer/orders/{number}/tracking/").status_code, 404)
