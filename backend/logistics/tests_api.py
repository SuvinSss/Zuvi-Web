"""Delivery pricing APIs, serviceability, providers, checkout quote and snapshots, payouts, permissions."""
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import Permission
from django.test import override_settings
from django.utils import timezone

from accounts.models import Role, User
from deliveries.tests import DeliveryBase, jpeg
from deliveries import services as delivery_services
from logistics import providers
from logistics.models import CheckoutQuote, DeliveryPricingVersion, PartnerEarning, PricingZone
from logistics.services import create_version, point_in_polygon
from orders.models import Order

KOCHI = (Decimal("9.931233"), Decimal("76.267303"))
NEAR = ("9.960000", "76.290000")   # ~4 km from KOCHI


class Base(DeliveryBase):
    def setUp(self):
        super().setUp()
        a = self.store.address
        a.latitude, a.longitude = KOCHI
        a.save()
        self.store.service_radius_km = Decimal("10")
        self.store.save(update_fields=["service_radius_km"])
        self.addr = self.address.address
        self.addr.latitude, self.addr.longitude = Decimal(NEAR[0]), Decimal(NEAR[1])
        self.addr.save()
        self.api.force_authenticate(self.customer_user)

    def add_cart(self, qty="1"):
        return self.api.post("/api/v1/cart/items/", {"product_id": self.product.pk, "quantity": qty}, format="json")

    def quote(self, **extra):
        return self.api.post("/api/v1/checkout/quote/", {"fulfillment_type": "DELIVERY", "delivery_address_id": self.address.pk, **extra}, format="json")

    def place(self, key, **extra):
        return self.api.post("/api/v1/checkout/", {"fulfillment_type": "DELIVERY", "payment_method": "COD",
                                                    "delivery_address_id": self.address.pk, **extra}, format="json", HTTP_IDEMPOTENCY_KEY=key)

    def boss_api(self):
        from rest_framework.test import APIClient
        c = APIClient()
        c.force_authenticate(self.super_admin)
        return c


class ProviderTests(Base):
    def test_no_provider_configured_degrades_gracefully(self):
        r = self.client.get("/api/v1/geo/search/?q=Edappally")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["available"])
        r = self.client.get(f"/api/v1/geo/reverse/?lat={NEAR[0]}&lon={NEAR[1]}")
        self.assertFalse(r.json()["available"])
        self.assertEqual(self.client.get("/api/v1/geo/reverse/?lat=500&lon=1").status_code, 400)

    @override_settings(LOCATION_GEOCODER="nominatim", LOCATION_GEOCODER_URL="https://geo.test")
    def test_nominatim_results_are_validated_and_cached(self):
        payload = [{"lat": "9.96", "lon": "76.29", "display_name": "Edappally, Kochi, Kerala", "osm_type": "node", "osm_id": 5,
                    "address": {"road": "NH 66", "suburb": "Edappally", "city": "Kochi", "state": "Kerala", "postcode": "682024"}},
                   {"lat": "bad", "lon": "x"}]
        with mock.patch.object(providers, "_http_json", return_value=payload) as m:
            r = self.client.get("/api/v1/geo/search/?q=Edappally").json()
            self.client.get("/api/v1/geo/search/?q=Edappally")
        self.assertEqual(m.call_count, 1)  # cached
        self.assertEqual(len(r["results"]), 1)  # malformed item dropped
        self.assertEqual(r["results"][0]["postal_code"], "682024")

    @override_settings(LOCATION_GEOCODER="nominatim", LOCATION_GEOCODER_URL="https://geo.test")
    def test_provider_timeout_is_not_a_server_error(self):
        with mock.patch.object(providers, "_http_json", side_effect=providers.ProviderUnavailable("timeout")):
            r = self.client.get("/api/v1/geo/search/?q=Thrissur")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["available"])

    @override_settings(LOCATION_ROUTER="osrm", LOCATION_ROUTER_URL="https://route.test")
    def test_road_route_used_when_available(self):
        self.add_cart()
        with mock.patch.object(providers, "_http_json", return_value={"code": "Ok", "routes": [{"distance": 6200}]}):
            q = self.quote().json()
        d = q["stores"][0]["delivery"]
        self.assertEqual((d["distance_km"], d["distance_source"]), ("6.20", "road"))

    def test_without_router_distance_is_labelled_estimated(self):
        self.add_cart()
        d = self.quote().json()["stores"][0]["delivery"]
        self.assertEqual(d["distance_source"], "estimated")
        self.assertIn("estimated", d["explanation"])

    def test_estimates_can_be_forbidden(self):
        v = DeliveryPricingVersion.objects.get()
        create_version(actor=self.super_admin, data={"allow_estimated_distance": False}, reason="Road distance only")
        self.add_cart()
        r = self.quote().json()
        self.assertFalse(r["all_deliverable"])
        self.assertIn("road distance", r["stores"][0]["error"])
        self.assertEqual(v.pk, DeliveryPricingVersion.objects.order_by("version").first().pk)


