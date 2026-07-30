"""
Stock-integrity checklist tests.

Covers balance math, ledger history, store isolation, portal guards,
concurrency, and rollback behaviour required for Phase 5 inventory.
"""

from datetime import timedelta
from decimal import Decimal
from threading import Thread
from unittest import mock, skipUnless

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role
from catalog.models import Product, ProductCategory, ProductStatus
from locations.models import Address
from stores.models import Store, StoreCategory, StoreStatus, StoreType, StoreUser

from .models import InventoryTransaction, InventoryTransactionType
from .services import (
    initialize_opening_stock_from_catalogue,
    record_adjustment_in,
    record_adjustment_out,
    record_customer_return,
    record_damaged_stock,
    record_expired_stock,
    record_manual_stock_in,
    record_manual_stock_out,
    record_opening_stock,
    record_purchase_stock_in,
    record_supplier_return,
)

User = get_user_model()


class StockIntegrityMixin:
    def create_address(self, **overrides):
        defaults = {
            "line1": "Integrity Road",
            "city": "Bengaluru",
            "state": "Karnataka",
            "postal_code": "560001",
            "latitude": Decimal("12.971600"),
            "longitude": Decimal("77.594600"),
        }
        defaults.update(overrides)
        return Address.objects.create(**defaults)

    def create_store(self, **overrides):
        if "address" not in overrides:
            overrides["address"] = self.create_address()
        if "category" not in overrides:
            overrides["category"] = StoreCategory.objects.create(
                name=f"IntCat-{StoreCategory.objects.count() + 1}"
            )
        defaults = {
            "name": "Integrity Store",
            "store_type": StoreType.OWN_STORE,
            "status": StoreStatus.ACTIVE,
            "is_active": True,
            "commission_percentage": Decimal("5.00"),
        }
        defaults.update(overrides)
        return Store.objects.create(**defaults)

    def create_actor(self, username="integrity-actor", **overrides):
        defaults = {
            "username": username,
            "email": f"{username}@example.com",
            "password": "secure-password-123",
            "role": Role.ADMIN,
            "is_staff": True,
        }
        defaults.update(overrides)
        return User.objects.create_user(**defaults)

    def create_product(self, store=None, **overrides):
        if store is None:
            store = self.create_store()
        if "category" not in overrides:
            overrides["category"] = ProductCategory.objects.create(
                name=f"IntGoods-{ProductCategory.objects.count() + 1}"
            )
        defaults = {
            "store": store,
            "name": "Integrity Product",
            "sku": f"INT-{Product.objects.count() + 1}",
            "store_price": Decimal("50.00"),
            "status": ProductStatus.APPROVED,
            "stock_quantity": Decimal("0.000"),
        }
        defaults.update(overrides)
        product = Product(**defaults)
        product.full_clean()
        product.save()
        return product

    def create_store_user(
        self, store, username, *, can_manage_inventory=True, is_primary=True
    ):
        user = User.objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password="secure-password-123",
            role=Role.STORE_USER,
        )
        StoreUser.objects.create(
            store=store,
            user=user,
            is_primary=is_primary,
            is_active=True,
            can_manage_inventory=can_manage_inventory,
            designation="Clerk",
        )
        return user


