from datetime import timedelta
from decimal import Decimal
from threading import Thread
from unittest import mock, skipUnless

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from accounts.models import Role
from catalog.models import Product, ProductCategory, ProductStatus
from locations.models import Address
from stores.models import Store, StoreCategory, StoreStatus, StoreType

from .models import (
    InventoryDirection,
    InventoryTransaction,
    InventoryTransactionType,
    PurchaseEntry,
    PurchaseEntryLine,
    PurchaseEntryStatus,
)
from .services import (
    apply_stock_movement,
    cancel_purchase_entry,
    confirm_purchase_entry,
    convert_existing_opening_stock,
    create_purchase_entry,
    generate_purchase_entry_number,
    generate_transaction_number,
    initialize_opening_stock_from_catalogue,
    products_needing_opening_stock_initialization,
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


class InventoryTestMixin:
    def create_address(self, **overrides):
        defaults = {
            "line1": "12 MG Road",
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
                name=f"StoreCat-{StoreCategory.objects.count() + 1}"
            )
        defaults = {
            "name": "Zoop Mart",
            "store_type": StoreType.OWN_STORE,
            "status": StoreStatus.ACTIVE,
            "is_active": True,
            "commission_percentage": Decimal("5.00"),
        }
        defaults.update(overrides)
        return Store.objects.create(**defaults)

    def create_actor(self, username="inventory-actor", **overrides):
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
                name=f"Cat-{ProductCategory.objects.count() + 1}"
            )
        defaults = {
            "store": store,
            "name": "Sample Product",
            "sku": f"SKU-{Product.objects.count() + 1}",
            "store_price": Decimal("100.00"),
            "status": ProductStatus.APPROVED,
            "stock_quantity": Decimal("0.000"),
        }
        defaults.update(overrides)
        product = Product(**defaults)
        product.full_clean()
        product.save()
        return product


