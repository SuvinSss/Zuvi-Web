"""
Dashboard order statistics: aggregates, permissions, and store isolation.
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role
from stores.models import StoreUser

from .management import get_order_dashboard_stats
from .models import OrderStatus, StoreOrderStatus
from .store_portal import (
    get_store_order_dashboard_stats,
    get_store_recent_store_orders,
)
from .tests import OrderModelTestMixin

User = get_user_model()


class OrderDashboardStatsTests(OrderModelTestMixin, TestCase):
    def setUp(self):
        self.customer = self.create_customer(username="dash-order-cust")
        self.store_a = self.create_store(name="Dash Store A")
        self.store_b = self.create_store(name="Dash Store B")

        self.order_pending = self.create_delivery_order(
            customer=self.customer,
            status=OrderStatus.PLACED,
            grand_total=Decimal("100.00"),
        )
        self.create_store_order(
            order=self.order_pending,
            store=self.store_a,
            status=StoreOrderStatus.PENDING,
        )

        self.order_processing = self.create_delivery_order(
            customer=self.customer,
            status=OrderStatus.IN_PROGRESS,
            grand_total=Decimal("50.00"),
        )
        self.create_store_order(
            order=self.order_processing,
            store=self.store_a,
            status=StoreOrderStatus.PREPARING,
        )

        self.order_ready = self.create_delivery_order(
            customer=self.customer,
            status=OrderStatus.IN_PROGRESS,
            grand_total=Decimal("75.00"),
        )
        self.create_store_order(
            order=self.order_ready,
            store=self.store_b,
            status=StoreOrderStatus.READY,
        )

        self.order_cancelled = self.create_delivery_order(
            customer=self.customer,
            status=OrderStatus.CANCELLED,
            grand_total=Decimal("20.00"),
        )
        self.create_store_order(
            order=self.order_cancelled,
            store=self.store_a,
            status=StoreOrderStatus.CANCELLED,
        )

        for order in (
            self.order_pending,
            self.order_processing,
            self.order_ready,
            self.order_cancelled,
        ):
            order.__class__.objects.filter(pk=order.pk).update(
                placed_at=timezone.now()
            )

    def test_order_dashboard_stats_counts_and_value(self):
        with CaptureQueriesContext(connection) as ctx:
            stats = get_order_dashboard_stats()

        self.assertEqual(len(ctx.captured_queries), 1)
        self.assertIn("COUNT", ctx.captured_queries[0]["sql"].upper())
        self.assertEqual(stats["orders_today"], 4)
        self.assertEqual(stats["pending"], 1)
        self.assertEqual(stats["processing"], 2)
        self.assertEqual(stats["ready"], 1)
        self.assertEqual(stats["cancelled"], 1)
        self.assertEqual(stats["total_order_value"], Decimal("245.00"))

    def test_management_dashboard_hides_order_stats_without_permission(self):
        User.objects.create_user(
            username="dash-order-admin-none",
            email="dash-order-admin-none@example.com",
            password="secure-password-123",
            role=Role.ADMIN,
            is_staff=True,
        )
        dashboard = reverse("accounts:management_dashboard")
        self.client.login(
            username="dash-order-admin-none", password="secure-password-123"
        )
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(dashboard)

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["order_stats"])
        self.assertNotContains(response, "Orders today")
        self.assertNotContains(response, "Total order value")
        order_table_queries = [
            query["sql"]
            for query in ctx.captured_queries
            if "orders_order" in query["sql"].lower()
            and "count" in query["sql"].lower()
        ]
        self.assertEqual(order_table_queries, [])

    def test_management_dashboard_shows_order_stats_with_view_order(self):
        admin = User.objects.create_user(
            username="dash-order-admin-view",
            email="dash-order-admin-view@example.com",
            password="secure-password-123",
            role=Role.ADMIN,
            is_staff=True,
        )
        admin.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="orders",
                codename="view_order",
            )
        )
        dashboard = reverse("accounts:management_dashboard")
        self.client.login(
            username="dash-order-admin-view", password="secure-password-123"
        )
        response = self.client.get(dashboard)
        self.assertEqual(response.status_code, 200)
        stats = response.context["order_stats"]
        self.assertIsNotNone(stats)
        self.assertEqual(stats["pending"], 1)
        self.assertEqual(stats["processing"], 2)
        self.assertEqual(stats["ready"], 1)
        self.assertEqual(stats["cancelled"], 1)
        self.assertContains(response, "<strong>Orders today:</strong> 4")
        self.assertContains(response, "<strong>Pending Orders:</strong> 1")
        self.assertContains(response, "<strong>Processing Orders:</strong> 2")
        self.assertContains(response, "<strong>Ready Orders:</strong> 1")
        self.assertContains(response, "<strong>Cancelled Orders:</strong> 1")
        self.assertContains(response, "<strong>Total order value:</strong> ₹245.00")
        self.assertEqual(stats["total_order_value"], Decimal("245.00"))
        self.assertContains(response, reverse("orders:management_order_list"))

    def test_management_dashboard_shows_order_stats_for_super_admin(self):
        User.objects.create_user(
            username="dash-order-super",
            email="dash-order-super@example.com",
            password="secure-password-123",
            role=Role.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        self.client.login(username="dash-order-super", password="secure-password-123")
        response = self.client.get(reverse("accounts:management_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.context["order_stats"])
        self.assertContains(response, "<strong>Pending Orders:</strong> 1")


class StoreOrderDashboardStatsTests(OrderModelTestMixin, TestCase):
    def setUp(self):
        self.store_a = self.create_store(name="Store Dash A")
        self.store_b = self.create_store(name="Store Dash B")
        self.customer = self.create_customer(username="store-dash-cust")

        # Store A: PENDING, ACCEPTED, PREPARING, READY
        for status in (
            StoreOrderStatus.PENDING,
            StoreOrderStatus.ACCEPTED,
            StoreOrderStatus.PREPARING,
            StoreOrderStatus.READY,
        ):
            order = self.create_delivery_order(customer=self.customer)
            self.create_store_order(order=order, store=self.store_a, status=status)

        # Store B: PENDING x2, READY x1 — must not leak into store A counts
        for status in (
            StoreOrderStatus.PENDING,
            StoreOrderStatus.PENDING,
            StoreOrderStatus.READY,
        ):
            order = self.create_delivery_order(customer=self.customer)
            self.create_store_order(order=order, store=self.store_b, status=status)

        self.user_a = User.objects.create_user(
            username="store-dash-a",
            email="store-dash-a@example.com",
            password="secure-password-123",
            role=Role.STORE_USER,
        )
        StoreUser.objects.create(
            store=self.store_a,
            user=self.user_a,
            is_primary=True,
            is_active=True,
            can_manage_orders=True,
        )
        self.user_b = User.objects.create_user(
            username="store-dash-b",
            email="store-dash-b@example.com",
            password="secure-password-123",
            role=Role.STORE_USER,
        )
        StoreUser.objects.create(
            store=self.store_b,
            user=self.user_b,
            is_primary=True,
            is_active=True,
            can_manage_orders=True,
        )
        self.dashboard_url = reverse("stores:store_portal_dashboard")

    def test_store_order_dashboard_stats_single_aggregate(self):
        with CaptureQueriesContext(connection) as ctx:
            stats = get_store_order_dashboard_stats(self.store_a)

        self.assertEqual(len(ctx.captured_queries), 1)
        self.assertEqual(stats["pending"], 1)
        self.assertEqual(stats["accepted"], 1)
        self.assertEqual(stats["processing"], 1)
        self.assertEqual(stats["ready"], 1)

    def test_store_a_dashboard_counts_only_own_store_orders(self):
        self.client.login(username="store-dash-a", password="secure-password-123")
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)
        stats = response.context["order_stats"]
        self.assertEqual(stats["pending"], 1)
        self.assertEqual(stats["accepted"], 1)
        self.assertEqual(stats["processing"], 1)
        self.assertEqual(stats["ready"], 1)
        self.assertContains(response, "<strong>Pending StoreOrders:</strong> 1")
        self.assertContains(response, "<strong>Accepted StoreOrders:</strong> 1")
        self.assertContains(response, "<strong>Processing StoreOrders:</strong> 1")
        self.assertContains(response, "<strong>Ready StoreOrders:</strong> 1")
        self.assertEqual(len(response.context["recent_store_orders"]), 4)
        recent_numbers = [
            so.store_order_number for so in response.context["recent_store_orders"]
        ]
        for so in get_store_recent_store_orders(self.store_b):
            self.assertNotIn(so.store_order_number, recent_numbers)

    def test_store_b_dashboard_isolated_from_store_a(self):
        self.client.login(username="store-dash-b", password="secure-password-123")
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)
        stats = response.context["order_stats"]
        self.assertEqual(stats["pending"], 2)
        self.assertEqual(stats["accepted"], 0)
        self.assertEqual(stats["processing"], 0)
        self.assertEqual(stats["ready"], 1)
        self.assertContains(response, "<strong>Pending StoreOrders:</strong> 2")
        self.assertNotContains(response, "<strong>Accepted StoreOrders:</strong> 1")
        self.assertEqual(len(response.context["recent_store_orders"]), 3)