class StockIntegrityServiceTests(StockIntegrityMixin, TestCase):
    """Service-layer balance and ledger integrity (items 1–13, 19–20)."""

    def setUp(self):
        self.store = self.create_store()
        self.actor = self.create_actor()
        self.product = self.create_product(store=self.store)

    def test_01_stock_in_increases_balance(self):
        txn = record_manual_stock_in(
            product=self.product,
            store=self.store,
            quantity=Decimal("7.500"),
            actor=self.actor,
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("7.500"))
        self.assertEqual(txn.transaction_type, InventoryTransactionType.STOCK_IN)
        self.assertEqual(txn.previous_quantity, Decimal("0.000"))
        self.assertEqual(txn.new_quantity, Decimal("7.500"))

    def test_02_stock_out_decreases_balance(self):
        record_manual_stock_in(
            product=self.product,
            store=self.store,
            quantity=Decimal("10.000"),
            actor=self.actor,
        )
        txn = record_manual_stock_out(
            product=self.product,
            store=self.store,
            quantity=Decimal("4.000"),
            actor=self.actor,
            reason="Issued to floor",
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("6.000"))
        self.assertEqual(txn.transaction_type, InventoryTransactionType.STOCK_OUT)
        self.assertEqual(txn.previous_quantity, Decimal("10.000"))
        self.assertEqual(txn.new_quantity, Decimal("6.000"))

    def test_03_stock_out_greater_than_available_is_rejected(self):
        record_manual_stock_in(
            product=self.product,
            store=self.store,
            quantity=Decimal("3.000"),
            actor=self.actor,
        )
        with self.assertRaises(ValidationError) as ctx:
            record_manual_stock_out(
                product=self.product,
                store=self.store,
                quantity=Decimal("5.000"),
                actor=self.actor,
                reason="Too much",
            )
        self.assertIn("Insufficient stock", str(ctx.exception))
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("3.000"))

    def test_04_failed_stock_out_creates_no_transaction(self):
        record_manual_stock_in(
            product=self.product,
            store=self.store,
            quantity=Decimal("2.000"),
            actor=self.actor,
        )
        before_count = InventoryTransaction.objects.count()
        with self.assertRaises(ValidationError):
            record_manual_stock_out(
                product=self.product,
                store=self.store,
                quantity=Decimal("9.000"),
                actor=self.actor,
                reason="Oversell attempt",
            )
        self.assertEqual(InventoryTransaction.objects.count(), before_count)
        self.assertFalse(
            InventoryTransaction.objects.filter(
                transaction_type=InventoryTransactionType.STOCK_OUT
            ).exists()
        )

    def test_05_purchase_creation_increases_stock_exactly_once(self):
        before = self.product.stock_quantity
        entry, txns = record_purchase_stock_in(
            store=self.store,
            supplier_name="Integrity Supplier",
            entry_date=timezone.localdate(),
            actor=self.actor,
            lines=[
                {
                    "product": self.product,
                    "quantity": Decimal("6.000"),
                    "unit_cost": Decimal("8.00"),
                }
            ],
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, before + Decimal("6.000"))
        self.assertEqual(len(txns), 1)
        self.assertEqual(
            InventoryTransaction.objects.filter(
                purchase_entry=entry,
                transaction_type=InventoryTransactionType.PURCHASE,
            ).count(),
            1,
        )
        self.assertEqual(txns[0].quantity, Decimal("6.000"))
        self.assertEqual(txns[0].previous_quantity, before)
        self.assertEqual(txns[0].new_quantity, before + Decimal("6.000"))

    def test_06_damaged_stock_reduces_available_stock(self):
        record_opening_stock(
            product=self.product,
            store=self.store,
            quantity=Decimal("20.000"),
            actor=self.actor,
        )
        txn = record_damaged_stock(
            product=self.product,
            store=self.store,
            quantity=Decimal("3.000"),
            actor=self.actor,
            reason="Crushed packaging",
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("17.000"))
        self.assertEqual(txn.transaction_type, InventoryTransactionType.DAMAGED)
        self.assertEqual(txn.previous_quantity, Decimal("20.000"))
        self.assertEqual(txn.new_quantity, Decimal("17.000"))

    def test_07_expired_stock_reduces_available_stock(self):
        record_opening_stock(
            product=self.product,
            store=self.store,
            quantity=Decimal("15.000"),
            actor=self.actor,
        )
        txn = record_expired_stock(
            product=self.product,
            store=self.store,
            quantity=Decimal("4.000"),
            actor=self.actor,
            reason="Past best-before",
            expiry_date=timezone.localdate() - timedelta(days=1),
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("11.000"))
        self.assertEqual(txn.transaction_type, InventoryTransactionType.EXPIRED)

    def test_08_customer_return_increases_stock(self):
        record_opening_stock(
            product=self.product,
            store=self.store,
            quantity=Decimal("5.000"),
            actor=self.actor,
        )
        txn = record_customer_return(
            product=self.product,
            store=self.store,
            quantity=Decimal("2.000"),
            actor=self.actor,
            reason="Customer returned unopened item",
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("7.000"))
        self.assertEqual(
            txn.transaction_type, InventoryTransactionType.CUSTOMER_RETURN
        )
        self.assertEqual(txn.previous_quantity, Decimal("5.000"))
        self.assertEqual(txn.new_quantity, Decimal("7.000"))

    def test_09_supplier_return_decreases_stock(self):
        record_opening_stock(
            product=self.product,
            store=self.store,
            quantity=Decimal("8.000"),
            actor=self.actor,
        )
        txn = record_supplier_return(
            product=self.product,
            store=self.store,
            quantity=Decimal("3.000"),
            actor=self.actor,
            reason="Returned defective batch",
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("5.000"))
        self.assertEqual(
            txn.transaction_type, InventoryTransactionType.SUPPLIER_RETURN
        )
        self.assertEqual(txn.previous_quantity, Decimal("8.000"))
        self.assertEqual(txn.new_quantity, Decimal("5.000"))

    def test_10_adjustment_requires_a_reason(self):
        record_manual_stock_in(
            product=self.product,
            store=self.store,
            quantity=Decimal("5.000"),
            actor=self.actor,
        )
        with self.assertRaises(ValidationError) as ctx:
            record_adjustment_out(
                product=self.product,
                store=self.store,
                quantity=Decimal("1.000"),
                actor=self.actor,
                reason="",
            )
        self.assertIn("reason", ctx.exception.message_dict)
        with self.assertRaises(ValidationError):
            record_adjustment_in(
                product=self.product,
                store=self.store,
                quantity=Decimal("1.000"),
                actor=self.actor,
                reason="   ",
            )
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("5.000"))
        self.assertEqual(
            InventoryTransaction.objects.filter(
                transaction_type__in=(
                    InventoryTransactionType.ADJUSTMENT_IN,
                    InventoryTransactionType.ADJUSTMENT_OUT,
                )
            ).count(),
            0,
        )

    def test_11_stock_quantity_cannot_become_negative(self):
        record_manual_stock_in(
            product=self.product,
            store=self.store,
            quantity=Decimal("1.000"),
            actor=self.actor,
        )
        for qty in (Decimal("1.001"), Decimal("100.000")):
            with self.assertRaises(ValidationError):
                record_manual_stock_out(
                    product=self.product,
                    store=self.store,
                    quantity=qty,
                    actor=self.actor,
                    reason="Would go negative",
                )
        self.product.refresh_from_db()
        self.assertGreaterEqual(self.product.stock_quantity, Decimal("0"))
        self.assertEqual(self.product.stock_quantity, Decimal("1.000"))

    def test_12_previous_and_new_quantity_are_correct(self):
        first = record_manual_stock_in(
            product=self.product,
            store=self.store,
            quantity=Decimal("12.000"),
            actor=self.actor,
        )
        self.assertEqual(first.previous_quantity, Decimal("0.000"))
        self.assertEqual(first.new_quantity, Decimal("12.000"))
        self.assertEqual(first.quantity, Decimal("12.000"))

        second = record_manual_stock_out(
            product=self.product,
            store=self.store,
            quantity=Decimal("5.000"),
            actor=self.actor,
            reason="Partial issue",
        )
        self.assertEqual(second.previous_quantity, Decimal("12.000"))
        self.assertEqual(second.new_quantity, Decimal("7.000"))
        self.assertEqual(second.quantity, Decimal("5.000"))
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, second.new_quantity)

    def test_13_transaction_actor_is_recorded(self):
        txn = record_manual_stock_in(
            product=self.product,
            store=self.store,
            quantity=Decimal("2.000"),
            actor=self.actor,
        )
        self.assertEqual(txn.created_by_id, self.actor.pk)
        out = record_manual_stock_out(
            product=self.product,
            store=self.store,
            quantity=Decimal("1.000"),
            actor=self.actor,
            reason="Actor check",
        )
        self.assertEqual(out.created_by_id, self.actor.pk)

    def test_19_service_failure_rolls_back_balance_and_history(self):
        record_manual_stock_in(
            product=self.product,
            store=self.store,
            quantity=Decimal("10.000"),
            actor=self.actor,
        )
        before_balance = Product.objects.get(pk=self.product.pk).stock_quantity
        before_history = InventoryTransaction.objects.count()

        with mock.patch(
            "inventory.services._create_transaction_row",
            side_effect=ValidationError({"notes": "Simulated ledger write failure"}),
        ):
            with self.assertRaises(ValidationError):
                record_manual_stock_out(
                    product=self.product,
                    store=self.store,
                    quantity=Decimal("2.000"),
                    actor=self.actor,
                    reason="Should roll back",
                )

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, before_balance)
        self.assertEqual(InventoryTransaction.objects.count(), before_history)
        self.assertFalse(
            InventoryTransaction.objects.filter(
                transaction_type=InventoryTransactionType.STOCK_OUT
            ).exists()
        )

    def test_20_repeated_opening_initialization_creates_no_duplicate_history(self):
        self.product.stock_quantity = Decimal("9.000")
        self.product.save(update_fields=["stock_quantity"])
        first = initialize_opening_stock_from_catalogue(actor=self.actor)
        self.assertGreaterEqual(first["converted"], 1)
        opening_count = InventoryTransaction.objects.filter(
            product=self.product,
            transaction_type=InventoryTransactionType.OPENING,
        ).count()
        self.assertEqual(opening_count, 1)
        balance_after = Product.objects.get(pk=self.product.pk).stock_quantity

        second = initialize_opening_stock_from_catalogue(actor=self.actor)
        self.assertEqual(second["converted"], 0)
        self.assertEqual(
            InventoryTransaction.objects.filter(
                product=self.product,
                transaction_type=InventoryTransactionType.OPENING,
            ).count(),
            1,
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, balance_after)


