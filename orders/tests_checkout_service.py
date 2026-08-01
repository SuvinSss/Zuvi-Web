"""
Unit, transaction-rollback and concurrency-oriented tests for the checkout service.
"""

from datetime import timedelta
from decimal import Decimal
from threading import Thread
from unittest import skipUnless

from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from cart.models import CartItem
from cart.services import add_product_to_cart
from catalog.models import ProductStatus
from customers.models import AddressLabel, RegistrationSource
from customers.services import create_customer_delivery_address, create_customer_with_user
from inventory.models import InventoryTransaction, InventoryTransactionType
from inventory.services import record_manual_stock_in
from stores.models import StoreStatus

from .checkout import place_customer_order
from .models import (
    FulfillmentType,
    Order,
    OrderItem,
    OrderStatusHistory,
    PaymentMethod,
    PaymentStatus,
    StoreOrder,
    StoreOrderStatusHistory,
)
from .tests_checkout import CheckoutTestMixin


class CheckoutServiceUnitTests(CheckoutTestMixin, TestCase):
    def setUp(self):
        self.customer, self.user = create_customer_with_user(
            user_data={
                "username": "svc-customer",
                "email": "svc@example.com",
                "first_name": "Svc",
                "last_name": "Customer",
                "phone_number": "9000000401",
                "password": "secure-password-123",
            },
            registration_source=RegistrationSource.WEBSITE,
        )
        self.store = self.create_store(name="Service Store")
        self.product = self.create_public_product(
            store=self.store,
            name="Service Milk",
            stock=Decimal("5.000"),
        )
        self.address = create_customer_delivery_address(
            customer=self.customer,
            data={
                "label": AddressLabel.HOME,
                "recipient_name": "Svc Customer",
                "phone_number": "9000000401",
                "line1": "12 Service Street",
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
        add_product_to_cart(
            customer=self.customer,
            product_code=self.product.product_code,
            quantity=Decimal("2.000"),
        )

    def _place(self, *, token="tok-svc-1", **overrides):
        kwargs = {
            "customer": self.customer,
            "checkout_token": token,
            "fulfillment_type": FulfillmentType.DELIVERY,
            "payment_method": PaymentMethod.COD,
            "delivery_address_id": self.address.pk,
            "customer_notes": "Note",
            "actor": self.user,
        }
        kwargs.update(overrides)
        return place_customer_order(**kwargs)

    def test_creates_order_store_order_items_histories_and_inventory(self):
        order = self._place()
        self.assertEqual(order.status, "PLACED")
        self.assertEqual(order.payment_status, PaymentStatus.PENDING)
        self.assertEqual(order.payment_method, PaymentMethod.COD)
        expected = (self.product.final_price * Decimal("2.000")).quantize(
            Decimal("0.01")
        )
        self.assertEqual(order.items_subtotal, expected)
        self.assertEqual(order.grand_total, expected)

        store_order = order.store_orders.get()
        self.assertEqual(store_order.store_id, self.store.pk)
        self.assertEqual(store_order.store_name, self.store.name)
        self.assertEqual(store_order.store_code, self.store.store_code)
        self.assertEqual(store_order.items_subtotal, expected)
        self.assertEqual(store_order.store_total, expected)

        item = store_order.items.get()
        self.assertEqual(item.product_id, self.product.pk)
        self.assertEqual(item.product_name, "Service Milk")
        self.assertEqual(item.product_code, self.product.product_code)
        self.assertEqual(item.sku, self.product.sku)
        self.assertEqual(item.unit, self.product.unit)
        self.assertEqual(item.unit_value, self.product.unit_value)
        self.assertEqual(item.unit_price, self.product.final_price)
        self.assertEqual(item.quantity, Decimal("2.000"))
        self.assertEqual(item.line_total, expected)

        self.assertEqual(OrderStatusHistory.objects.filter(order=order).count(), 1)
        self.assertEqual(
            StoreOrderStatusHistory.objects.filter(store_order=store_order).count(),
            1,
        )
        txn = InventoryTransaction.objects.get(
            product=self.product,
            transaction_type=InventoryTransactionType.STOCK_OUT,
        )
        self.assertEqual(txn.quantity, Decimal("2.000"))
        self.assertEqual(
            txn.reference,
            f"order-item:{item.pk}:deduct",
        )
        self.assertTrue(txn.is_system_generated)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("3.000"))
        self.assertFalse(
            CartItem.objects.filter(cart__customer=self.customer).exists()
        )

    def test_multi_store_creates_one_store_order_per_store(self):
        store_b = self.create_store(name="Second Store")
        product_b = self.create_public_product(
            store=store_b,
            name="Bread",
            stock=Decimal("4.000"),
        )
        add_product_to_cart(
            customer=self.customer,
            product_code=product_b.product_code,
            quantity=Decimal("1.000"),
        )
        order = self._place(token="tok-multi-1")
        self.assertEqual(order.store_orders.count(), 2)
        self.assertEqual(OrderItem.objects.filter(store_order__order=order).count(), 2)

    def test_idempotent_token_retry_returns_same_order_without_double_stock(self):
        first = self._place(token="tok-idem-1")
        self.product.refresh_from_db()
        stock_after_first = self.product.stock_quantity
        txn_count = InventoryTransaction.objects.filter(
            product=self.product,
            transaction_type=InventoryTransactionType.STOCK_OUT,
        ).count()

        second = self._place(token="tok-idem-1")
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Order.objects.count(), 1)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, stock_after_first)
        self.assertEqual(
            InventoryTransaction.objects.filter(
                product=self.product,
                transaction_type=InventoryTransactionType.STOCK_OUT,
            ).count(),
            txn_count,
        )

    def test_rejects_unapproved_product_and_keeps_cart(self):
        self.product.status = ProductStatus.PENDING
        self.product.save(update_fields=["status", "updated_at"])
        with self.assertRaises(ValidationError) as ctx:
            self._place(token="tok-pending")
        self.assertIn("Service Milk", str(ctx.exception))
        self.assertIn("review", str(ctx.exception).lower())
        self.assertEqual(Order.objects.count(), 0)
        self.assertTrue(
            CartItem.objects.filter(cart__customer=self.customer).exists()
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("5.000"))

    def test_rejects_inactive_store(self):
        self.store.status = StoreStatus.SUSPENDED
        self.store.save(update_fields=["status", "updated_at"])
        with self.assertRaises(ValidationError) as ctx:
            self._place(token="tok-store")
        self.assertIn("Service Milk", str(ctx.exception))
        self.assertEqual(Order.objects.count(), 0)

    def test_rejects_inactive_category(self):
        category = self.product.category
        category.is_active = False
        category.save(update_fields=["is_active", "updated_at"])
        with self.assertRaises(ValidationError) as ctx:
            self._place(token="tok-cat")
        self.assertIn("Service Milk", str(ctx.exception))
        self.assertEqual(Order.objects.count(), 0)

    def test_rejects_expired_product(self):
        self.product.expiry_date = timezone.localdate() - timedelta(days=1)
        self.product.save(update_fields=["expiry_date", "updated_at"])
        with self.assertRaises(ValidationError) as ctx:
            self._place(token="tok-exp")
        self.assertIn("Service Milk", str(ctx.exception))
        self.assertEqual(Order.objects.count(), 0)

    def test_rejects_insufficient_stock_without_partial_writes(self):
        CartItem.objects.filter(cart__customer=self.customer).update(
            quantity=Decimal("99.000")
        )
        with self.assertRaises(ValidationError) as ctx:
            self._place(token="tok-stock")
        message = str(ctx.exception)
        self.assertIn("Service Milk", message)
        self.assertIn("remain in stock", message)
        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(StoreOrder.objects.count(), 0)
        self.assertEqual(OrderItem.objects.count(), 0)
        self.assertFalse(
            InventoryTransaction.objects.filter(
                transaction_type=InventoryTransactionType.STOCK_OUT
            ).exists()
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("5.000"))
        self.assertEqual(
            CartItem.objects.get(cart__customer=self.customer).quantity,
            Decimal("99.000"),
        )

    def test_foreign_token_customer_rejected(self):
        other, _ = create_customer_with_user(
            user_data={
                "username": "svc-other",
                "email": "svc-other@example.com",
                "first_name": "Other",
                "last_name": "Customer",
                "phone_number": "9000000402",
                "password": "secure-password-123",
            },
            registration_source=RegistrationSource.WEBSITE,
        )
        order = self._place(token="tok-owned")
        with self.assertRaises(ValidationError):
            place_customer_order(
                customer=other,
                checkout_token="tok-owned",
                fulfillment_type=FulfillmentType.DELIVERY,
                payment_method=PaymentMethod.COD,
                delivery_address_id=self.address.pk,
                actor=None,
            )
        self.assertEqual(Order.objects.get().pk, order.pk)


