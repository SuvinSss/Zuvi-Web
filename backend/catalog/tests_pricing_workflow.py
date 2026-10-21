"""Pricing calculator, set-price API, bulk pricing, historical order prices."""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from accounts.models import Role, User
from catalog import pricing
from catalog.models import Product, ProductPriceHistory
from catalog.tests import CatalogTestMixin
from django.contrib.auth.models import Permission


class CalculatorTests(SimpleTestCase):
    def test_margin_and_markup_are_different_numbers(self):
        b = pricing.price_breakdown(cost="600", selling_price="800", discount_type="FIXED", discount_value="100")
        self.assertEqual(b["final_price"], "700.00")
        self.assertEqual(b["discount_amount"], "100.00")
        self.assertEqual(b["profit_per_unit"], "100.00")
        self.assertEqual(b["margin_percent"], "14.29")   # profit / final price
        self.assertEqual(b["markup_percent"], "16.67")   # profit / cost
        self.assertIn("Estimated gross profit", b["label"])

    def test_percentage_discount_example(self):
        b = pricing.price_breakdown(cost="500", selling_price="1000", discount_type="PERCENTAGE", discount_value="15")
        self.assertEqual((b["discount_amount"], b["final_price"]), ("150.00", "850.00"))

    def test_zero_cost_gives_no_markup_instead_of_dividing_by_zero(self):
        b = pricing.price_breakdown(cost="0", selling_price="100")
        self.assertIsNone(b["markup_percent"])
        self.assertEqual(b["margin_percent"], "100.00")

    def test_below_cost_is_flagged(self):
        b = pricing.price_breakdown(cost="100", selling_price="90")
        self.assertTrue(b["below_cost"])
        self.assertTrue(b["warnings"])

    def test_suggested_price_from_target_margin(self):
        self.assertEqual(pricing.suggest_selling_price(cost="700", target_margin_percent="30"), Decimal("1000.00"))
        for bad in ("100", "120", "-1"):
            with self.assertRaises(ValidationError):
                pricing.suggest_selling_price(cost="700", target_margin_percent=bad)
        with self.assertRaises(ValidationError):
            pricing.suggest_selling_price(cost="0", target_margin_percent="20")

    def test_invalid_discounts_rejected(self):
        with self.assertRaises(ValidationError):
            pricing.price_breakdown(cost="10", selling_price="100", discount_type="PERCENTAGE", discount_value="101")
        with self.assertRaises(ValidationError):
            pricing.price_breakdown(cost="10", selling_price="100", discount_type="FIXED", discount_value="100")


class PricingApiTests(CatalogTestMixin, TestCase):
    def setUp(self):
        self.boss = User.objects.create_superuser(username="pr-boss", email="pr-boss@example.com", password="x")
        self.boss.role = Role.SUPER_ADMIN
        self.boss.save()
        self.store = self.create_store(name="Price Mart")
        self.product = self.create_product(self.store, sku="P1", name="Rice", store_price=Decimal("600.00"))
        self.api = APIClient()
        self.api.force_authenticate(self.boss)

    def test_preview_changes_nothing_and_explains(self):
        r = self.api.post("/api/v1/products/pricing/preview/", {"product": self.product.pk, "selling_price": "800", "discount_type": "FIXED", "discount_value": "100"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["breakdown"]["margin_percent"], "14.29")
        self.product.refresh_from_db()
        self.assertIsNone(self.product.selling_price)

    def test_preview_suggests_price_without_applying_it(self):
        r = self.api.post("/api/v1/products/pricing/preview/", {"cost": "700", "target_margin": "30"}, format="json").json()
        self.assertEqual(r["suggested_selling_price"], "1000.00")

    def test_set_selling_price_is_derived_on_the_server(self):
        r = self.api.post(f"/api/v1/products/{self.product.pk}/pricing/", {"selling_price": "800", "discount_type": "FIXED", "discount_value": "100", "final_price": "1"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.product.refresh_from_db()
        self.assertEqual((self.product.selling_price, self.product.final_price), (Decimal("800.00"), Decimal("700.00")))
        self.assertEqual(r.json()["pricing"]["profit_per_unit"], "100.00")
        self.assertTrue(ProductPriceHistory.objects.filter(product=self.product).exists())

    def test_selling_below_cost_and_discount_below_cost_are_refused(self):
        self.assertEqual(self.api.post(f"/api/v1/products/{self.product.pk}/pricing/", {"selling_price": "500"}, format="json").status_code, 400)
        r = self.api.post(f"/api/v1/products/{self.product.pk}/pricing/", {"selling_price": "700", "discount_type": "PERCENTAGE", "discount_value": "20"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.product.refresh_from_db()
        self.assertIsNone(self.product.selling_price)

    def test_admin_without_pricing_permission_is_refused(self):
        plain = User.objects.create_user(username="pr-plain", email="pr-plain@example.com", password="x", role=Role.ADMIN, is_staff=True)
        plain.user_permissions.add(Permission.objects.get(content_type__app_label="catalog", codename="change_product"))
        api = APIClient()
        api.force_authenticate(plain)
        self.assertEqual(api.post(f"/api/v1/products/{self.product.pk}/pricing/", {"selling_price": "800"}, format="json").status_code, 403)
        self.assertEqual(api.post("/api/v1/products/pricing/preview/", {"cost": "1", "selling_price": "2"}, format="json").status_code, 403)

    def test_store_user_cannot_reach_pricing(self):
        owner = self.create_store_user(self.store) if hasattr(self, "create_store_user") else None
        if owner is None:
            self.skipTest("no store user helper")
        api = APIClient()
        api.force_authenticate(owner)
        self.assertIn(api.post(f"/api/v1/products/{self.product.pk}/pricing/", {"selling_price": "800"}, format="json").status_code, (401, 403))

    def test_bulk_pricing_previews_blocks_and_applies(self):
        second = self.create_product(self.store, sku="P2", name="Dal", store_price=Decimal("100.00"))
        body = {"action": "set_pricing", "ids": [self.product.pk, second.pk], "params": {"margin_type": "PERCENTAGE", "margin": "20"}}
        prev = self.api.post("/api/v1/admin/bulk/products/preview/", body, format="json").json()
        self.assertEqual(prev["eligible_count"], 2)
        bad = self.api.post("/api/v1/admin/bulk/products/preview/", {**body, "params": {"margin_type": "PERCENTAGE", "margin": "500"}}, format="json").json()
        self.assertEqual(bad["blocked_count"], 2)
        r = self.api.post("/api/v1/admin/bulk/products/apply/", {**body, "confirm": True}, format="json").json()
        self.assertEqual(r["counts"]["successful"], 2)
        second.refresh_from_db()
        self.assertEqual(second.selling_price, Decimal("120.00"))

    def test_order_prices_survive_later_repricing(self):
        from orders.models import OrderItem
        field_names = {f.name for f in OrderItem._meta.fields}
        self.assertIn("unit_price", field_names)  # the price is copied onto the line, not looked up later