class StockIntegrityPortalIsolationTests(StockIntegrityMixin, TestCase):
    """Store portal isolation and membership guards (items 14–17)."""

    def setUp(self):
        self.client = Client()
        self.store_a = self.create_store(name="Integrity Store A")
        self.store_b = self.create_store(name="Integrity Store B")
        self.product_a = self.create_product(
            store=self.store_a,
            sku="ISO-A",
            name="Store A Item",
            stock_quantity=Decimal("10.000"),
        )
        self.product_b = self.create_product(
            store=self.store_b,
            sku="ISO-B",
            name="Store B Item",
            stock_quantity=Decimal("10.000"),
        )
        self.manager_a = self.create_store_user(
            self.store_a, "iso-mgr-a", can_manage_inventory=True, is_primary=True
        )
        self.viewer_a = self.create_store_user(
            self.store_a,
            "iso-viewer-a",
            can_manage_inventory=False,
            is_primary=False,
        )
        self.manager_b = self.create_store_user(
            self.store_b, "iso-mgr-b", can_manage_inventory=True, is_primary=True
        )
        self.stock_in_a = reverse(
            "inventory:store_product_stock_in",
            kwargs={"product_id": self.product_a.pk},
        )
        self.stock_in_b = reverse(
            "inventory:store_product_stock_in",
            kwargs={"product_id": self.product_b.pk},
        )
        self.detail_b = reverse(
            "inventory:store_product_inventory",
            kwargs={"product_id": self.product_b.pk},
        )

    def test_14_store_a_cannot_access_store_b_inventory(self):
        self.client.login(username="iso-mgr-a", password="secure-password-123")
        list_response = self.client.get(reverse("inventory:store_inventory_list"))
        self.assertEqual(list_response.status_code, 200)
        self.assertContains(list_response, self.product_a.name)
        self.assertNotContains(list_response, self.product_b.name)
        self.assertEqual(self.client.get(self.detail_b).status_code, 404)
        self.assertEqual(self.client.get(self.stock_in_b).status_code, 404)

    def test_15_store_a_cannot_manipulate_store_b_via_modified_post(self):
        self.client.login(username="iso-mgr-a", password="secure-password-123")
        before_b = self.product_b.stock_quantity
        before_txns = InventoryTransaction.objects.filter(product=self.product_b).count()
        response = self.client.post(
            self.stock_in_b,
            {
                "quantity": "5.000",
                "store": self.store_b.pk,
                "store_id": self.store_b.pk,
                "product": self.product_b.pk,
            },
        )
        self.assertEqual(response.status_code, 404)
        self.product_b.refresh_from_db()
        self.assertEqual(self.product_b.stock_quantity, before_b)
        self.assertEqual(
            InventoryTransaction.objects.filter(product=self.product_b).count(),
            before_txns,
        )

    def test_16_suspended_store_cannot_change_stock(self):
        self.client.login(username="iso-mgr-a", password="secure-password-123")
        before = self.product_a.stock_quantity
        # Confirm write works while active.
        ok = self.client.post(self.stock_in_a, {"quantity": "1.000"})
        self.assertEqual(ok.status_code, 302)
        self.product_a.refresh_from_db()
        self.assertEqual(self.product_a.stock_quantity, before + Decimal("1.000"))

        self.store_a.status = StoreStatus.SUSPENDED
        self.store_a.save(update_fields=["status"])
        mid = self.product_a.stock_quantity
        blocked = self.client.post(self.stock_in_a, {"quantity": "2.000"})
        self.assertEqual(blocked.status_code, 403)
        self.product_a.refresh_from_db()
        self.assertEqual(self.product_a.stock_quantity, mid)
        self.assertFalse(
            InventoryTransaction.objects.filter(
                product=self.product_a,
                quantity=Decimal("2.000"),
            ).exists()
        )

    def test_17_store_user_without_can_manage_inventory_cannot_change_stock(self):
        self.client.login(username="iso-viewer-a", password="secure-password-123")
        before = self.product_a.stock_quantity
        response = self.client.post(self.stock_in_a, {"quantity": "3.000"})
        self.assertEqual(response.status_code, 403)
        self.product_a.refresh_from_db()
        self.assertEqual(self.product_a.stock_quantity, before)
        self.assertEqual(
            InventoryTransaction.objects.filter(product=self.product_a).count(),
            0,
        )


