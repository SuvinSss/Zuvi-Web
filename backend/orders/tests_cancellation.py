"""
Full customer order cancellation: valid, invalid, and idempotent paths.
"""

from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase

from cart.services import add_product_to_cart
from customers.models import AddressLabel, RegistrationSource
from customers.services import create_customer_delivery_address, create_customer_with_user
from inventory.models import InventoryTransaction, InventoryTransactionType

from .cancellation import cancel_customer_order
from .checkout import place_customer_order
from .models import (
    FulfillmentType,
    Order,
    OrderItem,
    OrderStatus,
    OrderStatusHistory,
    PaymentMethod,
    PaymentStatus,
    StoreOrder,
    StoreOrderStatus,
    StoreOrderStatusHistory,
)
from .tests_checkout import CheckoutTestMixin


class CustomerOrderCancellationServiceTests(CheckoutTestMixin, TestCase):
    def setUp(self):
        self.customer, self.user = create_customer_with_user(
            user_data={
                "username": "cancel-customer",
                "email": "cancel-customer@example.com",
                "first_name": "Cancel",
                "last_name": "Customer",
                "phone_number": "9000000901",
                "password": "secure-password-123",
            },
            registration_source=RegistrationSource.WEBSITE,
        )
        self.other_customer, self.other_user = create_customer_with_user(
            user_data={
                "username": "cancel-other",
                "email": "cancel-other@example.com",
                "first_name": "Other",
                "last_name": "Customer",
                "phone_number": "9000000902",
                "password": "secure-password-123",
            },
            registration_source=RegistrationSource.WEBSITE,
        )
        self.store = self.create_store(name="Cancel Store")
        self.product = self.create_public_product(
            store=self.store,
            name="Cancel Item",
            stock=Decimal("10.000"),
        )
        self.address = create_customer_delivery_address(
            customer=self.customer,
            data={
                "label": AddressLabel.HOME,
                "recipient_name": "Cancel Customer",
                "phone_number": "9000000901",
                "line1": "9 Cancel Street",
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

    def _place(self, *, token, quantity=Decimal("3.000")):
        add_product_to_cart(
            customer=self.customer,
            product_code=self.product.product_code,
            quantity=quantity,
        )
        return place_customer_order(
            customer=self.customer,
            checkout_token=token,
            fulfillment_type=FulfillmentType.DELIVERY,
            payment_method=PaymentMethod.COD,
            delivery_address_id=self.address.pk,
            actor=self.user,
        )

    def _return_count(self):
        return InventoryTransaction.objects.filter(
            product=self.product,
            transaction_type=InventoryTransactionType.CUSTOMER_RETURN,
            reference__startswith="order-item:",
        ).count()

    def test_valid_cancellation_marks_all_rows_restores_stock_and_keeps_history(self):
        order = self._place(token="tok-cancel-valid")
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("7.000"))

        cancel_customer_order(
            order=order,
            customer=self.customer,
            reason="Changed plans",
            actor=self.user,
        )

        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.CANCELLED)
        self.assertEqual(order.cancellation_reason, "Changed plans")
        self.assertIsNotNone(order.cancelled_at)
        self.assertEqual(order.cancelled_by_id, self.user.pk)
        self.assertEqual(order.payment_status, PaymentStatus.CANCELLED)

        store_order = order.store_orders.get()
        self.assertEqual(store_order.status, StoreOrderStatus.CANCELLED)

        items = list(OrderItem.objects.filter(store_order__order=order))
        self.assertTrue(items)
        for item in items:
            self.assertTrue(item.is_cancelled)
            self.assertIsNotNone(item.cancelled_at)
            self.assertTrue(item.stock_restored)

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("10.000"))
        self.assertEqual(self._return_count(), 1)

        self.assertTrue(
            OrderStatusHistory.objects.filter(
                order=order,
                new_status=OrderStatus.CANCELLED,
            ).exists()
        )
        self.assertTrue(
            StoreOrderStatusHistory.objects.filter(
                store_order=store_order,
                new_status=StoreOrderStatus.CANCELLED,
            ).exists()
        )
        # Nothing deleted.
        self.assertEqual(Order.objects.filter(pk=order.pk).count(), 1)
        self.assertEqual(StoreOrder.objects.filter(order=order).count(), 1)
        self.assertEqual(OrderItem.objects.filter(store_order__order=order).count(), 1)

    def test_valid_cancellation_from_confirmed_with_accepted_store_order(self):
        order = self._place(token="tok-cancel-confirmed")
        order.status = OrderStatus.CONFIRMED
        order.save(update_fields=["status", "updated_at"])
        store_order = order.store_orders.get()
        store_order.status = StoreOrderStatus.ACCEPTED
        store_order.save(update_fields=["status", "updated_at"])

        cancel_customer_order(
            order=order,
            customer=self.customer,
            reason="Still early enough",
            actor=self.user,
        )
        order.refresh_from_db()
        store_order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.CANCELLED)
        self.assertEqual(store_order.status, StoreOrderStatus.CANCELLED)

    def test_invalid_cancellation_wrong_customer(self):
        order = self._place(token="tok-cancel-wrong-cust")
        with self.assertRaises(PermissionDenied):
            cancel_customer_order(
                order=order,
                customer=self.other_customer,
                reason="Not mine",
                actor=self.other_user,
            )
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.PLACED)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("7.000"))
        self.assertEqual(self._return_count(), 0)

    def test_invalid_cancellation_missing_reason(self):
        order = self._place(token="tok-cancel-no-reason")
        with self.assertRaises(ValidationError) as ctx:
            cancel_customer_order(
                order=order,
                customer=self.customer,
                reason="   ",
                actor=self.user,
            )
        self.assertIn("reason", ctx.exception.message_dict)
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.PLACED)

    def test_invalid_cancellation_when_order_in_progress(self):
        order = self._place(token="tok-cancel-in-progress")
        order.status = OrderStatus.IN_PROGRESS
        order.save(update_fields=["status", "updated_at"])
        with self.assertRaises(ValidationError) as ctx:
            cancel_customer_order(
                order=order,
                customer=self.customer,
                reason="Too late",
                actor=self.user,
            )
        self.assertIn("status", ctx.exception.message_dict)
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.IN_PROGRESS)
        self.assertEqual(self._return_count(), 0)

    def test_invalid_cancellation_when_store_order_processing(self):
        order = self._place(token="tok-cancel-preparing")
        store_order = order.store_orders.get()
        store_order.status = StoreOrderStatus.PREPARING
        store_order.save(update_fields=["status", "updated_at"])

        with self.assertRaises(ValidationError) as ctx:
            cancel_customer_order(
                order=order,
                customer=self.customer,
                reason="Store already processing",
                actor=self.user,
            )
        self.assertIn("status", ctx.exception.message_dict)
        self.assertIn("PREPARING", str(ctx.exception))
        order.refresh_from_db()
        store_order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.PLACED)
        self.assertEqual(store_order.status, StoreOrderStatus.PREPARING)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("7.000"))

    def test_invalid_cancellation_when_store_order_ready(self):
        order = self._place(token="tok-cancel-ready")
        store_order = order.store_orders.get()
        store_order.status = StoreOrderStatus.READY
        store_order.save(update_fields=["status", "updated_at"])
        with self.assertRaises(ValidationError):
            cancel_customer_order(
                order=order,
                customer=self.customer,
                reason="Already ready",
                actor=self.user,
            )
        self.assertEqual(self._return_count(), 0)

    def test_invalid_cancellation_when_store_order_completed(self):
        order = self._place(token="tok-cancel-completed")
        store_order = order.store_orders.get()
        store_order.status = StoreOrderStatus.COMPLETED
        store_order.save(update_fields=["status", "updated_at"])
        with self.assertRaises(ValidationError):
            cancel_customer_order(
                order=order,
                customer=self.customer,
                reason="Already fulfilled",
                actor=self.user,
            )
        self.assertEqual(self._return_count(), 0)

    def test_repeated_cancellation_is_idempotent(self):
        order = self._place(token="tok-cancel-repeat")
        cancel_customer_order(
            order=order,
            customer=self.customer,
            reason="First cancel",
            actor=self.user,
        )
        self.product.refresh_from_db()
        stock_after_first = self.product.stock_quantity
        history_count = OrderStatusHistory.objects.filter(order=order).count()
        store_history_count = StoreOrderStatusHistory.objects.filter(
            store_order__order=order
        ).count()
        return_count = self._return_count()

        # Second call must not raise, restore again, or duplicate histories.
        cancel_customer_order(
            order=order,
            customer=self.customer,
            reason="Second cancel attempt",
            actor=self.user,
        )
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.CANCELLED)
        self.assertEqual(order.cancellation_reason, "First cancel")
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, stock_after_first)
        self.assertEqual(self._return_count(), return_count)
        self.assertEqual(
            OrderStatusHistory.objects.filter(order=order).count(),
            history_count,
        )
        self.assertEqual(
            StoreOrderStatusHistory.objects.filter(
                store_order__order=order
            ).count(),
            store_history_count,
        )
        item = OrderItem.objects.get(store_order__order=order)
        self.assertTrue(item.is_cancelled)
        self.assertTrue(item.stock_restored)