class ServiceabilityTests(Base):
    def test_lists_deliverable_stores_with_fee(self):
        r = self.client.get(f"/api/v1/delivery/stores/?lat={NEAR[0]}&lon={NEAR[1]}").json()
        row = next(s for s in r["stores"] if s["id"] == self.store.pk)
        self.assertTrue(row["serviceable"])
        self.assertIsNotNone(row["fee"])

    def test_outside_radius_closed_or_missing_location(self):
        far = ("10.527642", "76.214435")  # Thrissur, ~70 km
        row = next(s for s in self.client.get(f"/api/v1/delivery/stores/?lat={far[0]}&lon={far[1]}").json()["stores"] if s["id"] == self.store.pk)
        self.assertFalse(row["serviceable"])
        self.assertIn("delivers within", " ".join(row["reasons"]))
        self.store.opening_hours = {"mon": [{"open": "00:00", "close": "00:01"}]}
        self.store.save(update_fields=["opening_hours"])
        row = next(s for s in self.client.get(f"/api/v1/delivery/stores/?lat={NEAR[0]}&lon={NEAR[1]}").json()["stores"] if s["id"] == self.store.pk)
        self.assertFalse(row["serviceable"])
        a = self.store.address
        a.latitude = a.longitude = Decimal("0")
        a.save()
        self.store.opening_hours = {}
        self.store.save(update_fields=["opening_hours"])
        row = next(s for s in self.client.get(f"/api/v1/delivery/stores/?lat={NEAR[0]}&lon={NEAR[1]}").json()["stores"] if s["id"] == self.store.pk)
        self.assertIn("Store location is not set.", row["reasons"])

    def test_zone_mode_uses_polygon(self):
        z = PricingZone.objects.create(name="Edappally", polygon=[[9.95, 76.28], [9.97, 76.28], [9.97, 76.30], [9.95, 76.30]])
        self.assertTrue(point_in_polygon(Decimal(NEAR[0]), Decimal(NEAR[1]), z.polygon))
        self.store.service_mode, self.store.service_zone = "ZONE", z
        self.store.save()
        ok = next(s for s in self.client.get(f"/api/v1/delivery/stores/?lat={NEAR[0]}&lon={NEAR[1]}").json()["stores"] if s["id"] == self.store.pk)
        self.assertTrue(ok["serviceable"])
        out = next(s for s in self.client.get("/api/v1/delivery/stores/?lat=9.94&lon=76.27").json()["stores"] if s["id"] == self.store.pk)
        self.assertFalse(out["serviceable"])

    def test_inactive_store_never_deliverable(self):
        self.store.status = "SUSPENDED"
        self.store.save(update_fields=["status"])
        ids = [s["id"] for s in self.client.get(f"/api/v1/delivery/stores/?lat={NEAR[0]}&lon={NEAR[1]}").json()["stores"]]
        self.assertNotIn(self.store.pk, ids)