@skipUnless(
    connection.vendor != "sqlite",
    "select_for_update() is a no-op on SQLite; concurrency needs PostgreSQL/MySQL.",
)
class StockIntegrityConcurrencyTests(StockIntegrityMixin, TransactionTestCase):
    """Real-transaction concurrency coverage (item 18)."""

    def setUp(self):
        self.store = self.create_store(name="Concurrent Store")
        self.actor = self.create_actor(username="concurrent-actor")
        self.product = self.create_product(
            store=self.store,
            sku="CONC-1",
            stock_quantity=Decimal("0.000"),
        )
        record_opening_stock(
            product=self.product,
            store=self.store,
            quantity=Decimal("5.000"),
            actor=self.actor,
        )

    def test_18_concurrent_stock_outs_cannot_oversell(self):
        results = []

        def attempt_out():
            try:
                record_manual_stock_out(
                    product=self.product,
                    store=self.store,
                    quantity=Decimal("5.000"),
                    actor=self.actor,
                    reason="Concurrent oversell race",
                )
                results.append("ok")
            except ValidationError:
                results.append("rejected")
            finally:
                connection.close()

        threads = [Thread(target=attempt_out), Thread(target=attempt_out)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("0.000"))
        self.assertGreaterEqual(self.product.stock_quantity, Decimal("0"))
        self.assertEqual(results.count("ok"), 1)
        self.assertEqual(results.count("rejected"), 1)
        self.assertEqual(
            InventoryTransaction.objects.filter(
                product=self.product,
                transaction_type=InventoryTransactionType.STOCK_OUT,
            ).count(),
            1,
        )