class InventoryModelTests(InventoryTestMixin, TestCase):
    def setUp(self):
        self.store = self.create_store()
        self.actor = self.create_actor()
        self.product = self.create_product(store=self.store)

    def test_transaction_type_direction_mapping(self):
        self.assertEqual(
            InventoryTransactionType.OPENING.label,
            "Opening Stock",
        )
        self.assertEqual(InventoryDirection.IN, "IN")
        self.assertEqual(InventoryDirection.OUT, "OUT")

    def test_inventory_transaction_is_immutable_after_create(self):
        txn = record_manual_stock_in(
            product=self.product,
            store=self.store,
            quantity=Decimal("5.000"),
            actor=self.actor,
        )
        original_reason = txn.reason
        original_quantity = txn.quantity
        txn.reason = "silently rewritten"
        txn.quantity = Decimal("99.000")
        with self.assertRaises(ValidationError) as ctx:
            txn.save()
        self.assertIn("immutable", str(ctx.exception).lower())
        txn.refresh_from_db()
        self.assertEqual(txn.reason, original_reason)
        self.assertEqual(txn.quantity, original_quantity)

    def test_inventory_transaction_cannot_be_deleted(self):
        txn = record_manual_stock_in(
            product=self.product,
            store=self.store,
            quantity=Decimal("2.000"),
            actor=self.actor,
        )
        with self.assertRaises(ValidationError) as ctx:
            txn.delete()
        self.assertIn("immutable", str(ctx.exception).lower())
        self.assertTrue(
            InventoryTransaction.objects.filter(pk=txn.pk).exists()
        )

    def test_queryset_update_and_delete_cannot_rewrite_history(self):
        txn = record_manual_stock_in(
            product=self.product,
            store=self.store,
            quantity=Decimal("4.000"),
            actor=self.actor,
            reason="Original receipt",
        )
        original_quantity = txn.quantity
        original_reason = txn.reason

        with self.assertRaises(ValidationError):
            InventoryTransaction.objects.filter(pk=txn.pk).update(
                quantity=Decimal("50.000"),
                reason="rewritten",
            )
        with self.assertRaises(ValidationError):
            InventoryTransaction.objects.filter(pk=txn.pk).delete()
        with self.assertRaises(ValidationError):
            InventoryTransaction.objects.bulk_update(
                [txn], fields=["quantity", "reason"]
            )

        txn.refresh_from_db()
        self.assertEqual(txn.quantity, original_quantity)
        self.assertEqual(txn.reason, original_reason)
        self.assertEqual(InventoryTransaction.objects.count(), 1)

    def test_correction_uses_new_adjustment_transaction(self):
        original = record_manual_stock_in(
            product=self.product,
            store=self.store,
            quantity=Decimal("10.000"),
            actor=self.actor,
            reason="Received ten",
        )
        snapshot = {
            "quantity": original.quantity,
            "previous_quantity": original.previous_quantity,
            "new_quantity": original.new_quantity,
            "reason": original.reason,
            "transaction_number": original.transaction_number,
        }

        correction = record_adjustment_out(
            product=self.product,
            store=self.store,
            quantity=Decimal("3.000"),
            actor=self.actor,
            reason="Correct overstated receipt",
        )
        self.assertNotEqual(correction.pk, original.pk)
        self.assertEqual(
            correction.transaction_type,
            InventoryTransactionType.ADJUSTMENT_OUT,
        )

        original.refresh_from_db()
        self.assertEqual(original.quantity, snapshot["quantity"])
        self.assertEqual(original.previous_quantity, snapshot["previous_quantity"])
        self.assertEqual(original.new_quantity, snapshot["new_quantity"])
        self.assertEqual(original.reason, snapshot["reason"])
        self.assertEqual(
            original.transaction_number, snapshot["transaction_number"]
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("7.000"))
        self.assertEqual(InventoryTransaction.objects.count(), 2)

    def test_admin_is_read_only_and_blocks_delete(self):
        from django.contrib.admin.sites import AdminSite

        from .admin import InventoryTransactionAdmin

        txn = record_manual_stock_in(
            product=self.product,
            store=self.store,
            quantity=Decimal("1.000"),
            actor=self.actor,
        )
        admin_obj = InventoryTransactionAdmin(
            InventoryTransaction, AdminSite()
        )
        request = type("Req", (), {"user": self.actor})()
        self.assertFalse(admin_obj.has_add_permission(request))
        self.assertFalse(admin_obj.has_change_permission(request))
        self.assertFalse(admin_obj.has_change_permission(request, obj=txn))
        self.assertFalse(admin_obj.has_delete_permission(request))
        self.assertFalse(admin_obj.has_delete_permission(request, obj=txn))
        self.assertIsNone(admin_obj.actions)
        readonly = set(admin_obj.get_readonly_fields(request, obj=txn))
        self.assertIn("quantity", readonly)
        self.assertIn("previous_quantity", readonly)
        self.assertIn("new_quantity", readonly)
        self.assertIn("transaction_number", readonly)

    def test_no_transaction_edit_or_delete_urls(self):
        from django.urls import NoReverseMatch, reverse

        for name in (
            "inventory:management_transaction_edit",
            "inventory:management_transaction_delete",
            "inventory:store_transaction_edit",
            "inventory:store_transaction_delete",
        ):
            with self.assertRaises(NoReverseMatch):
                reverse(name)

    def test_product_must_belong_to_store_on_transaction_clean(self):
        other_store = self.create_store(name="Other Store")
        txn = InventoryTransaction(
            store=other_store,
            product=self.product,
            transaction_type=InventoryTransactionType.STOCK_IN,
            direction=InventoryDirection.IN,
            quantity=Decimal("1.000"),
            previous_quantity=Decimal("0.000"),
            new_quantity=Decimal("1.000"),
            created_by=self.actor,
        )
        with self.assertRaises(ValidationError) as ctx:
            txn.full_clean()
        self.assertIn("product", ctx.exception.message_dict)

    def test_manufacturing_and_expiry_date_validation(self):
        txn = InventoryTransaction(
            store=self.store,
            product=self.product,
            transaction_type=InventoryTransactionType.STOCK_IN,
            direction=InventoryDirection.IN,
            quantity=Decimal("1.000"),
            previous_quantity=Decimal("0.000"),
            new_quantity=Decimal("1.000"),
            manufacturing_date=timezone.localdate() + timedelta(days=1),
            created_by=self.actor,
        )
        with self.assertRaises(ValidationError) as ctx:
            txn.full_clean()
        self.assertIn("manufacturing_date", ctx.exception.message_dict)

        txn.manufacturing_date = timezone.localdate() - timedelta(days=10)
        txn.expiry_date = timezone.localdate() - timedelta(days=20)
        with self.assertRaises(ValidationError) as ctx:
            txn.full_clean()
        self.assertIn("expiry_date", ctx.exception.message_dict)

    def test_reason_required_for_stock_out_types(self):
        txn = InventoryTransaction(
            store=self.store,
            product=self.product,
            transaction_type=InventoryTransactionType.DAMAGED,
            direction=InventoryDirection.OUT,
            quantity=Decimal("1.000"),
            previous_quantity=Decimal("5.000"),
            new_quantity=Decimal("4.000"),
            reason="",
            created_by=self.actor,
        )
        with self.assertRaises(ValidationError) as ctx:
            txn.full_clean()
        self.assertIn("reason", ctx.exception.message_dict)

    def test_purchase_entry_line_rejects_foreign_product(self):
        other_store = self.create_store(name="Foreign")
        other_product = self.create_product(store=other_store, sku="OTHER-1")
        entry = PurchaseEntry(
            store=self.store,
            supplier_name="Supplier",
            entry_date=timezone.localdate(),
            created_by=self.actor,
        )
        entry.full_clean()
        entry.save()
        line = PurchaseEntryLine(
            purchase_entry=entry,
            product=other_product,
            quantity=Decimal("1.000"),
            unit_cost=Decimal("10.00"),
        )
        with self.assertRaises(ValidationError) as ctx:
            line.full_clean()
        self.assertIn("product", ctx.exception.message_dict)

    def test_purchase_line_calculates_line_total(self):
        entry = create_purchase_entry(
            store=self.store,
            supplier_name="Supplier Co",
            entry_date=timezone.localdate(),
            created_by=self.actor,
            lines=[
                {
                    "product": self.product,
                    "quantity": Decimal("3.000"),
                    "unit_cost": Decimal("12.50"),
                }
            ],
        )
        line = entry.lines.get()
        self.assertEqual(line.line_total, Decimal("37.50"))
        self.assertEqual(entry.total_cost, Decimal("37.50"))

    def test_unique_number_generators(self):
        tx_number = generate_transaction_number()
        pe_number = generate_purchase_entry_number()
        self.assertTrue(tx_number.startswith("TX-"))
        self.assertTrue(pe_number.startswith("PE-"))


