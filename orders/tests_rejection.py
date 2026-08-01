"""
StoreOrder rejection: multi-store status sync, totals, and once-only stock restore.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from cart.services import add_product_to_cart
from customers.models import AddressLabel, RegistrationSource
from customers.services import create_customer_delivery_address, create_customer_with_user
from inventory.models import InventoryTransaction, InventoryTransactionType

from .cancellation import reject_store_order
from .checkout import place_customer_order
from .models import (
    FulfillmentType,
    OrderItem,
    OrderStatus,
    OrderStatusHistory,
    PaymentMethod,
    PaymentStatus,
    StoreOrderStatus,
    StoreOrderStatusHistory,
)
from .store_status import accept_store_order, available_store_order_actions
from .tests_checkout import CheckoutTestMixin


class StoreOrderRejectionTests(CheckoutTestMixin, TestCase):
    def setUp(self):
        self.customer, self.user = create_customer_with_user(
            user_data={
                "username": "reject-customer",
                "email": "reject@example.com",
                "first_name": "Reject",
                "last_name": "Customer",
                "phone_number": "9000000801",
                "password": "secure-password-123",
            },
            registration_source=RegistrationSource.WEBSITE,
        )
        self.store_a = self.create_store(name="Reject Store A")
        self.store_b = self.create_store(name="Reject Store B")
        self.product_a = self.create_public_product(
            store=self.store_a,
            name="Reject Item A",
            stock=Decimal("10.000"),
            store_price=Decimal("100.00"),
            profit_margin=Decimal("0.00"),
        )
        self.product_b = self.create_public_product(
            store=self.store_b,
            name="Reject Item B",
            stock=Decimal("10.000"),
            store_price=Decimal("50.00"),
            profit_margin=Decimal("0.00"),
        )
        self.address = create_customer_delivery_address(
            customer=self.customer,
            data={
                "label": AddressLabel.HOME,
                "recipient_name": "Reject Customer",
                "phone_number": "9000000801",
                "line1": "9 Reject Lane",
                "line2": "",
                "landmark": "",
                "city": "Bengaluru",
                "district": "",
                "state": "Karnataka",
                "postal_code": "560001",
                "latitude": "12.971600",
                "longitude": "77.594600",
                "delivery_instructions": "",
                "is_default": True,
            },
        )

    def _place_multi_store(self, *, token, qty_a=Decimal("2.000"), qty_b=Decimal("3.000")):
        add_product_to_cart(
            customer=self.customer,
            product_code=self.product_a.product_code,
            quantity=qty_a,
        )
        add_product_to_cart(
            customer=self.customer,
            product_code=self.product_b.product_code,
            quantity=qty_b,
        )
        return place_customer_order(
            customer=self.customer,
            checkout_token=token,
            fulfillment_type=FulfillmentType.DELIVERY,
            payment_method=PaymentMethod.COD,
            delivery_address_id=self.address.pk,
            actor=self.user,
        )

    def _returns_for(self, product):
        return InventoryTransaction.objects.filter(
            product=product,
            transaction_type=InventoryTransactionType.CUSTOMER_RETURN,
            reference__startswith="order-item:",
        )

    def test_partial_rejection_sets_partially_cancelled_and_recalculates_total(self):
        order = self._place_multi_store(token="tok-reject-partial")
        store_order_a = order.store_orders.get(store=self.store_a)
        store_order_b = order.store_orders.get(store=self.store_b)
        original_total = order.grand_total
        expected_remaining = store_order_b.store_total

        reject_store_order(
            store_order=store_order_a,
            store=self.store_a,
            reason="Out of ingredients",
            actor=self.user,
        )

        order.refresh_from_db()
        store_order_a.refresh_from_db()
        store_order_b.refresh_from_db()

        self.assertEqual(store_order_a.status, StoreOrderStatus.REJECTED)
        self.assertEqual(store_order_b.status, StoreOrderStatus.PENDING)
        self.assertEqual(order.status, OrderStatus.PARTIALLY_CANCELLED)
        self.assertEqual(order.payment_status, PaymentStatus.PENDING)
        self.assertEqual(order.items_subtotal, store_order_b.items_subtotal)
        self.assertEqual(order.grand_total, expected_remaining)
        self.assertLess(order.grand_total, original_total)

        item_a = OrderItem.objects.get(store_order=store_order_a)
        item_b = OrderItem.objects.get(store_order=store_order_b)
        self.assertTrue(item_a.is_rejected)
        self.assertIsNotNone(item_a.rejected_at)
        self.assertFalse(item_a.is_cancelled)
        self.assertFalse(item_b.is_rejected)
        self.assertTrue(item_a.stock_restored)
        self.assertFalse(item_b.stock_restored)

        self.assertTrue(
            StoreOrderStatusHistory.objects.filter(
                store_order=store_order_a,
                new_status=StoreOrderStatus.REJECTED,
            ).exists()
        )
        self.assertTrue(
            OrderStatusHistory.objects.filter(
                order=order,
                new_status=OrderStatus.PARTIALLY_CANCELLED,
            ).exists()
        )

        self.product_a.refresh_from_db()
        self.product_b.refresh_from_db()
        self.assertEqual(self.product_a.stock_quantity, Decimal("10.000"))
        self.assertEqual(self.product_b.stock_quantity, Decimal("7.000"))
        self.assertEqual(self._returns_for(self.product_a).count(), 1)
        self.assertEqual(self._returns_for(self.product_b).count(), 0)

    def test_rejecting_all_store_orders_cancels_parent_and_zeros_total(self):
        order = self._place_multi_store(token="tok-reject-all")
        store_order_a = order.store_orders.get(store=self.store_a)
        store_order_b = order.store_orders.get(store=self.store_b)

        reject_store_order(
            store_order=store_order_a,
            store=self.store_a,
            reason="Cannot fulfil A",
            actor=self.user,
        )
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.PARTIALLY_CANCELLED)

        reject_store_order(
            store_order=store_order_b,
            store=self.store_b,
            reason="Cannot fulfil B",
            actor=self.user,
        )

        order.refresh_from_db()
        store_order_a.refresh_from_db()
        store_order_b.refresh_from_db()
        self.assertEqual(store_order_a.status, StoreOrderStatus.REJECTED)
        self.assertEqual(store_order_b.status, StoreOrderStatus.REJECTED)
        self.assertEqual(order.status, OrderStatus.CANCELLED)
        self.assertEqual(order.payment_status, PaymentStatus.CANCELLED)
        self.assertEqual(order.items_subtotal, Decimal("0.00"))
        self.assertEqual(order.grand_total, Decimal("0.00"))

        self.assertTrue(
            OrderStatusHistory.objects.filter(
                order=order,
                new_status=OrderStatus.CANCELLED,
            ).exists()
        )
        self.assertEqual(
            OrderItem.objects.filter(
                store_order__order=order,
                is_rejected=True,
            ).count(),
            2,
        )

        self.product_a.refresh_from_db()
        self.product_b.refresh_from_db()
        self.assertEqual(self.product_a.stock_quantity, Decimal("10.000"))
        self.assertEqual(self.product_b.stock_quantity, Decimal("10.000"))
        self.assertEqual(self._returns_for(self.product_a).count(), 1)
        self.assertEqual(self._returns_for(self.product_b).count(), 1)

    def test_rejection_requires_reason(self):
        order = self._place_multi_store(token="tok-reject-reason")
        store_order_a = order.store_orders.get(store=self.store_a)
        with self.assertRaises(ValidationError) as ctx:
            reject_store_order(
                store_order=store_order_a,
                store=self.store_a,
                reason="   ",
                actor=self.user,
            )
        self.assertIn("reason", ctx.exception.message_dict)
        store_order_a.refresh_from_db()
        self.assertEqual(store_order_a.status, StoreOrderStatus.PENDING)

    def test_only_pending_store_order_may_be_rejected(self):
        order = self._place_multi_store(token="tok-reject-pending-only")
        store_order_a = order.store_orders.get(store=self.store_a)
        accept_store_order(
            store_order=store_order_a,
            store=self.store_a,
            actor=self.user,
        )
        store_order_a.refresh_from_db()
        self.assertEqual(store_order_a.status, StoreOrderStatus.ACCEPTED)
        self.assertNotIn("reject", available_store_order_actions(store_order_a))

        with self.assertRaises(ValidationError) as ctx:
            reject_store_order(
                store_order=store_order_a,
                store=self.store_a,
                reason="Too late",
                actor=self.user,
            )
        self.assertIn("status", ctx.exception.message_dict)
        store_order_a.refresh_from_db()
        self.assertEqual(store_order_a.status, StoreOrderStatus.ACCEPTED)
        self.assertEqual(self._returns_for(self.product_a).count(), 0)

    def test_repeated_rejection_restores_stock_exactly_once(self):
        order = self._place_multi_store(token="tok-reject-idempotent")
        store_order_a = order.store_orders.get(store=self.store_a)

        reject_store_order(
            store_order=store_order_a,
            store=self.store_a,
            reason="First reject",
            actor=self.user,
        )
        reject_store_order(
            store_order=store_order_a,
            store=self.store_a,
            reason="Retry reject",
            actor=self.user,
        )

        self.product_a.refresh_from_db()
        self.assertEqual(self.product_a.stock_quantity, Decimal("10.000"))
        self.assertEqual(self._returns_for(self.product_a).count(), 1)
        self.assertEqual(
            StoreOrderStatusHistory.objects.filter(
                store_order=store_order_a,
                new_status=StoreOrderStatus.REJECTED,
            ).count(),
            1,
        )
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.PARTIALLY_CANCELLED)
        self.assertEqual(
            OrderStatusHistory.objects.filter(
                order=order,
                new_status=OrderStatus.PARTIALLY_CANCELLED,
            ).count(),
            1,
        )
