"""Scheduled offers, needs-information status, store submit, store view of pricing."""
from datetime import timedelta
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Role, User
from catalog.models import Product, ProductStatus
from catalog.services import refresh_offer_price, set_product_pricing
from catalog.tests import CatalogTestMixin


class Base(CatalogTestMixin, TestCase):
    def setUp(self):
        self.boss = User.objects.create_superuser(username="of-boss", email="of-boss@example.com", password="x")
        self.boss.role = Role.SUPER_ADMIN
        self.boss.save()
        self.store = self.create_store(name="Offer Mart")
        self.product = self.create_product(self.store, sku="OF1", name="Tea", store_price=Decimal("80.00"))
        self.api = APIClient()
        self.api.force_authenticate(self.boss)

    def price(self, **kw):
        set_product_pricing(product=self.product, actor=self.boss, selling_price=Decimal("100"), **kw)
        self.product.refresh_from_db()


class ScheduledOfferTests(Base):
    def test_future_offer_does_not_apply_until_it_starts(self):
        start = timezone.now() + timedelta(days=1)
        self.price(discount_type="PERCENTAGE", discount_value=Decimal("10"), discount_starts_at=start)
        self.assertEqual(self.product.final_price, Decimal("100.00"))
        self.assertEqual(self.product.current_final_price, Decimal("100.00"))
        later = start + timedelta(minutes=1)
        self.assertTrue(refresh_offer_price(self.product, now=later))
        self.product.refresh_from_db()
        self.assertEqual(self.product.final_price, Decimal("90.00"))

    def test_offer_ends_and_price_returns_to_regular(self):
        end = timezone.now() + timedelta(hours=2)
        self.price(discount_type="FIXED", discount_value=Decimal("15"), discount_ends_at=end)
        self.assertEqual(self.product.final_price, Decimal("85.00"))
        refresh_offer_price(self.product, now=end + timedelta(seconds=1))
        self.product.refresh_from_db()
        self.assertEqual(self.product.final_price, Decimal("100.00"))
        self.assertTrue(self.product.price_history.filter(reason="Scheduled offer ended").exists())

    def test_invalid_windows_rejected(self):
        now = timezone.now()
        r = self.api.post(f"/api/v1/products/{self.product.pk}/pricing/", {"selling_price": "100", "discount_type": "FIXED", "discount_value": "5",
                          "discount_starts_at": (now + timedelta(days=2)).isoformat(), "discount_ends_at": (now + timedelta(days=1)).isoformat()}, format="json")
        self.assertEqual(r.status_code, 400)
        r = self.api.post(f"/api/v1/products/{self.product.pk}/pricing/", {"selling_price": "100", "discount_type": "FIXED", "discount_value": "5",
                          "discount_ends_at": (now - timedelta(hours=1)).isoformat()}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_api_reports_offer_state(self):
        r = self.api.post(f"/api/v1/products/{self.product.pk}/pricing/", {"selling_price": "100", "discount_type": "FIXED", "discount_value": "5",
                          "discount_starts_at": (timezone.now() + timedelta(days=1)).isoformat()}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["offer_state"], "scheduled")

    def test_command_refreshes_due_offers(self):
        self.price(discount_type="FIXED", discount_value=Decimal("10"), discount_ends_at=timezone.now() + timedelta(seconds=1))
        Product.objects.filter(pk=self.product.pk).update(discount_ends_at=timezone.now() - timedelta(seconds=1))
        call_command("refresh_offer_prices", verbosity=0)
        self.product.refresh_from_db()
        self.assertEqual(self.product.final_price, Decimal("100.00"))

    def test_checkout_uses_current_offer_price(self):
        """Checkout corrects a stale stored price before charging."""
        from orders.checkout import _build_validated_lines
        self.price(discount_type="FIXED", discount_value=Decimal("10"), discount_ends_at=timezone.now() + timedelta(hours=1))
        Product.objects.filter(pk=self.product.pk).update(discount_ends_at=timezone.now() - timedelta(seconds=1))  # offer over, stored price stale (90)
        p = Product.objects.get(pk=self.product.pk)
        p.status, p.stock_quantity = ProductStatus.APPROVED, Decimal("5")

        class Item:  # minimal stand-in for a CartItem
            product_id, quantity = p.pk, Decimal("1")
            product = p
        lines = _build_validated_lines([Item()], {p.pk: p})
        self.assertEqual(lines[0]["unit_price"], Decimal("100.00"))
        p.refresh_from_db()
        self.assertEqual(p.final_price, Decimal("100.00"))  # stored price corrected too


class NeedsInfoTests(Base):
    def setUp(self):
        super().setUp()
        Product.objects.filter(pk=self.product.pk).update(status=ProductStatus.PENDING)

    def test_request_info_needs_a_note_and_store_can_resubmit(self):
        body = {"action": "request_info", "ids": [self.product.pk]}
        self.assertEqual(self.api.post("/api/v1/admin/bulk/products/apply/", {**body, "confirm": True}, format="json").status_code, 400)
        r = self.api.post("/api/v1/admin/bulk/products/apply/", {**body, "confirm": True, "reason": "Add the pack size"}, format="json").json()
        self.assertEqual(r["counts"]["successful"], 1)
        self.product.refresh_from_db()
        self.assertEqual((self.product.status, self.product.rejection_reason), (ProductStatus.NEEDS_INFO, "Add the pack size"))
        owner = self.create_store_user(self.store, username="of-owner")
        store_api = APIClient()
        store_api.force_authenticate(owner)
        r = store_api.post(f"/api/v1/store/products/{self.product.pk}/submit/")
        self.assertEqual(r.status_code, 200, r.content)
        self.product.refresh_from_db()
        self.assertEqual(self.product.status, ProductStatus.PENDING)

    def test_needs_info_product_is_never_public(self):
        from catalog.status import product_is_publicly_available
        Product.objects.filter(pk=self.product.pk).update(status=ProductStatus.NEEDS_INFO, is_active=True)
        self.product.refresh_from_db()
        self.assertFalse(product_is_publicly_available(self.product))

    def test_store_cannot_submit_approved_or_other_stores_products(self):
        owner = self.create_store_user(self.store, username="of-owner2")
        other = self.create_product(self.create_store(name="Else"), sku="X1", name="Other")
        api = APIClient()
        api.force_authenticate(owner)
        self.assertEqual(api.post(f"/api/v1/store/products/{other.pk}/submit/").status_code, 404)
        Product.objects.filter(pk=self.product.pk).update(status=ProductStatus.APPROVED)
        self.assertEqual(api.post(f"/api/v1/store/products/{self.product.pk}/submit/").status_code, 400)


class StoreViewTests(Base):
    def test_store_owner_never_sees_margin_or_profit(self):
        self.price()
        owner = self.create_store_user(self.store, username="of-owner3")
        api = APIClient()
        api.force_authenticate(owner)
        data = api.get(f"/api/v1/store/products/{self.product.pk}/").json()
        for key in ("profit_margin", "profit_margin_type", "pricing"):
            self.assertNotIn(key, data)
        self.assertIn("final_price", data)
        self.assertIsNotNone(self.api.get(f"/api/v1/products/{self.product.pk}/").json()["pricing"])


class CreateFlowTests(Base):
    def create_body(self, **extra):
        cat = self.create_product_category(name="Flow cat")
        return {"store": self.store.pk, "name": "Flow Rice", "sku": "FLOW1", "category": cat.pk, "unit": "KG", "unit_value": "1",
                "store_price": "50", "save_as_draft": True, **extra}

    def test_opening_stock_is_recorded_with_the_product(self):
        r = self.api.post("/api/v1/products/", self.create_body(opening_stock="12"), format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(Decimal(r.json()["stock_quantity"]), Decimal("12"))

    def test_bad_opening_stock_creates_nothing(self):
        before = Product.objects.count()
        self.assertEqual(self.api.post("/api/v1/products/", self.create_body(opening_stock="-3"), format="json").status_code, 400)
        self.assertEqual(Product.objects.count(), before)

    def test_opening_stock_needs_inventory_permission(self):
        from django.contrib.auth.models import Permission
        plain = User.objects.create_user(username="of-add", email="of-add@example.com", password="x", role=Role.ADMIN, is_staff=True)
        plain.user_permissions.add(Permission.objects.get(content_type__app_label="catalog", codename="add_product"))
        api = APIClient()
        api.force_authenticate(plain)
        self.assertEqual(api.post("/api/v1/products/", self.create_body(opening_stock="5"), format="json").status_code, 403)
        self.assertEqual(api.post("/api/v1/products/", self.create_body(), format="json").status_code, 201)

    def test_status_endpoint_submits_and_blocks_incomplete_approval(self):
        pid = self.api.post("/api/v1/products/", self.create_body(), format="json").json()["id"]
        r = self.api.post(f"/api/v1/products/{pid}/status/", {"status": "PENDING"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIn("APPROVED", r.json()["next_statuses"])
        r = self.api.post(f"/api/v1/products/{pid}/status/", {"status": "APPROVED"}, format="json")
        self.assertEqual(r.status_code, 400)  # no price, no image
        self.assertEqual(self.api.post(f"/api/v1/products/{pid}/status/", {"status": "NEEDS_INFO"}, format="json").status_code, 400)  # note required
        self.assertEqual(self.api.post(f"/api/v1/products/{pid}/status/", {"status": "NEEDS_INFO", "reason": "Add a photo"}, format="json").status_code, 200)

    def test_status_endpoint_respects_approve_permission(self):
        from django.contrib.auth.models import Permission
        Product.objects.filter(pk=self.product.pk).update(status=ProductStatus.PENDING)
        plain = User.objects.create_user(username="of-view", email="of-view@example.com", password="x", role=Role.ADMIN, is_staff=True)
        plain.user_permissions.add(Permission.objects.get(content_type__app_label="catalog", codename="view_product"))
        api = APIClient()
        api.force_authenticate(plain)
        self.assertEqual(api.post(f"/api/v1/products/{self.product.pk}/status/", {"status": "REJECTED", "reason": "x"}, format="json").status_code, 403)