class InventoryServiceTests(InventoryTestMixin, TestCase):
    def setUp(self):
        self.store = self.create_store()
        self.actor = self.create_actor()
        self.product = self.create_product(store=self.store)

    def test_opening_stock_updates_balance_and_creates_transaction(self):
        txn = record_opening_stock(
            product=self.product,
            store=self.store,
            quantity=Decimal("10.000"),
            actor=self.actor,
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("10.000"))
        self.assertEqual(txn.transaction_type, InventoryTransactionType.OPENING)
        self.assertEqual(txn.direction, InventoryDirection.IN)
        self.assertEqual(txn.previous_quantity, Decimal("0.000"))
        self.assertEqual(txn.new_quantity, Decimal("10.000"))
        self.assertEqual(InventoryTransaction.objects.count(), 1)

    def test_opening_stock_only_once(self):
        record_opening_stock(
            product=self.product,
            store=self.store,
            quantity=Decimal("5.000"),
            actor=self.actor,
        )
        with self.assertRaises(ValidationError):
            record_opening_stock(
                product=self.product,
                store=self.store,
                quantity=Decimal("2.000"),
                actor=self.actor,
            )
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("5.000"))
        self.assertEqual(InventoryTransaction.objects.count(), 1)

    def test_convert_existing_opening_stock_preserves_balance(self):
        self.product.stock_quantity = Decimal("25.000")
        self.product.save(update_fields=["stock_quantity"])
        txn = convert_existing_opening_stock(
            product=self.product,
            store=self.store,
            actor=self.actor,
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("25.000"))
        self.assertEqual(txn.previous_quantity, Decimal("0.000"))
        self.assertEqual(txn.new_quantity, Decimal("25.000"))
        self.assertEqual(txn.quantity, Decimal("25.000"))
        self.assertTrue(txn.is_system_generated)

    def test_reject_zero_and_negative_quantity(self):
        for bad in (Decimal("0"), Decimal("-1.000")):
            with self.assertRaises(ValidationError):
                record_manual_stock_in(
                    product=self.product,
                    store=self.store,
                    quantity=bad,
                    actor=self.actor,
                )
        self.assertEqual(InventoryTransaction.objects.count(), 0)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("0.000"))

    def test_manual_stock_in_and_out(self):
        record_manual_stock_in(
            product=self.product,
            store=self.store,
            quantity=Decimal("8.000"),
            actor=self.actor,
        )
        txn = record_manual_stock_out(
            product=self.product,
            store=self.store,
            quantity=Decimal("3.000"),
            actor=self.actor,
            reason="Issued to kitchen",
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("5.000"))
        self.assertEqual(txn.previous_quantity, Decimal("8.000"))
        self.assertEqual(txn.new_quantity, Decimal("5.000"))
        self.assertEqual(txn.direction, InventoryDirection.OUT)

    def test_prevent_negative_stock(self):
        record_manual_stock_in(
            product=self.product,
            store=self.store,
            quantity=Decimal("2.000"),
            actor=self.actor,
        )
        with self.assertRaises(ValidationError):
            record_manual_stock_out(
                product=self.product,
                store=self.store,
                quantity=Decimal("5.000"),
                actor=self.actor,
                reason="Too much",
            )
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("2.000"))
        self.assertEqual(InventoryTransaction.objects.count(), 1)

    def test_failed_movement_creates_no_transaction(self):
        other_store = self.create_store(name="Mismatch Store")
        with self.assertRaises(ValidationError):
            record_manual_stock_in(
                product=self.product,
                store=other_store,
                quantity=Decimal("1.000"),
                actor=self.actor,
            )
        self.assertEqual(InventoryTransaction.objects.count(), 0)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("0.000"))

    def test_adjustment_in_and_out_require_reason(self):
        record_manual_stock_in(
            product=self.product,
            store=self.store,
            quantity=Decimal("10.000"),
            actor=self.actor,
        )
        with self.assertRaises(ValidationError):
            record_adjustment_out(
                product=self.product,
                store=self.store,
                quantity=Decimal("1.000"),
                actor=self.actor,
                reason="",
            )
        record_adjustment_in(
            product=self.product,
            store=self.store,
            quantity=Decimal("1.500"),
            actor=self.actor,
            reason="Cycle count gain",
        )
        record_adjustment_out(
            product=self.product,
            store=self.store,
            quantity=Decimal("0.500"),
            actor=self.actor,
            reason="Cycle count loss",
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("11.000"))

    def test_damaged_and_expired_reduce_stock(self):
        record_opening_stock(
            product=self.product,
            store=self.store,
            quantity=Decimal("20.000"),
            actor=self.actor,
        )
        record_damaged_stock(
            product=self.product,
            store=self.store,
            quantity=Decimal("2.000"),
            actor=self.actor,
            reason="Broken packaging",
        )
        record_expired_stock(
            product=self.product,
            store=self.store,
            quantity=Decimal("3.000"),
            actor=self.actor,
            reason="Past expiry",
            expiry_date=timezone.localdate() - timedelta(days=1),
            manufacturing_date=timezone.localdate() - timedelta(days=30),
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("15.000"))

    def test_customer_and_supplier_return(self):
        record_opening_stock(
            product=self.product,
            store=self.store,
            quantity=Decimal("10.000"),
            actor=self.actor,
        )
        record_customer_return(
            product=self.product,
            store=self.store,
            quantity=Decimal("2.000"),
            actor=self.actor,
            reason="Customer returned unopened item",
        )
        record_supplier_return(
            product=self.product,
            store=self.store,
            quantity=Decimal("1.000"),
            actor=self.actor,
            reason="Returned defective batch to supplier",
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("11.000"))
        types = set(
            InventoryTransaction.objects.values_list("transaction_type", flat=True)
        )
        self.assertIn(InventoryTransactionType.CUSTOMER_RETURN, types)
        self.assertIn(InventoryTransactionType.SUPPLIER_RETURN, types)

    def test_purchase_stock_in_confirms_and_updates_total_cost(self):
        product_b = self.create_product(store=self.store, sku="SKU-B", name="B")
        entry, txns = record_purchase_stock_in(
            store=self.store,
            supplier_name="Fresh Farms",
            entry_date=timezone.localdate(),
            actor=self.actor,
            supplier_invoice_number="INV-100",
            lines=[
                {
                    "product": self.product,
                    "quantity": Decimal("4.000"),
                    "unit_cost": Decimal("10.00"),
                },
                {
                    "product": product_b,
                    "quantity": Decimal("2.000"),
                    "unit_cost": Decimal("7.50"),
                },
            ],
        )
        self.assertEqual(entry.status, PurchaseEntryStatus.CONFIRMED)
        self.assertEqual(entry.total_cost, Decimal("55.00"))
        self.assertEqual(len(txns), 2)
        self.product.refresh_from_db()
        product_b.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("4.000"))
        self.assertEqual(product_b.stock_quantity, Decimal("2.000"))
        self.assertEqual(
            InventoryTransaction.objects.filter(
                transaction_type=InventoryTransactionType.PURCHASE
            ).count(),
            2,
        )
        for txn in txns:
            self.assertEqual(txn.purchase_entry_id, entry.pk)
            self.assertIsNotNone(txn.purchase_entry_line_id)
            self.assertEqual(txn.direction, InventoryDirection.IN)

    def test_purchase_increases_stock_only_once_and_preserves_unit_cost(self):
        before = self.product.stock_quantity
        quantity = Decimal("5.000")
        unit_cost = Decimal("12.50")
        entry, txns = record_purchase_stock_in(
            store=self.store,
            supplier_name="Cost Co",
            entry_date=timezone.localdate(),
            actor=self.actor,
            lines=[
                {
                    "product": self.product,
                    "quantity": quantity,
                    "unit_cost": unit_cost,
                }
            ],
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, before + quantity)
        self.assertEqual(len(txns), 1)
        self.assertEqual(
            InventoryTransaction.objects.filter(
                product=self.product,
                transaction_type=InventoryTransactionType.PURCHASE,
            ).count(),
            1,
        )
        line = entry.lines.get()
        txn = txns[0]
        self.assertEqual(line.unit_cost, unit_cost)
        self.assertEqual(line.line_total, Decimal("62.50"))
        self.assertEqual(entry.total_cost, Decimal("62.50"))
        self.assertEqual(txn.unit_cost, unit_cost)
        self.assertEqual(txn.quantity, quantity)
        self.assertEqual(txn.previous_quantity, before)
        self.assertEqual(txn.new_quantity, before + quantity)

    def test_purchase_rolls_back_entry_and_stock_when_a_later_step_fails(self):
        product_b = self.create_product(store=self.store, sku="SKU-ROLL", name="Roll")
        before_a = self.product.stock_quantity
        before_b = product_b.stock_quantity
        call_count = {"n": 0}
        real_apply = apply_stock_movement

        def fail_on_second_line(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] >= 2:
                raise ValidationError({"quantity": "Simulated mid-purchase failure."})
            return real_apply(*args, **kwargs)

        with mock.patch(
            "inventory.services.apply_stock_movement",
            side_effect=fail_on_second_line,
        ):
            with self.assertRaises(ValidationError):
                record_purchase_stock_in(
                    store=self.store,
                    supplier_name="Rollback Co",
                    entry_date=timezone.localdate(),
                    actor=self.actor,
                    lines=[
                        {
                            "product": self.product,
                            "quantity": Decimal("3.000"),
                            "unit_cost": Decimal("4.00"),
                        },
                        {
                            "product": product_b,
                            "quantity": Decimal("2.000"),
                            "unit_cost": Decimal("5.00"),
                        },
                    ],
                )

        self.product.refresh_from_db()
        product_b.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, before_a)
        self.assertEqual(product_b.stock_quantity, before_b)
        self.assertEqual(PurchaseEntry.objects.count(), 0)
        self.assertEqual(PurchaseEntryLine.objects.count(), 0)
        self.assertEqual(InventoryTransaction.objects.count(), 0)

    def test_confirm_purchase_twice_fails_without_extra_stock(self):
        entry = create_purchase_entry(
            store=self.store,
            supplier_name="Supplier",
            entry_date=timezone.localdate(),
            created_by=self.actor,
            lines=[
                {
                    "product": self.product,
                    "quantity": Decimal("5.000"),
                    "unit_cost": Decimal("3.00"),
                }
            ],
        )
        confirm_purchase_entry(purchase_entry=entry, confirmed_by=self.actor)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("5.000"))
        with self.assertRaises(ValidationError):
            confirm_purchase_entry(purchase_entry=entry, confirmed_by=self.actor)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("5.000"))
        self.assertEqual(InventoryTransaction.objects.count(), 1)

    def test_cancel_draft_purchase_does_not_change_stock(self):
        entry = create_purchase_entry(
            store=self.store,
            supplier_name="Supplier",
            entry_date=timezone.localdate(),
            created_by=self.actor,
            lines=[
                {
                    "product": self.product,
                    "quantity": Decimal("5.000"),
                    "unit_cost": Decimal("3.00"),
                }
            ],
        )
        cancel_purchase_entry(purchase_entry=entry)
        entry.refresh_from_db()
        self.assertEqual(entry.status, PurchaseEntryStatus.CANCELLED)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("0.000"))
        self.assertEqual(InventoryTransaction.objects.count(), 0)

    def test_purchase_rejects_product_from_other_store(self):
        other = self.create_product(
            store=self.create_store(name="Other"),
            sku="X-1",
        )
        with self.assertRaises(ValidationError):
            record_purchase_stock_in(
                store=self.store,
                supplier_name="Supplier",
                entry_date=timezone.localdate(),
                actor=self.actor,
                lines=[
                    {
                        "product": other,
                        "quantity": Decimal("1.000"),
                        "unit_cost": Decimal("1.00"),
                    }
                ],
            )
        self.assertEqual(PurchaseEntry.objects.count(), 0)
        self.assertEqual(InventoryTransaction.objects.count(), 0)