class CheckoutServiceTransactionTests(CheckoutTestMixin, TestCase):
    """Failure mid-checkout must roll back completely and leave the cart intact."""

    def setUp(self):
        self.customer, self.user = create_customer_with_user(
            user_data={
                "username": "txn-customer",
                "email": "txn@example.com",
                "first_name": "Txn",
                "last_name": "Customer",
                "phone_number": "9000000501",
                "password": "secure-password-123",
            },
            registration_source=RegistrationSource.WEBSITE,
        )
        self.store = self.create_store(name="Txn Store")
        self.product = self.create_public_product(
            store=self.store,
            name="Txn Item",
            stock=Decimal("3.000"),
        )
        self.address = create_customer_delivery_address(
            customer=self.customer,
            data={
                "label": AddressLabel.HOME,
                "recipient_name": "Txn Customer",
                "phone_number": "9000000501",
                "line1": "1 Txn Road",
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
        add_product_to_cart(
            customer=self.customer,
            product_code=self.product.product_code,
            quantity=Decimal("1.000"),
        )

    def test_inventory_failure_rolls_back_order_and_keeps_cart(self):
        original_stock = self.product.stock_quantity

        def boom(**kwargs):
            raise ValidationError({"quantity": "Forced inventory failure."})

        from orders import checkout as checkout_module

        original = checkout_module.deduct_order_stock
        checkout_module.deduct_order_stock = boom
        try:
            with self.assertRaises(ValidationError):
                place_customer_order(
                    customer=self.customer,
                    checkout_token="tok-txn-fail",
                    fulfillment_type=FulfillmentType.DELIVERY,
                    payment_method=PaymentMethod.COD,
                    delivery_address_id=self.address.pk,
                    actor=self.user,
                )
        finally:
            checkout_module.deduct_order_stock = original

        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(StoreOrder.objects.count(), 0)
        self.assertEqual(OrderItem.objects.count(), 0)
        self.assertEqual(OrderStatusHistory.objects.count(), 0)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, original_stock)
        self.assertTrue(
            CartItem.objects.filter(
                cart__customer=self.customer,
                product=self.product,
            ).exists()
        )

    def test_second_customer_loses_last_unit_sequentially(self):
        customer_b, user_b = create_customer_with_user(
            user_data={
                "username": "txn-customer-b",
                "email": "txn-b@example.com",
                "first_name": "TxnB",
                "last_name": "Customer",
                "phone_number": "9000000502",
                "password": "secure-password-123",
            },
            registration_source=RegistrationSource.WEBSITE,
        )
        address_b = create_customer_delivery_address(
            customer=customer_b,
            data={
                "label": AddressLabel.HOME,
                "recipient_name": "TxnB",
                "phone_number": "9000000502",
                "line1": "2 Txn Road",
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
        # Leave exactly one sellable unit.
        self.product.stock_quantity = Decimal("1.000")
        self.product.save(update_fields=["stock_quantity", "updated_at"])
        CartItem.objects.filter(cart__customer=self.customer).update(
            quantity=Decimal("1.000")
        )
        add_product_to_cart(
            customer=customer_b,
            product_code=self.product.product_code,
            quantity=Decimal("1.000"),
        )

        winner = place_customer_order(
            customer=self.customer,
            checkout_token="tok-last-a",
            fulfillment_type=FulfillmentType.DELIVERY,
            payment_method=PaymentMethod.COD,
            delivery_address_id=self.address.pk,
            actor=self.user,
        )
        self.assertIsNotNone(winner.pk)

        with self.assertRaises(ValidationError) as ctx:
            place_customer_order(
                customer=customer_b,
                checkout_token="tok-last-b",
                fulfillment_type=FulfillmentType.DELIVERY,
                payment_method=PaymentMethod.COD,
                delivery_address_id=address_b.pk,
                actor=user_b,
            )
        self.assertIn("Txn Item", str(ctx.exception))
        self.assertEqual(Order.objects.count(), 1)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("0.000"))
        self.assertTrue(
            CartItem.objects.filter(cart__customer=customer_b).exists()
        )
        self.assertFalse(
            CartItem.objects.filter(cart__customer=self.customer).exists()
        )


@skipUnless(
    connection.vendor != "sqlite",
    "select_for_update() is a no-op on SQLite; concurrency needs PostgreSQL/MySQL.",
)
class CheckoutServiceConcurrencyTests(CheckoutTestMixin, TransactionTestCase):
    def setUp(self):
        self.store = self.create_store(name="Concurrent Store")
        self.product = self.create_public_product(
            store=self.store,
            name="Last Unit",
            stock=Decimal("1.000"),
        )
        self.customers = []
        for index in (1, 2):
            customer, user = create_customer_with_user(
                user_data={
                    "username": f"conc-{index}",
                    "email": f"conc-{index}@example.com",
                    "first_name": f"Conc{index}",
                    "last_name": "Customer",
                    "phone_number": f"90000006{index:02d}",
                    "password": "secure-password-123",
                },
                registration_source=RegistrationSource.WEBSITE,
            )
            address = create_customer_delivery_address(
                customer=customer,
                data={
                    "label": AddressLabel.HOME,
                    "recipient_name": f"Conc{index}",
                    "phone_number": f"90000006{index:02d}",
                    "line1": f"{index} Conc Street",
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
            add_product_to_cart(
                customer=customer,
                product_code=self.product.product_code,
                quantity=Decimal("1.000"),
            )
            self.customers.append((customer, user, address))

    def test_two_customers_cannot_both_buy_last_unit(self):
        results = []

        def attempt(customer, user, address, token):
            try:
                order = place_customer_order(
                    customer=customer,
                    checkout_token=token,
                    fulfillment_type=FulfillmentType.DELIVERY,
                    payment_method=PaymentMethod.COD,
                    delivery_address_id=address.pk,
                    actor=user,
                )
                results.append(("ok", order.pk))
            except ValidationError:
                results.append(("rejected", None))
            finally:
                connection.close()

        threads = [
            Thread(
                target=attempt,
                args=(*self.customers[0], "tok-conc-a"),
            ),
            Thread(
                target=attempt,
                args=(*self.customers[1], "tok-conc-b"),
            ),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("0.000"))
        self.assertEqual(sum(1 for status, _ in results if status == "ok"), 1)
        self.assertEqual(sum(1 for status, _ in results if status == "rejected"), 1)
        self.assertEqual(Order.objects.count(), 1)
        self.assertGreaterEqual(self.product.stock_quantity, Decimal("0.000"))

    def test_double_click_same_token_does_not_duplicate_order(self):
        customer, user, address = self.customers[0]
        # Restock so only idempotency is under test.
        record_manual_stock_in(
            product=self.product,
            store=self.store,
            quantity=Decimal("5.000"),
            actor=None,
            reason="Concurrency restock",
        )
        results = []

        def attempt():
            try:
                order = place_customer_order(
                    customer=customer,
                    checkout_token="tok-double-click",
                    fulfillment_type=FulfillmentType.DELIVERY,
                    payment_method=PaymentMethod.COD,
                    delivery_address_id=address.pk,
                    actor=user,
                )
                results.append(order.pk)
            except ValidationError:
                results.append(None)
            finally:
                connection.close()

        threads = [Thread(target=attempt), Thread(target=attempt)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(Order.objects.filter(checkout_token="tok-double-click").count(), 1)
        successful = [pk for pk in results if pk is not None]
        # Both retries must resolve to the same order (idempotent, not empty-cart error).
        self.assertEqual(len(successful), 2)
        self.assertEqual(len(set(successful)), 1)
        order = Order.objects.get()
        item = OrderItem.objects.get(store_order__order=order)
        self.assertEqual(
            InventoryTransaction.objects.filter(
                product=self.product,
                transaction_type=InventoryTransactionType.STOCK_OUT,
                reference=f"order-item:{item.pk}:deduct",
            ).count(),
            1,
        )
