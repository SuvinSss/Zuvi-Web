"""Approval Center and bulk actions: eligibility preview, confirmed apply, partial success, permissions."""
from django.contrib.auth.models import Permission
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import Role, User
from catalog.models import Product, ProductStatus
from catalog.tests import CatalogTestMixin
from core.models import AuditEvent
from deliveries.models import DeliveryPartner, PartnerStatus
from stores.models import Store, StoreStatus


class BulkBase(CatalogTestMixin, TestCase):
    def setUp(self):
        self.boss = User.objects.create_superuser(username="bk-boss", email="bk-boss@example.com", password="x")
        self.boss.role = Role.SUPER_ADMIN
        self.boss.save()
        self.plain = User.objects.create_user(username="bk-plain", email="bk-plain@example.com", password="x", role=Role.ADMIN, is_staff=True)
        self.store = self.create_store(name="Bulk Mart")
        self.api = APIClient()
        self.api.force_authenticate(self.boss)

    def good(self, n):
        product = self.create_product(self.store, sku=f"G{n}", name=f"Good {n}")
        return self.prepare_product_for_approval(product, priced_by=self.boss)

    def preview(self, module, **body):
        return self.api.post(f"/api/v1/admin/bulk/{module}/preview/", body, format="json")

    def apply(self, module, **body):
        return self.api.post(f"/api/v1/admin/bulk/{module}/apply/", body, format="json")


class ProductBulkTests(BulkBase):
    def test_preview_separates_eligible_from_blocked_with_reasons_and_changes_nothing(self):
        ok = self.good(1)
        bare = self.create_product(self.store, sku="BARE", name="No price or image")
        r = self.preview("products", action="approve", ids=[ok.pk, bare.pk]).json()
        self.assertEqual((r["total"], r["eligible_count"], r["blocked_count"]), (2, 1, 1))
        blocked = r["blocked"][0]
        self.assertEqual(blocked["id"], bare.pk)
        self.assertTrue(any("pricing" in m.lower() for m in blocked["reasons"]))
        self.assertTrue(any("image" in m.lower() for m in blocked["reasons"]))
        ok.refresh_from_db()
        self.assertEqual(ok.status, ProductStatus.PENDING)

    def test_apply_reports_successful_skipped_and_failed_separately(self):
        ok1, ok2 = self.good(1), self.good(2)
        bare = self.create_product(self.store, sku="BARE", name="Bare")
        r = self.apply("products", action="approve", ids=[ok1.pk, ok2.pk, bare.pk], confirm=True)
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertEqual(body["counts"], {"successful": 2, "skipped": 1, "failed": 0})
        self.assertEqual(body["skipped"][0]["id"], bare.pk)
        ok1.refresh_from_db(); bare.refresh_from_db()
        self.assertEqual(ok1.status, ProductStatus.APPROVED)
        self.assertEqual(ok1.approved_by, self.boss)
        self.assertEqual(bare.status, ProductStatus.PENDING)
        self.assertTrue(AuditEvent.objects.filter(action="bulk.products.approve").exists())

    def test_apply_requires_explicit_confirmation(self):
        ok = self.good(1)
        self.assertEqual(self.apply("products", action="approve", ids=[ok.pk]).status_code, 400)
        ok.refresh_from_db()
        self.assertEqual(ok.status, ProductStatus.PENDING)

    def test_reject_needs_reason_and_pending_products_are_not_public(self):
        ok = self.good(1)
        self.assertEqual(self.apply("products", action="reject", ids=[ok.pk], confirm=True).status_code, 400)
        r = self.apply("products", action="reject", ids=[ok.pk], confirm=True, reason="Wrong category")
        self.assertEqual(r.json()["counts"]["successful"], 1)
        ok.refresh_from_db()
        self.assertEqual((ok.status, ok.rejection_reason), (ProductStatus.REJECTED, "Wrong category"))
        self.assertEqual(APIClient().get("/api/v1/public/products/").json()["count"], 0)

    def test_state_changes_between_preview_and_apply_are_rechecked(self):
        ok = self.good(1)
        self.assertEqual(self.preview("products", action="approve", ids=[ok.pk]).json()["eligible_count"], 1)
        ok.images.all().delete()  # someone removes the image after the preview
        r = self.apply("products", action="approve", ids=[ok.pk], confirm=True).json()
        self.assertEqual(r["counts"], {"successful": 0, "skipped": 1, "failed": 0})

    def test_inactive_store_blocks_approval(self):
        ok = self.good(1)
        Store.objects.filter(pk=self.store.pk).update(status=StoreStatus.SUSPENDED)
        r = self.preview("products", action="approve", ids=[ok.pk]).json()
        self.assertEqual(r["blocked_count"], 1)
        self.assertTrue(any("ACTIVE" in m for m in r["blocked"][0]["reasons"]))

    def test_select_all_across_pages_requires_matching_count(self):
        for n in range(25):  # more than one page of 20
            self.good(n)
        self.create_product(self.store, sku="OTHER", name="Other", status=ProductStatus.DRAFT)
        body = dict(action="approve", select_all=True, filters={"status": "PENDING"})
        p = self.preview("products", **body).json()
        self.assertEqual((p["total"], p["eligible_count"]), (25, 25))
        stale = self.apply("products", **body, confirm=True, expected_count=24)
        self.assertEqual(stale.status_code, 400)
        self.assertEqual(Product.objects.filter(status=ProductStatus.APPROVED).count(), 0)
        done = self.apply("products", **body, confirm=True, expected_count=25).json()
        self.assertEqual(done["counts"]["successful"], 25)
        self.assertEqual(Product.objects.get(sku="OTHER").status, ProductStatus.DRAFT)  # filter respected

    def test_generated_fields_are_flagged_in_the_preview(self):
        ok = self.good(1)
        Product.objects.filter(pk=ok.pk).update(generated_fields=["sku"])
        r = self.preview("products", action="approve", ids=[ok.pk]).json()
        self.assertEqual(r["warning_count"], 1)
        self.assertIn("sku", r["eligible"][0]["warnings"][0])

    def test_permission_and_input_hardening(self):
        ok = self.good(1)
        self.api.force_authenticate(self.plain)  # admin without catalog.approve_product
        r = self.preview("products", action="approve", ids=[ok.pk]).json()
        self.assertEqual((r["eligible_count"], r["blocked_count"]), (0, 1))
        self.assertEqual(self.apply("products", action="approve", ids=[ok.pk], confirm=True).json()["counts"]["successful"], 0)
        self.plain.user_permissions.add(Permission.objects.get(codename="approve_product"))
        self.api = APIClient(); self.api.force_authenticate(User.objects.get(pk=self.plain.pk))
        self.assertEqual(self.apply("products", action="approve", ids=[ok.pk], confirm=True).json()["counts"]["successful"], 1)
        for who in (self.create_store_user(self.store),):
            self.api.force_authenticate(who)
            self.assertEqual(self.preview("products", action="approve", ids=[ok.pk]).status_code, 403)
        self.api.force_authenticate(self.boss)
        self.assertEqual(self.preview("nope", action="approve", ids=[1]).status_code, 400)
        self.assertEqual(self.preview("products", action="delete", ids=[1]).status_code, 400)
        self.assertEqual(self.preview("products", action="approve", ids=[]).status_code, 400)
        self.assertEqual(self.preview("products", action="approve", ids=list(range(1, 600))).status_code, 400)
        self.assertEqual(self.preview("products", action="approve", ids=[999999]).json()["total"], 0)