@skipUnless(
    connection.vendor != "sqlite",
    "select_for_update() is a no-op on SQLite; concurrency needs PostgreSQL/MySQL.",
)
class InventoryConcurrencyTests(InventoryTestMixin, TransactionTestCase):
    def setUp(self):
        self.store = self.create_store()
        self.actor = self.create_actor()
        self.product = self.create_product(
            store=self.store,
            stock_quantity=Decimal("0.000"),
        )
        record_opening_stock(
            product=self.product,
            store=self.store,
            quantity=Decimal("5.000"),
            actor=self.actor,
        )

    def test_concurrent_stock_outs_do_not_go_negative(self):
        results = []

        def attempt_out():
            try:
                record_manual_stock_out(
                    product=self.product,
                    store=self.store,
                    quantity=Decimal("5.000"),
                    actor=self.actor,
                    reason="Concurrent issue",
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
        self.assertEqual(results.count("ok"), 1)
        self.assertEqual(results.count("rejected"), 1)
        self.assertEqual(
            InventoryTransaction.objects.filter(
                transaction_type=InventoryTransactionType.STOCK_OUT
            ).count(),
            1,
        )


class OpeningStockInitializationTests(InventoryTestMixin, TestCase):
    def setUp(self):
        self.store = self.create_store()
        self.actor = self.create_actor(username="opening-init-actor")
        self.with_stock = self.create_product(
            store=self.store,
            sku="INIT-POS",
            name="Positive Stock",
            stock_quantity=Decimal("12.500"),
        )
        self.zero_stock = self.create_product(
            store=self.store,
            sku="INIT-ZERO",
            name="Zero Stock",
            stock_quantity=Decimal("0.000"),
        )
        self.other_store = self.create_store(name="Second Store")
        self.other_product = self.create_product(
            store=self.other_store,
            sku="INIT-OTHER",
            name="Other Store Product",
            stock_quantity=Decimal("3.000"),
        )

    def test_first_run_creates_opening_without_changing_stock(self):
        balances_before = {
            self.with_stock.pk: self.with_stock.stock_quantity,
            self.zero_stock.pk: self.zero_stock.stock_quantity,
            self.other_product.pk: self.other_product.stock_quantity,
        }

        candidates = list(products_needing_opening_stock_initialization())
        self.assertEqual(
            {product.pk for product in candidates},
            {self.with_stock.pk, self.other_product.pk},
        )

        result = initialize_opening_stock_from_catalogue(actor=self.actor)
        self.assertEqual(result["converted"], 2)
        self.assertFalse(result["dry_run"])

        openings = InventoryTransaction.objects.filter(
            transaction_type=InventoryTransactionType.OPENING
        ).order_by("product_id")
        self.assertEqual(openings.count(), 2)

        for txn in openings:
            product = Product.objects.get(pk=txn.product_id)
            self.assertEqual(txn.previous_quantity, Decimal("0.000"))
            self.assertEqual(txn.new_quantity, balances_before[product.pk])
            self.assertEqual(txn.quantity, balances_before[product.pk])
            self.assertEqual(txn.direction, InventoryDirection.IN)
            self.assertTrue(txn.is_system_generated)
            self.assertEqual(product.stock_quantity, balances_before[product.pk])

        self.zero_stock.refresh_from_db()
        self.assertEqual(self.zero_stock.stock_quantity, Decimal("0.000"))
        self.assertFalse(
            InventoryTransaction.objects.filter(product=self.zero_stock).exists()
        )

    def test_repeated_run_is_idempotent(self):
        first = initialize_opening_stock_from_catalogue(actor=self.actor)
        self.assertEqual(first["converted"], 2)
        balances = {
            p.pk: p.stock_quantity
            for p in Product.objects.filter(
                pk__in=[self.with_stock.pk, self.other_product.pk, self.zero_stock.pk]
            )
        }

        second = initialize_opening_stock_from_catalogue(actor=self.actor)
        self.assertEqual(second["converted"], 0)
        self.assertEqual(list(products_needing_opening_stock_initialization()), [])
        self.assertEqual(
            InventoryTransaction.objects.filter(
                transaction_type=InventoryTransactionType.OPENING
            ).count(),
            2,
        )

        for pk, expected in balances.items():
            product = Product.objects.get(pk=pk)
            self.assertEqual(product.stock_quantity, expected)

    def test_skips_products_that_already_have_inventory_history(self):
        record_manual_stock_in(
            product=self.with_stock,
            store=self.store,
            quantity=Decimal("1.000"),
            actor=self.actor,
        )
        self.with_stock.refresh_from_db()
        balance_after_stock_in = self.with_stock.stock_quantity

        result = initialize_opening_stock_from_catalogue(actor=self.actor)
        self.assertEqual(result["converted"], 1)
        self.assertEqual(result["product_ids"], [self.other_product.pk])
        self.assertFalse(
            InventoryTransaction.objects.filter(
                product=self.with_stock,
                transaction_type=InventoryTransactionType.OPENING,
            ).exists()
        )
        self.with_stock.refresh_from_db()
        self.assertEqual(self.with_stock.stock_quantity, balance_after_stock_in)

    def test_management_command_first_and_repeat_run(self):
        from django.core.management import call_command
        from io import StringIO

        out = StringIO()
        call_command("initialize_opening_stock", stdout=out)
        self.assertIn("Initialized OPENING stock for 2 product(s)", out.getvalue())
        self.assertEqual(
            InventoryTransaction.objects.filter(
                transaction_type=InventoryTransactionType.OPENING
            ).count(),
            2,
        )
        self.with_stock.refresh_from_db()
        self.assertEqual(self.with_stock.stock_quantity, Decimal("12.500"))

        out_repeat = StringIO()
        call_command("initialize_opening_stock", stdout=out_repeat)
        self.assertIn("Initialized OPENING stock for 0 product(s)", out_repeat.getvalue())
        self.assertEqual(
            InventoryTransaction.objects.filter(
                transaction_type=InventoryTransactionType.OPENING
            ).count(),
            2,
        )

    def test_dry_run_writes_nothing(self):
        from django.core.management import call_command
        from io import StringIO

        out = StringIO()
        call_command("initialize_opening_stock", dry_run=True, stdout=out)
        self.assertIn("Dry run: 2 product(s)", out.getvalue())
        self.assertEqual(InventoryTransaction.objects.count(), 0)
        self.with_stock.refresh_from_db()
        self.assertEqual(self.with_stock.stock_quantity, Decimal("12.500"))
