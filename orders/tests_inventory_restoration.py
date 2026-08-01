"""
Order inventory mapping and once-only deduct / restore behaviour.

Existing InventoryTransaction types (no new concepts):
- Checkout / order placement → STOCK_OUT
- Cancellation → CUSTOMER_RETURN
- Store rejection → CUSTOMER_RETURN

Each movement uses an immutable ``order-item:{id}:deduct|restore`` reference
so duplicate deduction or restoration cannot create a second ledger row.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from accounts.models import Role
from cart.models import CartItem
from cart.services import add_product_to_cart
from customers.models import AddressLabel, RegistrationSource
from customers.services import create_customer_delivery_address, create_customer_with_user
from inventory.models import InventoryTransaction, InventoryTransactionType
from inventory.services import (
    deduct_order_stock,
    order_item_deduct_reference,
    order_item_restore_reference,
    restore_order_stock,
)

from .cancellation import (
    cancel_customer_order,
    cancel_order_by_admin,
    reject_store_order,
)
from .checkout import place_customer_order
from .models import (
    FulfillmentType,
    Order,
    OrderItem,
    OrderStatus,
    PaymentMethod,
    StoreOrderStatus,
)
from .tests_checkout import CheckoutTestMixin


class OrderInventoryRestorationTests(CheckoutTestMixin, TestCase):
    def setUp(self):
        self.customer, self.user = create_customer_with_user(
            user_data={
                "username": "restore-customer",
                "email": "restore@example.com",
                "first_name": "Restore",
                "last_name": "Customer",
                "phone_number": "9000000701",
                "password": "secure-password-123",
            },
            registration_source=RegistrationSource.WEBSITE,
        )
        from django.contrib.auth import get_user_model

        User = get_user_model()
        self.admin = User.objects.create_user(
            username="restore-admin",
            email="restore-admin@example.com",
            password="secure-password-123",
            role=Role.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        self.store_a = self.create_store(name="Store A")
        self.store_b = self.create_store(name="Store B")
        self.product_a = self.create_public_product(
            store=self.store_a,
            name="Item A",
            stock=Decimal("10.000"),
        )
        self.product_b = self.create_public_product(
            store=self.store_b,
            name="Item B",
            stock=Decimal("10.000"),
        )
        self.address = create_customer_delivery_address(
            customer=self.customer,
            data={
                "label": AddressLabel.HOME,
                "recipient_name": "Restore Customer",
                "phone_number": "9000000701",
                "line1": "7 Restore Lane",
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

    def _add_and_place(self, *, token, lines):
        for product, quantity in lines:
            add_product_to_cart(
                customer=self.customer,
                product_code=product.product_code,
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

    def _stock_out_for(self, product):
        return InventoryTransaction.objects.filter(
            product=product,
            transaction_type=InventoryTransactionType.STOCK_OUT,
            reference__startswith="order-item:",
        )

    def _return_for(self, product):
        return InventoryTransaction.objects.filter(
            product=product,
            transaction_type=InventoryTransactionType.CUSTOMER_RETURN,
            reference__startswith="order-item:",
        )

    def test_checkout_deducts_once(self):
        order = self._add_and_place(
            token="tok-checkout-once",
            lines=[(self.product_a, Decimal("3.000"))],
        )
        item = OrderItem.objects.get(store_order__order=order)
        self.product_a.refresh_from_db()
        self.assertEqual(self.product_a.stock_quantity, Decimal("7.000"))
        self.assertEqual(self._stock_out_for(self.product_a).count(), 1)
        txn = self._stock_out_for(self.product_a).get()
        self.assertEqual(txn.reference, order_item_deduct_reference(item.pk))
        self.assertTrue(txn.is_system_generated)

    def test_duplicate_checkout_does_not_deduct_again(self):
        order = self._add_and_place(
            token="tok-checkout-dup",
            lines=[(self.product_a, Decimal("3.000"))],
        )
        place_customer_order(
            customer=self.customer,
            checkout_token="tok-checkout-dup",
            fulfillment_type=FulfillmentType.DELIVERY,
            payment_method=PaymentMethod.COD,
            delivery_address_id=self.address.pk,
            actor=self.user,
        )
        self.product_a.refresh_from_db()
        self.assertEqual(self.product_a.stock_quantity, Decimal("7.000"))
        self.assertEqual(self._stock_out_for(self.product_a).count(), 1)
        self.assertEqual(Order.objects.filter(pk=order.pk).count(), 1)

        # Inventory-layer guard: same order-item deduct reference is a no-op.
        item = OrderItem.objects.get(store_order__order=order)
        before = self.product_a.stock_quantity
        again = deduct_order_stock(
            product=self.product_a,
            store=self.store_a,
            quantity=item.quantity,
            reference=order_item_deduct_reference(item.pk),
            actor=self.user,
            reason="Retry",
        )
        self.product_a.refresh_from_db()
        self.assertEqual(self.product_a.stock_quantity, before)
        self.assertEqual(again.reference, order_item_deduct_reference(item.pk))
        self.assertEqual(self._stock_out_for(self.product_a).count(), 1)

    def test_cancellation_restores_once(self):
        order = self._add_and_place(
            token="tok-cust-cancel",
            lines=[(self.product_a, Decimal("4.000"))],
        )
        item = OrderItem.objects.get(store_order__order=order)
        self.product_a.refresh_from_db()
        self.assertEqual(self.product_a.stock_quantity, Decimal("6.000"))

        cancel_customer_order(
            order=order,
            customer=self.customer,
            reason="Changed my mind",
            actor=self.user,
        )
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.CANCELLED)
        self.product_a.refresh_from_db()
        self.assertEqual(self.product_a.stock_quantity, Decimal("10.000"))
        self.assertEqual(self._return_for(self.product_a).count(), 1)
        restore_txn = self._return_for(self.product_a).get()
        self.assertEqual(
            restore_txn.reference,
            order_item_restore_reference(item.pk),
        )
        self.assertTrue(restore_txn.is_system_generated)
        item.refresh_from_db()
        self.assertTrue(item.stock_restored)

    def test_duplicate_cancellation_does_not_restore_twice(self):
        order = self._add_and_place(
            token="tok-cust-cancel-dup",
            lines=[(self.product_a, Decimal("4.000"))],
        )
        item = OrderItem.objects.get(store_order__order=order)
        cancel_customer_order(
            order=order,
            customer=self.customer,
            reason="Changed my mind",
            actor=self.user,
        )
        cancel_customer_order(
            order=order,
            customer=self.customer,
            reason="Changed my mind again",
            actor=self.user,
        )
        self.product_a.refresh_from_db()
        self.assertEqual(self.product_a.stock_quantity, Decimal("10.000"))
        self.assertEqual(self._return_for(self.product_a).count(), 1)

        # Inventory-layer guard: same restore reference is a no-op.
        again = restore_order_stock(
            product=self.product_a,
            store=self.store_a,
            quantity=item.quantity,
            reference=order_item_restore_reference(item.pk),
            actor=self.user,
            reason="Forced retry",
        )
        self.product_a.refresh_from_db()
        self.assertEqual(self.product_a.stock_quantity, Decimal("10.000"))
        self.assertEqual(again.pk, self._return_for(self.product_a).get().pk)
        self.assertEqual(self._return_for(self.product_a).count(), 1)

    def test_store_rejection_restores_only_that_stores_items(self):
        order = self._add_and_place(
            token="tok-store-reject",
            lines=[
                (self.product_a, Decimal("2.000")),
                (self.product_b, Decimal("3.000")),
            ],
        )
        store_order_a = order.store_orders.get(store=self.store_a)
        store_order_b = order.store_orders.get(store=self.store_b)

        reject_store_order(
            store_order=store_order_a,
            store=self.store_a,
            reason="Out of ingredients",
            actor=self.user,
        )
        store_order_a.refresh_from_db()
        store_order_b.refresh_from_db()
        self.assertEqual(store_order_a.status, StoreOrderStatus.REJECTED)
        self.assertEqual(store_order_b.status, StoreOrderStatus.PENDING)

        self.product_a.refresh_from_db()
        self.product_b.refresh_from_db()
        self.assertEqual(self.product_a.stock_quantity, Decimal("10.000"))
        self.assertEqual(self.product_b.stock_quantity, Decimal("7.000"))
        self.assertEqual(self._return_for(self.product_a).count(), 1)
        self.assertEqual(self._return_for(self.product_b).count(), 0)
        self.assertTrue(
            OrderItem.objects.get(store_order=store_order_a).stock_restored
        )
        self.assertFalse(
            OrderItem.objects.get(store_order=store_order_b).stock_restored
        )

        reject_store_order(
            store_order=store_order_a,
            store=self.store_a,
            reason="Still rejected",
            actor=self.user,
        )
        self.product_a.refresh_from_db()
        self.assertEqual(self.product_a.stock_quantity, Decimal("10.000"))
        self.assertEqual(self._return_for(self.product_a).count(), 1)

    def test_failed_checkout_leaves_inventory_unchanged(self):
        add_product_to_cart(
            customer=self.customer,
            product_code=self.product_a.product_code,
            quantity=Decimal("2.000"),
        )
        CartItem.objects.filter(cart__customer=self.customer).update(
            quantity=Decimal("99.000")
        )
        opening_txns = InventoryTransaction.objects.filter(
            product=self.product_a
        ).count()
        with self.assertRaises(ValidationError):
            place_customer_order(
                customer=self.customer,
                checkout_token="tok-rollback",
                fulfillment_type=FulfillmentType.DELIVERY,
                payment_method=PaymentMethod.COD,
                delivery_address_id=self.address.pk,
                actor=self.user,
            )
        self.assertEqual(Order.objects.count(), 0)
        self.assertFalse(self._stock_out_for(self.product_a).exists())
        self.assertEqual(
            InventoryTransaction.objects.filter(product=self.product_a).count(),
            opening_txns,
        )
        self.product_a.refresh_from_db()
        self.assertEqual(self.product_a.stock_quantity, Decimal("10.000"))

    def test_admin_cancellation_restores_only_unrestored_quantities(self):
        order = self._add_and_place(
            token="tok-admin-cancel",
            lines=[
                (self.product_a, Decimal("2.000")),
                (self.product_b, Decimal("5.000")),
            ],
        )
        store_order_a = order.store_orders.get(store=self.store_a)

        reject_store_order(
            store_order=store_order_a,
            store=self.store_a,
            reason="Cannot fulfil",
            actor=self.user,
        )
        self.product_a.refresh_from_db()
        self.product_b.refresh_from_db()
        self.assertEqual(self.product_a.stock_quantity, Decimal("10.000"))
        self.assertEqual(self.product_b.stock_quantity, Decimal("5.000"))

        cancel_order_by_admin(
            order=order,
            actor=self.admin,
            reason="Customer escalation",
        )
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.CANCELLED)
        self.product_a.refresh_from_db()
        self.product_b.refresh_from_db()
        self.assertEqual(self.product_a.stock_quantity, Decimal("10.000"))
        self.assertEqual(self.product_b.stock_quantity, Decimal("10.000"))
        self.assertEqual(self._return_for(self.product_a).count(), 1)
        self.assertEqual(self._return_for(self.product_b).count(), 1)

        cancel_order_by_admin(
            order=order,
            actor=self.admin,
            reason="Repeat cancel",
        )
        self.product_a.refresh_from_db()
        self.product_b.refresh_from_db()
        self.assertEqual(self.product_a.stock_quantity, Decimal("10.000"))
        self.assertEqual(self.product_b.stock_quantity, Decimal("10.000"))
        self.assertEqual(self._return_for(self.product_a).count(), 1)
        self.assertEqual(self._return_for(self.product_b).count(), 1)