class StoreAndPartnerBulkTests(BulkBase):
    def test_store_bulk_approve_blocks_incomplete_wizard_stores_and_reject_needs_reason(self):
        pending = self.create_store(name="P1", status=StoreStatus.PENDING)
        suspended = self.create_store(name="S1", status=StoreStatus.SUSPENDED)
        r = self.apply("stores", action="approve", ids=[pending.pk, suspended.pk], confirm=True).json()
        self.assertEqual(r["counts"]["successful"], 2)  # pending -> active, suspended -> active (reactivation)
        pending.refresh_from_db()
        self.assertEqual((pending.status, pending.approved_by), (StoreStatus.ACTIVE, self.boss))
        other = self.create_store(name="P2", status=StoreStatus.PENDING)
        self.assertEqual(self.apply("stores", action="reject", ids=[other.pk], confirm=True).status_code, 400)
        r = self.apply("stores", action="reject", ids=[other.pk], confirm=True, reason="Incomplete application").json()
        self.assertEqual(r["counts"]["successful"], 1)

    def test_active_store_cannot_be_rejected_in_bulk(self):
        r = self.preview("stores", action="reject", ids=[self.store.pk], reason="x").json()
        self.assertEqual(r["blocked_count"], 1)

    def test_partner_bulk_uses_the_same_rules_as_single_decisions(self):
        a = DeliveryPartner.objects.create(user=User.objects.create_user("pa", "pa@example.com", "x", role=Role.DELIVERY_AGENT), status=PartnerStatus.PENDING, vehicle_type="SCOOTER")
        b = DeliveryPartner.objects.create(user=User.objects.create_user("pb", "pb@example.com", "x", role=Role.DELIVERY_AGENT), status=PartnerStatus.REJECTED, vehicle_type="SCOOTER")
        r = self.apply("partners", action="approve", ids=[a.pk, b.pk], confirm=True).json()
        self.assertEqual(r["counts"], {"successful": 1, "skipped": 1, "failed": 0})
        a.refresh_from_db()
        self.assertEqual(a.status, PartnerStatus.APPROVED)


class ApprovalCenterTests(BulkBase):
    def test_queues_count_what_needs_a_decision(self):
        self.good(1)
        self.create_store(name="Wait", status=StoreStatus.PENDING)
        self.create_store(name="Info", status=StoreStatus.NEEDS_INFO)
        data = self.api.get("/api/v1/admin/approvals/").json()
        counts = {q["key"]: q["count"] for q in data["queues"]}
        self.assertEqual((counts["products"], counts["stores_pending"], counts["stores_info"]), (1, 1, 1))
        self.assertEqual(data["total"], sum(counts.values()))
        self.assertTrue(data["not_available"])
        self.api.force_authenticate(self.create_store_user(self.store, username="sx"))
        self.assertEqual(self.api.get("/api/v1/admin/approvals/").status_code, 403)
