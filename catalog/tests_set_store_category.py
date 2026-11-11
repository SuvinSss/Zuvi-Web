from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from accounts.models import AdminAuditLog, Role
from .models import Product, ProductCategory, ProductStatus
from .tests import CatalogTestMixin

User = get_user_model()


class SetStoreProductCategoryTests(CatalogTestMixin, TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="cat-admin",
            email="cat-admin@example.com",
            password="secure-password-123",
            role=Role.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        self.store = self.create_store(name="Zuuvi Grocery")
        self.other_store = self.create_store(name="Other Mart")
        self.rice = self.create_product_category(name="Rice")
        self.oil = self.create_product_category(name="Oil")
        self.p1 = self.create_product(store=self.store, category=self.rice, status=ProductStatus.APPROVED)
        self.p2 = self.create_product(store=self.store, category=self.oil)
        self.other = self.create_product(store=self.other_store, category=self.rice)

    def run_command(self, *extra, store="zuuvi grocery", actor=None):
        out = StringIO()
        call_command(
            "set_store_product_category",
            "--store", store,
            "--category", "Grocery",
            "--actor", str((actor or self.admin).pk),
            *extra,
            stdout=out,
        )
        return out.getvalue()

    def test_dry_run_changes_nothing(self):
        output = self.run_command()
        self.assertIn('"to_move": 2', output)
        self.assertFalse(ProductCategory.objects.filter(name="Grocery").exists())
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.category, self.rice)
        self.assertFalse(AdminAuditLog.objects.exists())

    def test_apply_creates_category_and_moves_only_this_store(self):
        self.run_command("--apply")
        grocery = ProductCategory.objects.get(name="Grocery", parent=None)
        self.assertEqual(
            set(Product.objects.filter(store=self.store).values_list("category", flat=True)),
            {grocery.pk},
        )
        self.other.refresh_from_db()
        self.assertEqual(self.other.category, self.rice)
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.status, ProductStatus.APPROVED)
        self.assertEqual(self.p1.store_price, Decimal("100.00"))
        log = AdminAuditLog.objects.get()
        self.assertEqual(log.action, AdminAuditLog.Action.PRODUCT_UPDATED)
        self.assertEqual(
            log.metadata["previous_category_by_product"],
            {str(self.p1.pk): self.rice.pk, str(self.p2.pk): self.oil.pk},
        )

    def test_existing_category_reused_and_rerun_is_noop(self):
        grocery = self.create_product_category(name="grocery")
        self.run_command("--apply")
        self.assertEqual(ProductCategory.objects.filter(name__iexact="grocery").count(), 1)
        self.p2.refresh_from_db()
        self.assertEqual(self.p2.category, grocery)
        output = self.run_command("--apply")
        self.assertIn('"moved": 0', output)
        self.assertEqual(AdminAuditLog.objects.count(), 1)

    def test_unknown_store_rejected(self):
        with self.assertRaises(CommandError):
            self.run_command(store="Missing Store")

    def test_actor_without_permission_rejected(self):
        store_user = self.create_store_user(self.store)
        with self.assertRaises(PermissionDenied):
            self.run_command("--apply", actor=store_user)
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.category, self.rice)


class MoveZuuviGroceryMigrationTests(CatalogTestMixin, TestCase):
    """The 0014 data migration, run against the real (current) models."""

    def setUp(self):
        from importlib import import_module

        self.forward = import_module(
            "catalog.migrations.0014_move_zuuvi_grocery_products_to_grocery"
        ).forward
        self.admin = User.objects.create_user(
            username="mig-admin",
            email="mig-admin@example.com",
            password="secure-password-123",
            role=Role.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        self.rice = self.create_product_category(name="Appam / Idiyappam Podi")
        self.other_store = self.create_store(name="Other Mart")
        self.other = self.create_product(store=self.other_store, category=self.rice)

    def run_forward(self):
        from django.apps import apps

        self.forward(apps, None)

    def test_moves_only_zuuvi_grocery_products_and_keeps_status(self):
        store = self.create_store(name="ZuuVi Grocery")
        product = self.create_product(store=store, category=self.rice, status=ProductStatus.APPROVED)
        self.run_forward()
        grocery = ProductCategory.objects.get(name="Grocery", parent=None)
        self.assertTrue(grocery.slug)
        product.refresh_from_db()
        self.assertEqual(product.category, grocery)
        self.assertEqual(product.status, ProductStatus.APPROVED)
        self.assertEqual(product.store_price, Decimal("100.00"))
        self.other.refresh_from_db()
        self.assertEqual(self.other.category, self.rice)
        log = AdminAuditLog.objects.get()
        self.assertEqual(log.actor, self.admin)
        self.assertEqual(log.metadata["previous_category_by_product"], {str(product.pk): self.rice.pk})
        self.run_forward()
        self.assertEqual(AdminAuditLog.objects.count(), 1)

    def test_reuses_existing_grocery_category(self):
        grocery = self.create_product_category(name="Grocery")
        store = self.create_store(name="Zuuvi Grocery")
        product = self.create_product(store=store, category=self.rice)
        self.run_forward()
        product.refresh_from_db()
        self.assertEqual(product.category, grocery)
        self.assertEqual(ProductCategory.objects.filter(name__iexact="grocery").count(), 1)

    def test_no_store_changes_nothing(self):
        self.run_forward()
        self.assertFalse(ProductCategory.objects.filter(name="Grocery").exists())
        self.assertFalse(AdminAuditLog.objects.exists())
