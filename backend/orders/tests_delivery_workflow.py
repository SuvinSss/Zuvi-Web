"""
Order-delivery workflow v1: Delivered status, Collected payment, automatic
timestamps, audit history, corrected reversals and unchanged inventory.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from customers.models import AddressLabel, RegistrationSource
from customers.services import create_customer_delivery_address, create_customer_with_user
from inventory.models import InventoryTransaction
from inventory.services import order_item_deduct_reference

from .management_status import (
    ADMIN_ORDER_STATUS_TRANSITIONS,
    ADMIN_PAYMENT_STATUS_TRANSITIONS,
    available_admin_order_statuses,
    available_admin_payment_statuses,
    update_order_payment_status,
    update_order_status,
)
from .models import (
    OrderPaymentHistory,
    OrderStatus,
    OrderStatusHistory,
    PaymentStatus,
    StoreOrderStatus,
)
from .store_status import (
    accept_store_order,
    mark_store_order_processing,
    mark_store_order_ready,
)
from .tests_management_permissions import OrderPermissionTestMixin


class DeliveryWorkflowTestMixin(OrderPermissionTestMixin):
    def setUp(self):
        self.super_admin = self.create_super_admin()
        self.admin = self.create_admin()
        self.store = self.create_store(name="Delivery Store")
        self.product = self.create_public_product(
            store=self.store,
            name="Delivery Item",
            stock=Decimal("10.000"),
        )
        self.store_user = self.create_store_user(
            store=self.store,
            username="delivery-store-user",
        )
        self.customer, self.customer_user = create_customer_with_user(
            user_data={
                "username": "delivery-customer",
                "email": "delivery-customer@example.com",
                "first_name": "Delivery",
                "last_name": "Customer",
                "phone_number": "9000000777",
                "password": "secure-password-123",
            },
            registration_source=RegistrationSource.WEBSITE,
        )
        self.address = create_customer_delivery_address(
            customer=self.customer,
            data={
                "label": AddressLabel.HOME,
                "recipient_name": "Delivery Customer",
                "phone_number": "9000000777",
                "line1": "7 Delivery Road",
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
        self.order = self.place_sample_order(token="tok-delivery-workflow")
        self.store_order = self.order.store_orders.get()
        self.detail_url = reverse(
            "orders:management_order_detail",
            kwargs={"order_number": self.order.order_number},
        )
        self.change_url = reverse(
            "orders:management_order_change_status",
            kwargs={"order_number": self.order.order_number},
        )

    def make_store_order_ready(self):
        for step in (
            accept_store_order,
            mark_store_order_processing,
            mark_store_order_ready,
        ):
            step(
                store_order=self.store_order,
                store=self.store,
                actor=self.store_user,
            )
        # These tests cover the management status/audit rules. Delivery orders now get a
        # Delivery record when the store marks them ready, and the evidence workflow (see
        # deliveries/tests.py) is the only way to complete those. Dropping the record here
        # reproduces an order that predates the delivery module, which management may
        # still complete by hand.
        from deliveries.models import Delivery

        Delivery.objects.filter(store_order=self.store_order).delete()
        self.order.refresh_from_db()
        self.store_order.refresh_from_db()

    def mark_delivered(self, actor=None):
        return update_order_status(
            order=self.order,
            new_status=OrderStatus.COMPLETED,
            actor=actor or self.super_admin,
            reason="Handed to customer",
        )

    def mark_collected(self, actor=None):
        return update_order_payment_status(
            order=self.order,
            new_payment_status=PaymentStatus.COLLECTED,
            actor=actor or self.super_admin,
            reason="Cash received",
        )

    def stock_snapshot(self):
        self.product.refresh_from_db()
        return (
            self.product.stock_quantity,
            InventoryTransaction.objects.filter(product=self.product).count(),
        )


class DeliveredStatusTests(DeliveryWorkflowTestMixin, TestCase):
    def test_completed_is_labelled_delivered(self):
        self.assertEqual(OrderStatus.COMPLETED.label, "Delivered")
        self.assertEqual(PaymentStatus.COLLECTED.label, "Collected")

    def test_existing_forward_transitions_unchanged(self):
        self.assertEqual(
            ADMIN_ORDER_STATUS_TRANSITIONS,
            {
                OrderStatus.PLACED: {OrderStatus.CONFIRMED, OrderStatus.IN_PROGRESS},
                OrderStatus.CONFIRMED: {
                    OrderStatus.IN_PROGRESS,
                    OrderStatus.COMPLETED,
                },
                OrderStatus.IN_PROGRESS: {OrderStatus.COMPLETED},
                OrderStatus.PARTIALLY_CANCELLED: {
                    OrderStatus.IN_PROGRESS,
                    OrderStatus.COMPLETED,
                },
            },
        )
        self.assertEqual(
            ADMIN_PAYMENT_STATUS_TRANSITIONS,
            {PaymentStatus.PENDING: {PaymentStatus.COLLECTED, PaymentStatus.CANCELLED}},
        )

    def test_store_flow_then_delivered(self):
        self.assertEqual(self.order.status, OrderStatus.PLACED)
        self.make_store_order_ready()
        self.assertEqual(self.order.status, OrderStatus.IN_PROGRESS)
        self.assertIn(OrderStatus.COMPLETED, available_admin_order_statuses(self.order))

        order = self.mark_delivered()
        self.store_order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.COMPLETED)
        self.assertEqual(self.store_order.status, StoreOrderStatus.COMPLETED)

    def test_cannot_deliver_before_store_order_ready(self):
        update_order_status(
            order=self.order,
            new_status=OrderStatus.IN_PROGRESS,
            actor=self.super_admin,
        )
        self.order.refresh_from_db()
        with self.assertRaises(ValidationError):
            self.mark_delivered()
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.IN_PROGRESS)
        self.assertIsNone(self.order.delivered_at)

    def test_delivered_while_payment_pending(self):
        self.make_store_order_ready()
        order = self.mark_delivered()
        self.assertEqual(order.status, OrderStatus.COMPLETED)
        self.assertEqual(order.payment_status, PaymentStatus.PENDING)
        self.assertIsNotNone(order.delivered_at)
        self.assertIsNone(order.payment_collected_at)

    def test_payment_collected_after_delivery(self):
        self.make_store_order_ready()
        self.assertNotIn(
            PaymentStatus.COLLECTED, available_admin_payment_statuses(self.order)
        )
        self.mark_delivered()
        self.order.refresh_from_db()
        self.assertIn(
            PaymentStatus.COLLECTED, available_admin_payment_statuses(self.order)
        )
        order = self.mark_collected()
        self.assertEqual(order.status, OrderStatus.COMPLETED)
        self.assertEqual(order.payment_status, PaymentStatus.COLLECTED)

    def test_payment_cannot_be_collected_before_delivery(self):
        self.make_store_order_ready()
        with self.assertRaises(ValidationError):
            self.mark_collected()
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, PaymentStatus.PENDING)
        self.assertIsNone(self.order.payment_collected_at)


class TimestampTests(DeliveryWorkflowTestMixin, TestCase):
    def test_timestamps_recorded_automatically(self):
        self.make_store_order_ready()
        self.assertIsNone(self.order.delivered_at)
        self.assertIsNone(self.order.payment_collected_at)

        before = timezone.now()
        order = self.mark_delivered()
        after_delivery = timezone.now()
        self.assertTrue(before <= order.delivered_at <= after_delivery)
        self.assertIsNone(order.payment_collected_at)

        order = self.mark_collected()
        self.assertTrue(after_delivery <= order.payment_collected_at <= timezone.now())
        self.assertTrue(order.delivered_at <= after_delivery)

    def test_reversals_clear_timestamps(self):
        self.make_store_order_ready()
        self.mark_delivered()
        self.mark_collected()

        order = update_order_payment_status(
            order=self.order,
            new_payment_status=PaymentStatus.PENDING,
            actor=self.super_admin,
            correction_note="Cash was not actually received",
        )
        self.assertIsNone(order.payment_collected_at)
        self.assertIsNotNone(order.delivered_at)

        order = update_order_status(
            order=self.order,
            new_status=OrderStatus.IN_PROGRESS,
            actor=self.super_admin,
            correction_note="Marked delivered by mistake",
        )
        self.assertIsNone(order.delivered_at)


class ReversalTests(DeliveryWorkflowTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.make_store_order_ready()
        self.mark_delivered()
        self.order.refresh_from_db()

    def test_delivery_reversal_without_note_rejected(self):
        for note in ("", "   "):
            with self.assertRaises(ValidationError) as ctx:
                update_order_status(
                    order=self.order,
                    new_status=OrderStatus.IN_PROGRESS,
                    actor=self.super_admin,
                    reason="A plain note is not a correction note",
                    correction_note=note,
                )
            self.assertIn("correction_note", ctx.exception.message_dict)
        self.order.refresh_from_db()
        self.store_order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.COMPLETED)
        self.assertEqual(self.store_order.status, StoreOrderStatus.COMPLETED)
        self.assertIsNotNone(self.order.delivered_at)

    def test_payment_reversal_without_note_rejected(self):
        self.mark_collected()
        with self.assertRaises(ValidationError) as ctx:
            update_order_payment_status(
                order=self.order,
                new_payment_status=PaymentStatus.PENDING,
                actor=self.super_admin,
            )
        self.assertIn("correction_note", ctx.exception.message_dict)
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, PaymentStatus.COLLECTED)
        self.assertIsNotNone(self.order.payment_collected_at)

    def test_delivery_reversal_blocked_while_payment_collected(self):
        self.mark_collected()
        self.order.refresh_from_db()
        self.assertNotIn(
            OrderStatus.IN_PROGRESS, available_admin_order_statuses(self.order)
        )
        with self.assertRaises(ValidationError):
            update_order_status(
                order=self.order,
                new_status=OrderStatus.IN_PROGRESS,
                actor=self.super_admin,
                correction_note="Wrong order",
            )
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.COMPLETED)

    def test_delivery_reversal_with_note_reopens_store_orders(self):
        self.assertIn(OrderStatus.IN_PROGRESS, available_admin_order_statuses(self.order))
        order = update_order_status(
            order=self.order,
            new_status=OrderStatus.IN_PROGRESS,
            actor=self.super_admin,
            correction_note="Marked delivered by mistake",
        )
        self.store_order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.IN_PROGRESS)
        self.assertEqual(self.store_order.status, StoreOrderStatus.READY)
        entry = self.store_order.status_history.order_by("-created_at", "-pk").first()
        self.assertEqual(entry.old_status, StoreOrderStatus.COMPLETED)
        self.assertEqual(entry.new_status, StoreOrderStatus.READY)

        # Delivery can be re-recorded after the correction.
        order = self.mark_delivered()
        self.assertEqual(order.status, OrderStatus.COMPLETED)
        self.assertIsNotNone(order.delivered_at)

    def test_view_rejects_reversal_without_note(self):
        self.client.login(username="order-super", password="secure-password-123")
        response = self.client.post(
            self.change_url,
            {
                "action": "update_status",
                "status-status": OrderStatus.IN_PROGRESS,
                "status-reason": "",
                "status-correction_note": "",
            },
            follow=True,
        )
        self.assertContains(response, "A correction note is required")
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.COMPLETED)

    def test_view_accepts_reversal_with_note(self):
        self.client.login(username="order-super", password="secure-password-123")
        response = self.client.post(
            self.change_url,
            {
                "action": "update_status",
                "status-status": OrderStatus.IN_PROGRESS,
                "status-correction_note": "Customer was not home",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.IN_PROGRESS)


class AuditHistoryTests(DeliveryWorkflowTestMixin, TestCase):
    def test_audit_rows_record_previous_new_actor_and_note(self):
        self.make_store_order_ready()
        self.mark_delivered()
        self.mark_collected()
        update_order_payment_status(
            order=self.order,
            new_payment_status=PaymentStatus.PENDING,
            actor=self.super_admin,
            correction_note="Cash counted short",
        )

        delivered = OrderStatusHistory.objects.get(
            order=self.order, new_status=OrderStatus.COMPLETED
        )
        self.assertEqual(delivered.old_status, OrderStatus.IN_PROGRESS)
        self.assertEqual(delivered.changed_by, self.super_admin)
        self.assertIsNotNone(delivered.created_at)
        self.assertEqual(delivered.correction_note, "")

        payments = list(OrderPaymentHistory.objects.filter(order=self.order).order_by("pk"))
        self.assertEqual(
            [(p.old_payment_status, p.new_payment_status) for p in payments],
            [
                (PaymentStatus.PENDING, PaymentStatus.COLLECTED),
                (PaymentStatus.COLLECTED, PaymentStatus.PENDING),
            ],
        )
        self.assertTrue(all(p.changed_by == self.super_admin for p in payments))
        self.assertEqual(payments[0].correction_note, "")
        self.assertEqual(payments[1].correction_note, "Cash counted short")

        # Payment changes no longer create fake order-status rows.
        self.assertFalse(
            OrderStatusHistory.objects.filter(
                order=self.order, reason__startswith="Payment status"
            ).exists()
        )

    def test_management_detail_shows_audit_history(self):
        self.make_store_order_ready()
        self.mark_delivered()
        self.mark_collected()
        update_order_payment_status(
            order=self.order,
            new_payment_status=PaymentStatus.PENDING,
            actor=self.super_admin,
            correction_note="Cash counted short",
        )

        self.client.login(username="order-super", password="secure-password-123")
        response = self.client.get(self.detail_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Order &amp; payment audit history")
        self.assertContains(response, 'id="order-audit-history"')

        rows = response.context["audit_entries"]
        kinds = [(row["kind"], row["previous"], row["new"]) for row in rows]
        self.assertIn(("Order status", "In Progress", "Delivered"), kinds)
        self.assertIn(("Payment", "Pending", "Collected"), kinds)
        self.assertIn(("Payment", "Collected", "Pending"), kinds)
        correction = next(row for row in rows if row["correction_note"])
        self.assertEqual(correction["changed_by"], self.super_admin)
        self.assertIsNotNone(correction["created_at"])

        self.assertContains(response, "Cash counted short")
        self.assertContains(response, "Correction")
        self.assertContains(response, str(self.super_admin))
        self.assertContains(response, "Delivered at")
        self.assertContains(response, "Collected at")

    def test_customer_tracking_still_shows_status_without_internal_notes(self):
        self.make_store_order_ready()
        self.mark_delivered()
        update_order_status(
            order=self.order,
            new_status=OrderStatus.IN_PROGRESS,
            actor=self.super_admin,
            correction_note="Internal: driver error",
        )
        self.mark_delivered()

        self.client.login(username="delivery-customer", password="secure-password-123")
        response = self.client.get(
            reverse(
                "orders:customer_order_detail",
                kwargs={"order_number": self.order.order_number},
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Delivered")
        self.assertContains(response, "Status history")
        self.assertNotContains(response, "Internal: driver error")


class InventoryUnchangedTests(DeliveryWorkflowTestMixin, TestCase):
    def test_full_workflow_does_not_touch_stock(self):
        item = self.store_order.items.get()
        self.assertEqual(
            InventoryTransaction.objects.filter(
                reference=order_item_deduct_reference(item.pk)
            ).count(),
            1,
        )
        stock_after_checkout, txns_after_checkout = self.stock_snapshot()
        self.assertEqual(stock_after_checkout, Decimal("8.000"))

        self.make_store_order_ready()
        self.mark_delivered()
        self.mark_collected()
        update_order_payment_status(
            order=self.order,
            new_payment_status=PaymentStatus.PENDING,
            actor=self.super_admin,
            correction_note="Correction test",
        )
        update_order_status(
            order=self.order,
            new_status=OrderStatus.IN_PROGRESS,
            actor=self.super_admin,
            correction_note="Correction test",
        )
        self.mark_delivered()
        self.mark_collected()

        self.assertEqual(self.stock_snapshot(), (stock_after_checkout, txns_after_checkout))
        self.assertEqual(
            InventoryTransaction.objects.filter(
                reference=order_item_deduct_reference(item.pk)
            ).count(),
            1,
        )
        item.refresh_from_db()
        self.assertFalse(item.stock_restored)


class DeliveryPermissionTests(DeliveryWorkflowTestMixin, TestCase):
    """Existing model: Super Admin always; Admin needs the Django permissions."""

    def setUp(self):
        super().setUp()
        self.make_store_order_ready()

    def _post(self, data):
        return self.client.post(self.change_url, data)

    def _deliver_and_collect_via_views(self):
        delivered = self._post(
            {"action": "update_status", "status-status": OrderStatus.COMPLETED}
        )
        collected = self._post(
            {"action": "update_payment", "payment-payment_status": PaymentStatus.COLLECTED}
        )
        self.order.refresh_from_db()
        return delivered, collected

    def test_super_admin_can_deliver_and_collect(self):
        self.client.login(username="order-super", password="secure-password-123")
        delivered, collected = self._deliver_and_collect_via_views()
        self.assertEqual((delivered.status_code, collected.status_code), (302, 302))
        self.assertEqual(self.order.status, OrderStatus.COMPLETED)
        self.assertEqual(self.order.payment_status, PaymentStatus.COLLECTED)

    def test_admin_with_order_permissions_can_deliver_and_collect(self):
        self.grant_order_perms(
            self.admin, "view_order", "change_order", "manage_payment_status"
        )
        self.client.login(username="order-admin", password="secure-password-123")
        delivered, collected = self._deliver_and_collect_via_views()
        self.assertEqual((delivered.status_code, collected.status_code), (302, 302))
        self.assertEqual(self.order.status, OrderStatus.COMPLETED)
        self.assertEqual(self.order.payment_status, PaymentStatus.COLLECTED)
        self.assertEqual(
            self.order.payment_history.get().changed_by_id, self.admin.pk
        )

    def test_admin_without_permissions_is_denied(self):
        self.grant_order_perms(self.admin, "view_order")
        self.client.login(username="order-admin", password="secure-password-123")
        delivered, collected = self._deliver_and_collect_via_views()
        self.assertEqual((delivered.status_code, collected.status_code), (403, 403))
        self.assertEqual(self.order.status, OrderStatus.IN_PROGRESS)
        self.assertEqual(self.order.payment_status, PaymentStatus.PENDING)

    def test_store_user_and_customer_are_denied(self):
        for username in ("delivery-store-user", "delivery-customer"):
            self.client.logout()
            self.client.login(username=username, password="secure-password-123")
            delivered, collected = self._deliver_and_collect_via_views()
            for response in (delivered, collected):
                self.assertNotEqual(response.get("Location"), self.detail_url)
            self.assertEqual(self.order.status, OrderStatus.IN_PROGRESS)
            self.assertEqual(self.order.payment_status, PaymentStatus.PENDING)
