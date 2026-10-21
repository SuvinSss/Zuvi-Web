from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role
from catalog.models import Product, ProductCategory, ProductStatus
from locations.models import Address
from stores.models import Store, StoreCategory, StoreStatus, StoreType, StoreUser

from .models import InventoryTransaction
from .services import record_expired_stock
from .status import (
    EXPIRING_SOON_DAYS,
    get_inventory_dashboard_stats,
    get_store_inventory_dashboard_stats,
    is_product_expired,
    is_product_expiring_soon,
    stock_status_for_product,
)

User = get_user_model()


class InventoryStatusHelperTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        address = Address.objects.create(
            line1="Status Road",
            city="Bengaluru",
            state="Karnataka",
            postal_code="560001",
            latitude=Decimal("12.971600"),
            longitude=Decimal("77.594600"),
        )
        self.store = Store.objects.create(
            name="Status Store",
            store_type=StoreType.OWN_STORE,
            status=StoreStatus.ACTIVE,
            is_active=True,
            commission_percentage=Decimal("5.00"),
            address=address,
            category=StoreCategory.objects.create(name="Status Cat"),
        )
        self.category = ProductCategory.objects.create(name="Status Goods")
        self.actor = User.objects.create_user(
            username="status-actor",
            email="status-actor@example.com",
            password="secure-password-123",
            role=Role.ADMIN,
            is_staff=True,
        )

    def _product(self, sku, stock, threshold=Decimal("0"), **extra):
        return Product.objects.create(
            store=self.store,
            name=f"Product {sku}",
            sku=sku,
            category=self.category,
            store_price=Decimal("10.00"),
            status=ProductStatus.APPROVED,
            stock_quantity=stock,
            low_stock_threshold=threshold,
            **extra,
        )

    def test_stock_status_labels(self):
        self.assertEqual(
            stock_status_for_product(
                self._product("OUT", Decimal("0"), Decimal("2"))
            ),
            "Out of stock",
        )
        self.assertEqual(
            stock_status_for_product(
                self._product("LOW", Decimal("2"), Decimal("5"))
            ),
            "Low stock",
        )
        self.assertEqual(
            stock_status_for_product(
                self._product("IN", Decimal("10"), Decimal("2"))
            ),
            "In stock",
        )

    def test_expiry_helpers_use_localdate_and_do_not_touch_stock(self):
        expired = self._product(
            "EXP",
            Decimal("8.000"),
            expiry_date=self.today - timedelta(days=1),
        )
        soon = self._product(
            "SOON",
            Decimal("8.000"),
            expiry_date=self.today + timedelta(days=10),
        )
        later = self._product(
            "LATER",
            Decimal("8.000"),
            expiry_date=self.today + timedelta(days=EXPIRING_SOON_DAYS + 1),
        )
        self.assertTrue(is_product_expired(expired, today=self.today))
        self.assertFalse(is_product_expiring_soon(expired, today=self.today))
        self.assertTrue(is_product_expiring_soon(soon, today=self.today))
        self.assertFalse(is_product_expired(soon, today=self.today))
        self.assertFalse(is_product_expiring_soon(later, today=self.today))

        expired.refresh_from_db()
        self.assertEqual(expired.stock_quantity, Decimal("8.000"))
        self.assertEqual(InventoryTransaction.objects.count(), 0)

    def test_dashboard_counts_single_aggregate_query(self):
        self._product("IN1", Decimal("10"), Decimal("2"))
        self._product("LOW1", Decimal("1"), Decimal("3"))
        self._product("OUT1", Decimal("0"), Decimal("2"))
        self._product(
            "EXPIRED1",
            Decimal("4"),
            Decimal("1"),
            expiry_date=self.today - timedelta(days=2),
        )
        self._product(
            "SOON1",
            Decimal("4"),
            Decimal("1"),
            expiry_date=self.today + timedelta(days=5),
        )
        self._product(
            "FAR1",
            Decimal("4"),
            Decimal("1"),
            expiry_date=self.today + timedelta(days=60),
        )

        with CaptureQueriesContext(connection) as ctx:
            stats = get_inventory_dashboard_stats()
        self.assertEqual(len(ctx.captured_queries), 1)
        self.assertEqual(stats["total"], 6)
        self.assertEqual(stats["in_stock"], 4)  # IN1, EXPIRED1, SOON1, FAR1
        self.assertEqual(stats["low_stock"], 1)
        self.assertEqual(stats["out_of_stock"], 1)
        self.assertEqual(stats["expired"], 1)
        self.assertEqual(stats["expiring_soon"], 1)

    def test_expired_date_does_not_auto_reduce_stock_until_explicit_record(self):
        product = self._product(
            "KEEP",
            Decimal("5.000"),
            expiry_date=self.today - timedelta(days=3),
        )
        stats = get_inventory_dashboard_stats(store=self.store)
        self.assertEqual(stats["expired"], 1)
        product.refresh_from_db()
        self.assertEqual(product.stock_quantity, Decimal("5.000"))

        record_expired_stock(
            product=product,
            store=self.store,
            quantity=Decimal("2.000"),
            actor=self.actor,
            reason="Past dated batch removed",
            expiry_date=product.expiry_date,
        )
        product.refresh_from_db()
        self.assertEqual(product.stock_quantity, Decimal("3.000"))
        self.assertEqual(
            InventoryTransaction.objects.filter(
                product=product,
                transaction_type="EXPIRED",
            ).count(),
            1,
        )


class InventoryDashboardIsolationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.today = timezone.localdate()

        def make_store(name):
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

        self.store_a = make_store("Inv Dash A")
        self.store_b = make_store("Inv Dash B")
        category = ProductCategory.objects.create(name="Inv Dash Goods")

        def make_product(store, sku, stock, threshold, **extra):
            return Product.objects.create(
                store=store,
                name=f"P {sku}",
                sku=sku,
                category=category,
                store_price=Decimal("10.00"),
                status=ProductStatus.APPROVED,
                stock_quantity=stock,
                low_stock_threshold=threshold,
                **extra,
            )

        # Store A: in-stock, low, out, expired, expiring
        make_product(self.store_a, "A-IN", Decimal("10"), Decimal("2"))
        make_product(self.store_a, "A-LOW", Decimal("1"), Decimal("3"))
        make_product(self.store_a, "A-OUT", Decimal("0"), Decimal("1"))
        make_product(
            self.store_a,
            "A-EXP",
            Decimal("2"),
            Decimal("1"),
            expiry_date=self.today - timedelta(days=1),
        )
        make_product(
            self.store_a,
            "A-SOON",
            Decimal("2"),
            Decimal("1"),
            expiry_date=self.today + timedelta(days=7),
        )
        # Store B noise
        make_product(self.store_b, "B-IN", Decimal("20"), Decimal("1"))
        make_product(
            self.store_b,
            "B-EXP",
            Decimal("5"),
            Decimal("1"),
            expiry_date=self.today - timedelta(days=5),
        )
        make_product(
            self.store_b,
            "B-SOON",
            Decimal("5"),
            Decimal("1"),
            expiry_date=self.today + timedelta(days=3),
        )

        self.user_a = User.objects.create_user(
            username="inv-dash-a",
            email="inv-dash-a@example.com",
            password="secure-password-123",
            role=Role.STORE_USER,
        )
        StoreUser.objects.create(
            store=self.store_a,
            user=self.user_a,
            is_primary=True,
            is_active=True,
            can_manage_inventory=True,
            designation="Manager",
        )
        self.user_b = User.objects.create_user(
            username="inv-dash-b",
            email="inv-dash-b@example.com",
            password="secure-password-123",
            role=Role.STORE_USER,
        )
        StoreUser.objects.create(
            store=self.store_b,
            user=self.user_b,
            is_primary=True,
            is_active=True,
            can_manage_inventory=True,
            designation="Manager",
        )
        self.dashboard_url = reverse("stores:store_portal_dashboard")

    def test_store_stats_are_isolated(self):
        with CaptureQueriesContext(connection) as ctx:
            stats_a = get_store_inventory_dashboard_stats(self.store_a)
        self.assertEqual(len(ctx.captured_queries), 1)
        self.assertEqual(stats_a["total"], 5)
        self.assertEqual(stats_a["in_stock"], 3)  # A-IN, A-EXP, A-SOON
        self.assertEqual(stats_a["low_stock"], 1)
        self.assertEqual(stats_a["out_of_stock"], 1)
        self.assertEqual(stats_a["expired"], 1)
        self.assertEqual(stats_a["expiring_soon"], 1)

        stats_b = get_store_inventory_dashboard_stats(self.store_b)
        self.assertEqual(stats_b["total"], 3)
        self.assertEqual(stats_b["in_stock"], 3)
        self.assertEqual(stats_b["low_stock"], 0)
        self.assertEqual(stats_b["out_of_stock"], 0)
        self.assertEqual(stats_b["expired"], 1)
        self.assertEqual(stats_b["expiring_soon"], 1)

    def test_store_dashboard_renders_only_own_inventory_counts(self):
        self.client.login(username="inv-dash-a", password="secure-password-123")
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)
        stats = response.context["inventory_stats"]
        self.assertEqual(stats["total"], 5)
        self.assertEqual(stats["expired"], 1)
        self.assertContains(response, "<strong>Total inventory Products:</strong> 5")
        self.assertContains(response, "<strong>In-stock Products:</strong> 3")
        self.assertContains(response, "<strong>Low-stock Products:</strong> 1")
        self.assertContains(response, "<strong>Out-of-stock Products:</strong> 1")
        self.assertContains(response, "<strong>Expired Products:</strong> 1")
        self.assertContains(
            response, "<strong>Products expiring within 30 days:</strong> 1"
        )
        self.assertContains(response, "Open Inventory")

        self.client.login(username="inv-dash-b", password="secure-password-123")
        response_b = self.client.get(self.dashboard_url)
        self.assertEqual(response_b.context["inventory_stats"]["total"], 3)
        self.assertContains(
            response_b, "<strong>Total inventory Products:</strong> 3"
        )


class ManagementInventoryDashboardTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.today = timezone.localdate()
        self.super_admin = User.objects.create_superuser(
            username="inv-dash-super",
            email="inv-dash-super@example.com",
            password="secure-password-123",
            role=Role.SUPER_ADMIN,
        )

        store = Store.objects.create(
            name="Mgmt Inv Dash",
            store_type=StoreType.OWN_STORE,
            status=StoreStatus.ACTIVE,
            is_active=True,
            commission_percentage=Decimal("5.00"),
            address=Address.objects.create(
                line1="Mgmt Rd",
                city="Bengaluru",
                state="Karnataka",
                postal_code="560001",
                latitude=Decimal("12.971600"),
                longitude=Decimal("77.594600"),
            ),
            category=StoreCategory.objects.create(name="Mgmt Inv Cat"),
        )
        category = ProductCategory.objects.create(name="Mgmt Inv Goods")
        Product.objects.create(
            store=store,
            name="Dash In",
            sku="MGMT-IN",
            category=category,
            store_price=Decimal("10.00"),
            status=ProductStatus.APPROVED,
            stock_quantity=Decimal("10"),
            low_stock_threshold=Decimal("2"),
        )
        Product.objects.create(
            store=store,
            name="Dash Out",
            sku="MGMT-OUT",
            category=category,
            store_price=Decimal("10.00"),
            status=ProductStatus.APPROVED,
            stock_quantity=Decimal("0"),
            low_stock_threshold=Decimal("2"),
        )
        Product.objects.create(
            store=store,
            name="Dash Expired",
            sku="MGMT-EXP",
            category=category,
            store_price=Decimal("10.00"),
            status=ProductStatus.APPROVED,
            stock_quantity=Decimal("3"),
            low_stock_threshold=Decimal("1"),
            expiry_date=self.today - timedelta(days=1),
        )
        self.dashboard_url = reverse("accounts:management_dashboard")

    def test_management_dashboard_shows_inventory_counts(self):
        self.client.login(username="inv-dash-super", password="secure-password-123")
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)
        stats = response.context["inventory_stats"]
        self.assertEqual(stats["total"], 3)
        self.assertEqual(stats["in_stock"], 2)
        self.assertEqual(stats["out_of_stock"], 1)
        self.assertEqual(stats["expired"], 1)
        self.assertContains(response, "<strong>Total inventory Products:</strong> 3")
        self.assertContains(response, "<strong>Out-of-stock Products:</strong> 1")
        self.assertContains(response, "<strong>Expired Products:</strong> 1")