class CheckoutPricingTests(Base):
    def test_quote_then_order_charges_server_fee_and_snapshots_it(self):
        self.add_cart()
        q = self.quote().json()
        fee = Decimal(q["delivery_total"])
        self.assertGreater(fee, 0)
        self.assertNotIn("estimated_cost", str(q))  # customers never see cost or rider pay
        self.assertNotIn("partner_payout", str(q))
        r = self.place("k1", quote_token=q["quote_token"], delivery_charge="0", grand_total="1")
        self.assertEqual(r.status_code, 201, r.content)
        order = Order.objects.get(pk=r.json()["id"])
        self.assertEqual(order.delivery_charge, fee)  # tampered client totals ignored
        so = order.store_orders.get()
        self.assertEqual(so.delivery_pricing["customer_total"], str(fee))
        self.assertIsNotNone(so.delivery_pricing_version_id)
        self.assertEqual(CheckoutQuote.objects.get(token=q["quote_token"]).order, order)

    def test_snapshot_survives_settings_change(self):
        self.add_cart()
        r = self.place("k2")
        order = Order.objects.get(pk=r.json()["id"])
        before = order.store_orders.get().delivery_pricing
        create_version(actor=self.super_admin, data={"energy_price": "130", "base_fee": "60", "min_fee": "60", "max_fee": "120"}, reason="Fuel up")
        order.refresh_from_db()
        self.assertEqual(order.store_orders.get().delivery_pricing, before)
        self.assertEqual(r.json()["delivery_charge"], before["customer_total"])

    def test_price_change_after_quote_is_explained_with_409(self):
        self.add_cart()
        q = self.quote().json()
        create_version(actor=self.super_admin, data={"base_fee": "45", "min_fee": "45"}, reason="Raise base fee")
        r = self.place("k3", quote_token=q["quote_token"])
        self.assertEqual(r.status_code, 409)
        self.assertTrue(r.json()["price_changed"])
        self.assertIn("changed", r.json()["quote_token"][0])
        self.assertFalse(Order.objects.filter(checkout_token="k3").exists())

    def test_cart_or_address_change_needs_new_quote(self):
        self.add_cart()
        q = self.quote().json()
        self.add_cart("1")  # quantity changes
        self.assertEqual(self.place("k4", quote_token=q["quote_token"]).status_code, 409)

    def test_expired_and_reused_quotes(self):
        self.add_cart()
        q = self.quote().json()
        CheckoutQuote.objects.filter(token=q["quote_token"]).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.place("k5", quote_token=q["quote_token"]).status_code, 409)
        q2 = self.quote().json()
        self.assertEqual(self.place("k6", quote_token=q2["quote_token"]).status_code, 201)
        self.add_cart()
        self.assertEqual(self.place("k7", quote_token=q2["quote_token"]).status_code, 400)  # already used

    def test_duplicate_submission_creates_one_order(self):
        self.add_cart()
        q = self.quote().json()
        a = self.place("same", quote_token=q["quote_token"])
        b = self.place("same", quote_token=q["quote_token"])
        self.assertEqual((a.status_code, b.status_code), (201, 200))
        self.assertEqual(Order.objects.filter(checkout_token="same").count(), 1)

    def test_free_delivery_offer_and_funder(self):
        create_version(actor=self.super_admin, data={"free_delivery_threshold": "1", "free_delivery_funded_by": "STORE"}, reason="Store promo")
        self.add_cart()
        d = self.quote().json()["stores"][0]["delivery"]
        self.assertEqual(d["customer_total"], "0.00")
        self.assertIn("Free delivery", d["discount_reason"])
        so = Order.objects.get(pk=self.place("k8").json()["id"]).store_orders.get()
        self.assertEqual(Decimal(so.delivery_pricing["store_funded_promotion"]), Decimal(so.delivery_pricing["customer_fee_before_discount"]))

    def test_unpinned_or_unserviceable_address_blocks_delivery(self):
        self.addr.latitude = self.addr.longitude = Decimal("0")
        self.addr.save()
        self.add_cart()
        self.assertFalse(self.quote().json()["all_deliverable"])
        self.assertEqual(self.place("k9").status_code, 400)

    def test_quote_requires_own_address(self):
        other_customer, other_user = self.other_customer_with_address()
        self.add_cart()
        r = self.quote(delivery_address_id=other_customer)
        self.assertIn(r.status_code, (400, 404))

    def other_customer_with_address(self):
        from customers.models import AddressLabel, RegistrationSource
        from customers.services import create_customer_delivery_address, create_customer_with_user
        cust, user = create_customer_with_user(user_data={"username": "q-other", "email": "q-other@example.com", "password": "secure-password-123",
                                                          "first_name": "Q", "phone_number": "9000000888"}, registration_source=RegistrationSource.WEBSITE)
        a = create_customer_delivery_address(customer=cust, data={"label": AddressLabel.HOME, "recipient_name": "Q", "phone_number": "9000000888",
                                                                  "line1": "1", "city": "Kochi", "state": "Kerala", "postal_code": "682001",
                                                                  "latitude": NEAR[0], "longitude": NEAR[1], "is_default": True})
        return a.pk, user


