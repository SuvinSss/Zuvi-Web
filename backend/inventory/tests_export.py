import csv
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import Role
from catalog.models import Product, ProductCategory, ProductStatus, ProductUnit
from locations.models import Address
from stores.models import Store, StoreCategory, StoreStatus, StoreType, StoreUser

from .export import EXPORT_HEADERS, csv_safe_text
from .services import record_manual_stock_in

User = get_user_model()


class InventoryExportTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.category = ProductCategory.objects.create(name="Export Cat")
        self.store_a = self._store("Export Store A")
        self.store_b = self._store("Export Store B")
        self.product_a = self._product(
            self.store_a,
            sku="EXP-A",
            name="=SUM(A1:A2)",
            stock=Decimal("10.000"),
        )
        self.product_a_low = self._product(
            self.store_a,
            sku="EXP-A-LOW",
            name="Low Stock Juice",
            stock=Decimal("1.000"),
            threshold=Decimal("5.000"),
        )
        self.product_b = self._product(
            self.store_b,
            sku="EXP-B",
            name="+CMD|calc",
            stock=Decimal("8.000"),
        )
        self.actor = User.objects.create_user(
            username="export-actor",
            email="export-actor@example.com",
            password="secure-password-123",
            role=Role.ADMIN,
            is_staff=True,
        )
        record_manual_stock_in(
            product=self.product_a,
            store=self.store_a,
            quantity=Decimal("1.000"),
            actor=self.actor,
        )

        self.super_admin = User.objects.create_superuser(
            username="export-super",
            email="export-super@example.com",
            password="secure-password-123",
            role=Role.SUPER_ADMIN,
        )
        self.admin = User.objects.create_user(
            username="export-admin",
            email="export-admin@example.com",
            password="secure-password-123",
            role=Role.ADMIN,
            is_staff=True,
        )
        self.store_user_a = User.objects.create_user(
            username="export-store-a",
            email="export-store-a@example.com",
            password="secure-password-123",
            role=Role.STORE_USER,
        )
        StoreUser.objects.create(
            store=self.store_a,
            user=self.store_user_a,
            is_primary=True,
            is_active=True,
            can_manage_inventory=True,
        )
        self.store_user_b = User.objects.create_user(
            username="export-store-b",
            email="export-store-b@example.com",
            password="secure-password-123",
            role=Role.STORE_USER,
        )
        StoreUser.objects.create(
            store=self.store_b,
            user=self.store_user_b,
            is_primary=True,
            is_active=True,
            can_manage_inventory=True,
        )


    def _store(self, name):
        return Store.objects.create(
            name=name,
            store_type=StoreType.OWN_STORE,
            status=StoreStatus.ACTIVE,
            is_active=True,
            commission_percentage=Decimal("5.00"),
            address=Address.objects.create(
                line1=f"{name} Rd",
                city="Bengaluru",
                state="Karnataka",
                postal_code="560001",
                latitude=Decimal("12.971600"),
                longitude=Decimal("77.594600"),
            ),
            category=StoreCategory.objects.create(name=f"Cat-{name}"),
        )

    def _product(self, store, *, sku, name, stock, threshold=Decimal("2.000")):
        product = Product(
            store=store,
            name=name,
            sku=sku,
            category=self.category,
            store_price=Decimal("20.00"),
            status=ProductStatus.APPROVED,
            stock_quantity=stock,
            low_stock_threshold=threshold,
            unit=ProductUnit.PIECE,
        )
        product.full_clean()
        product.save()
        return product

    def _grant(self, user, *codenames):
        for codename in codenames:
            permission = Permission.objects.get(
                codename=codename,
                content_type__app_label="inventory",
            )
            user.user_permissions.add(permission)

    def _parse_csv(self, response):
        content = response.content.decode("utf-8")
        rows = list(csv.reader(StringIO(content)))
        return rows[0], rows[1:]

    def test_csv_safe_text_neutralizes_formula_prefixes(self):
        self.assertEqual(csv_safe_text("=1+1"), "'=1+1")
        self.assertEqual(csv_safe_text("+cmd"), "'+cmd")
        self.assertEqual(csv_safe_text("-1+1"), "'-1+1")
        self.assertEqual(csv_safe_text("@SUM"), "'@SUM")
        self.assertEqual(csv_safe_text("Normal"), "Normal")
        self.assertEqual(csv_safe_text(None), "")










