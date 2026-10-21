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

    def test_store_order_dashboard_stats_single_aggregate(self):
        with CaptureQueriesContext(connection) as ctx:
            stats = get_store_order_dashboard_stats(self.store_a)

        self.assertEqual(len(ctx.captured_queries), 1)
        self.assertEqual(stats["pending"], 1)
        self.assertEqual(stats["accepted"], 1)
        self.assertEqual(stats["processing"], 1)
        self.assertEqual(stats["ready"], 1)