class AddressTests(Base):
    def payload(self, **over):
        return {"label": "OTHER", "custom_label": "Amma's house", "recipient_name": "R", "phone_number": "9000000777", "line1": "Rose Villa",
                "line2": "Market Road", "city": "Paravur", "state": "Kerala", "postal_code": "", "latitude": NEAR[0], "longitude": NEAR[1],
                "location_source": "PIN", "location_confirmed": True, **over}

    def test_custom_label_optional_pin_and_confirmation(self):
        r = self.api.post("/api/v1/customer/addresses/", self.payload(), format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual((r.json()["short_label"], r.json()["location_confirmed"]), ("Amma's house", True))
        self.assertEqual(self.api.post("/api/v1/customer/addresses/", self.payload(postal_code="12345"), format="json").status_code, 400)
        self.assertEqual(self.api.post("/api/v1/customer/addresses/", self.payload(latitude="0", longitude="0"), format="json").status_code, 400)


class AdminPricingTests(Base):
    def test_versioning_audit_and_validation(self):
        api = self.boss_api()
        r = api.post("/api/v1/admin/delivery-pricing/", {"settings": {"energy_price": "113.74", "energy_price_source": "Kochi pump, verified"},
                                                         "reason": "Verified local price"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["version"], 2)
        self.assertEqual(api.post("/api/v1/admin/delivery-pricing/", {"settings": {"efficiency_km_per_unit": "0"}, "reason": "x"}, format="json").status_code, 400)
        self.assertEqual(api.post("/api/v1/admin/delivery-pricing/", {"settings": {"energy_price": "100"}}, format="json").status_code, 400)  # reason required
        from core.models import AuditEvent
        ev = AuditEvent.objects.filter(action="delivery_pricing.version_created").latest("pk")
        self.assertEqual(ev.metadata["changes"]["energy_price"], {"from": "115", "to": "113.74"})
        data = api.get("/api/v1/admin/delivery-pricing/").json()
        self.assertEqual(data["active"]["version"], 2)
        self.assertEqual(len(data["history"]), 2)

    def test_scheduled_version_takes_effect_later(self):
        api = self.boss_api()
        later = (timezone.now() + timedelta(days=1)).isoformat()
        api.post("/api/v1/admin/delivery-pricing/", {"settings": {"base_fee": "40"}, "reason": "Next week", "effective_from": later}, format="json")
        data = api.get("/api/v1/admin/delivery-pricing/").json()
        self.assertEqual(data["active"]["version"], 1)
        self.assertEqual(len(data["scheduled"]), 1)

    def test_simulator_matches_worked_example_and_saves_nothing(self):
        api = self.boss_api()
        overrides = {"energy_price": "115", "efficiency_km_per_unit": "40", "operational_multiplier": "2.0", "maintenance_per_km": "1.50",
                     "rider_pay_per_order": "25", "rider_pay_per_km": "0", "overhead_per_order": "8", "overhead_per_km": "0", "failure_cost_rate": "0.10",
                     "pricing_mode": "BANDS", "distance_bands": [{"up_to_km": 6, "fee": 55}], "min_fee": "0", "max_fee": "100", "rounding": "NONE"}
        r = api.post("/api/v1/admin/delivery-pricing/simulate/", {"distance_km": "5", "overrides": overrides,
                                                                  "batch": {"route_km": "8", "stops": [{"key": "a", "distance_km": 3}, {"key": "b", "distance_km": 5}]}}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        res = r.json()["result"]
        self.assertEqual((res["estimated_cost"], res["customer_fee"], res["platform_subsidy"]), ("84.43", "55.00", "29.43"))
        self.assertEqual(len(r.json()["batch"]["allocations"]), 2)
        self.assertEqual(DeliveryPricingVersion.objects.count(), 1)

    def test_zone_crud_and_polygon_validation(self):
        api = self.boss_api()
        self.assertEqual(api.post("/api/v1/admin/delivery-zones/", {"name": "Bad", "polygon": [[1, 2]]}, format="json").status_code, 400)
        r = api.post("/api/v1/admin/delivery-zones/", {"name": "Hill area", "polygon": [[9.9, 76.2], [10, 76.2], [10, 76.3]], "service_area_surcharge": "10"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(api.patch(f"/api/v1/admin/delivery-zones/{r.json()['id']}/", {"is_active": False}, format="json").json()["is_active"], False)
        self.assertEqual(api.post("/api/v1/admin/delivery-zones/", {"name": "hill AREA"}, format="json").status_code, 400)  # duplicate name is a 400, not a crash

    def test_role_permissions(self):
        from rest_framework.test import APIClient
        plain = User.objects.create_user(username="dp-admin", email="dp@example.com", password="x", role=Role.ADMIN, is_staff=True)
        c = APIClient()
        c.force_authenticate(plain)
        self.assertEqual(c.get("/api/v1/admin/delivery-pricing/").status_code, 403)
        plain.user_permissions.add(Permission.objects.get(codename="view_delivery_operations"))
        plain = User.objects.get(pk=plain.pk)
        c.force_authenticate(plain)
        self.assertEqual(c.get("/api/v1/admin/delivery-pricing/").status_code, 200)
        self.assertEqual(c.post("/api/v1/admin/delivery-pricing/", {"settings": {}, "reason": "x"}, format="json").status_code, 403)
        for user in (self.customer_user, self.store_user):
            c.force_authenticate(user)
            self.assertEqual(c.get("/api/v1/admin/delivery-pricing/").status_code, 403)
            self.assertEqual(c.post("/api/v1/admin/delivery-pricing/simulate/", {"distance_km": "1"}, format="json").status_code, 403)

    def test_operations_report(self):
        self.add_cart()
        self.place("ops1")
        r = self.boss_api().get("/api/v1/admin/delivery-operations/").json()
        from orders.models import StoreOrder
        self.assertEqual(r["economics"]["priced_deliveries"], StoreOrder.objects.exclude(delivery_pricing={}).count())
        self.assertGreaterEqual(r["economics"]["priced_deliveries"], 1)
        self.assertIn("platform_subsidy", r["economics"])


class PayoutAndStoreTests(Base):
    def setUp(self):
        super().setUp()
        self.add_cart()
        oid = self.place("pay1").json()["id"]
        self.order = Order.objects.get(pk=oid)
        self.store_order = self.order.store_orders.get()

    def test_rider_earns_snapshot_payout_and_failed_attempt_pay(self):
        partner = self.make_partner("rider-pay")
        delivery = self.accepted_delivery(partner)
        trip = self.as_user(partner.user).get(f"/api/v1/deliveries/{delivery.pk}/").json()["trip"]
        self.assertEqual(trip["estimated_payout"], self.store_order.delivery_pricing["partner_payout"])
        self.assertNotIn("platform_subsidy", str(trip))
        self.pickup(delivery, partner)
        delivery_services.fail_delivery(delivery.pk, partner, reason="CUSTOMER_UNAVAILABLE")
        self.assertEqual(PartnerEarning.objects.get(kind="FAILED_ATTEMPT").amount, Decimal("15.00"))
        # Recording the same failure twice never pays twice.
        from logistics.payouts import record_failed_attempt_earning
        delivery.refresh_from_db()
        record_failed_attempt_earning(delivery, "CUSTOMER_UNAVAILABLE")
        self.assertEqual(PartnerEarning.objects.filter(kind="FAILED_ATTEMPT").count(), 1)

    def test_completed_delivery_pays_the_snapshot_amount(self):
        partner = self.make_partner("rider-done")
        delivery = self.accepted_delivery(partner)
        self.pickup(delivery, partner)
        delivery_services.complete_delivery(delivery.pk, partner, **self.deliver_payload())
        e = PartnerEarning.objects.get(kind="DELIVERY")
        self.assertEqual(e.amount, Decimal(self.store_order.delivery_pricing["partner_payout"]))
        self.assertNotEqual(e.amount, self.order.delivery_charge)  # rider pay is not the customer fee
        r = self.as_user(partner.user).get("/api/v1/delivery/earnings/").json()
        self.assertEqual(Decimal(r["summary"]["total"]), e.amount)
        other = self.make_partner("rider-other")
        self.assertEqual(self.as_user(other.user).get("/api/v1/delivery/earnings/").json()["results"], [])

    def test_vehicle_problem_is_not_paid(self):
        partner = self.make_partner("rider-veh")
        delivery = self.accepted_delivery(partner)
        self.pickup(delivery, partner)
        delivery_services.fail_delivery(delivery.pk, partner, reason="VEHICLE_PROBLEM")
        self.assertFalse(PartnerEarning.objects.exists())

    def test_admin_marks_paid_with_reference(self):
        partner = self.make_partner("rider-paid")
        delivery = self.accepted_delivery(partner)
        self.pickup(delivery, partner)
        delivery_services.complete_delivery(delivery.pk, partner, **self.deliver_payload())
        api = self.boss_api()
        ids = [e["id"] for e in api.get("/api/v1/admin/partner-earnings/").json()]
        self.assertEqual(api.post("/api/v1/admin/partner-earnings/", {"ids": ids}, format="json").status_code, 400)
        self.assertEqual(api.post("/api/v1/admin/partner-earnings/", {"ids": ids, "payout_reference": "UPI-123"}, format="json").json()["updated"], 1)

    def test_store_finance_separates_delivery_and_commission(self):
        self.store.commission_percentage = Decimal("10")
        self.store.save(update_fields=["commission_percentage"])
        r = self.as_user(self.store_user).get("/api/v1/store/finance/").json()
        row = r["orders"][0]
        self.assertEqual(Decimal(row["commission"]), (self.store_order.items_subtotal * Decimal("0.10")).quantize(Decimal("0.01")))
        self.assertEqual(Decimal(row["settlement"]), self.store_order.items_subtotal - Decimal(row["commission"]))
        self.assertIn("not store revenue", r["note"])
        self.assertNotIn("estimated_cost", str(r))
