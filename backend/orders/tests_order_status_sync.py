"""
Order status synchronization: deterministic derivation from StoreOrder statuses.
"""

from django.test import SimpleTestCase, TestCase

from .models import (
    OrderStatus,
    OrderStatusHistory,
    PaymentStatus,
    StoreOrderStatus,
)
from .order_status_sync import (
    calculate_order_status,
    sync_order_status_from_store_orders,
)
from .store_status import (
    accept_store_order,
    mark_store_order_processing,
    mark_store_order_ready,
)
from .tests import OrderModelTestMixin


class CalculateOrderStatusTests(SimpleTestCase):
    """Pure rule coverage — every meaningful StoreOrder combination."""

    def test_empty_store_orders_is_placed(self):
        self.assertEqual(calculate_order_status([]), OrderStatus.PLACED)

    def test_all_pending_is_placed(self):
        self.assertEqual(
            calculate_order_status(
                [StoreOrderStatus.PENDING, StoreOrderStatus.PENDING]
            ),
            OrderStatus.PLACED,
        )

    def test_single_pending_is_placed(self):
        self.assertEqual(
            calculate_order_status([StoreOrderStatus.PENDING]),
            OrderStatus.PLACED,
        )

    def test_all_accepted_is_confirmed(self):
        self.assertEqual(
            calculate_order_status(
                [StoreOrderStatus.ACCEPTED, StoreOrderStatus.ACCEPTED]
            ),
            OrderStatus.CONFIRMED,
        )

    def test_pending_and_accepted_is_confirmed(self):
        self.assertEqual(
            calculate_order_status(
                [StoreOrderStatus.PENDING, StoreOrderStatus.ACCEPTED]
            ),
            OrderStatus.CONFIRMED,
        )

    def test_any_preparing_none_ready_is_in_progress(self):
        self.assertEqual(
            calculate_order_status(
                [StoreOrderStatus.PREPARING, StoreOrderStatus.ACCEPTED]
            ),
            OrderStatus.IN_PROGRESS,
        )
        self.assertEqual(
            calculate_order_status(
                [StoreOrderStatus.PREPARING, StoreOrderStatus.PENDING]
            ),
            OrderStatus.IN_PROGRESS,
        )
        self.assertEqual(
            calculate_order_status([StoreOrderStatus.PREPARING]),
            OrderStatus.IN_PROGRESS,
        )

    def test_all_ready_tier_is_in_progress(self):
        for status in (
            StoreOrderStatus.READY,
            StoreOrderStatus.OUT_FOR_DELIVERY,
            StoreOrderStatus.READY_FOR_PICKUP,
        ):
            with self.subTest(status=status):
                self.assertEqual(
                    calculate_order_status([status, status]),
                    OrderStatus.IN_PROGRESS,
                )

    def test_mixed_ready_tier_is_in_progress(self):
        self.assertEqual(
            calculate_order_status(
                [
                    StoreOrderStatus.READY,
                    StoreOrderStatus.OUT_FOR_DELIVERY,
                    StoreOrderStatus.READY_FOR_PICKUP,
                ]
            ),
            OrderStatus.IN_PROGRESS,
        )

    def test_preparing_and_ready_is_in_progress(self):
        self.assertEqual(
            calculate_order_status(
                [StoreOrderStatus.PREPARING, StoreOrderStatus.READY]
            ),
            OrderStatus.IN_PROGRESS,
        )

    def test_pending_and_ready_is_in_progress(self):
        self.assertEqual(
            calculate_order_status(
                [StoreOrderStatus.PENDING, StoreOrderStatus.READY]
            ),
            OrderStatus.IN_PROGRESS,
        )

    def test_all_completed_is_completed(self):
        self.assertEqual(
            calculate_order_status(
                [StoreOrderStatus.COMPLETED, StoreOrderStatus.COMPLETED]
            ),
            OrderStatus.COMPLETED,
        )

    def test_completed_delivery_and_pickup_workflows_both_map_to_completed(self):
        # Order has no DELIVERED; both fulfillment workflows use COMPLETED.
        self.assertEqual(
            calculate_order_status([StoreOrderStatus.COMPLETED]),
            OrderStatus.COMPLETED,
        )

    def test_completed_with_ready_sibling_is_in_progress(self):
        self.assertEqual(
            calculate_order_status(
                [StoreOrderStatus.COMPLETED, StoreOrderStatus.READY]
            ),
            OrderStatus.IN_PROGRESS,
        )

    def test_all_rejected_is_cancelled(self):
        self.assertEqual(
            calculate_order_status(
                [StoreOrderStatus.REJECTED, StoreOrderStatus.REJECTED]
            ),
            OrderStatus.CANCELLED,
        )

    def test_all_cancelled_store_orders_is_cancelled(self):
        self.assertEqual(
            calculate_order_status(
                [StoreOrderStatus.CANCELLED, StoreOrderStatus.CANCELLED]
            ),
            OrderStatus.CANCELLED,
        )

    def test_mixed_rejected_and_cancelled_is_cancelled(self):
        self.assertEqual(
            calculate_order_status(
                [StoreOrderStatus.REJECTED, StoreOrderStatus.CANCELLED]
            ),
            OrderStatus.CANCELLED,
        )

    def test_some_rejected_some_active_is_partially_cancelled(self):
        for active in (
            StoreOrderStatus.PENDING,
            StoreOrderStatus.ACCEPTED,
            StoreOrderStatus.PREPARING,
            StoreOrderStatus.READY,
            StoreOrderStatus.OUT_FOR_DELIVERY,
            StoreOrderStatus.READY_FOR_PICKUP,
        ):
            with self.subTest(active=active):
                self.assertEqual(
                    calculate_order_status(
                        [StoreOrderStatus.REJECTED, active]
                    ),
                    OrderStatus.PARTIALLY_CANCELLED,
                )

    def test_some_cancelled_some_active_is_partially_cancelled(self):
        self.assertEqual(
            calculate_order_status(
                [StoreOrderStatus.CANCELLED, StoreOrderStatus.PENDING]
            ),
            OrderStatus.PARTIALLY_CANCELLED,
        )

    def test_rejected_plus_all_remaining_completed_is_completed(self):
        self.assertEqual(
            calculate_order_status(
                [
                    StoreOrderStatus.REJECTED,
                    StoreOrderStatus.COMPLETED,
                    StoreOrderStatus.COMPLETED,
                ]
            ),
            OrderStatus.COMPLETED,
        )

    def test_cancelled_plus_all_remaining_completed_is_completed(self):
        self.assertEqual(
            calculate_order_status(
                [StoreOrderStatus.CANCELLED, StoreOrderStatus.COMPLETED]
            ),
            OrderStatus.COMPLETED,
        )

    def test_rejected_plus_completed_and_pending_is_partially_cancelled(self):
        self.assertEqual(
            calculate_order_status(
                [
                    StoreOrderStatus.REJECTED,
                    StoreOrderStatus.COMPLETED,
                    StoreOrderStatus.PENDING,
                ]
            ),
            OrderStatus.PARTIALLY_CANCELLED,
        )


class SyncOrderStatusServiceTests(OrderModelTestMixin, TestCase):
    def _multi_store_order(self, *store_statuses):
        order = self.create_delivery_order()
        store_orders = []
        for status in store_statuses:
            store_orders.append(
                self.create_store_order(order=order, status=status)
            )
        return order, store_orders

    def test_sync_writes_history_only_when_status_changes(self):
        order, _store_orders = self._multi_store_order(
            StoreOrderStatus.PENDING,
            StoreOrderStatus.PENDING,
        )
        self.assertEqual(order.status, OrderStatus.PLACED)
        history_before = OrderStatusHistory.objects.filter(order=order).count()

        sync_order_status_from_store_orders(
            order=order,
            actor=order.customer.user,
            reason="No-op sync",
        )
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.PLACED)
        self.assertEqual(
            OrderStatusHistory.objects.filter(order=order).count(),
            history_before,
        )

        # Advance one store order to ACCEPTED → parent CONFIRMED + one history.
        store_orders = list(order.store_orders.order_by("pk"))
        store_orders[0].status = StoreOrderStatus.ACCEPTED
        store_orders[0].save(update_fields=["status", "updated_at"])

        sync_order_status_from_store_orders(
            order=order,
            actor=order.customer.user,
            reason="Store accepted",
        )
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.CONFIRMED)
        self.assertEqual(
            OrderStatusHistory.objects.filter(order=order).count(),
            history_before + 1,
        )
        latest = OrderStatusHistory.objects.filter(order=order).latest("pk")
        self.assertEqual(latest.old_status, OrderStatus.PLACED)
        self.assertEqual(latest.new_status, OrderStatus.CONFIRMED)
        self.assertEqual(latest.reason, "Store accepted")

    def test_sync_all_rejected_cancels_order_and_pending_payment(self):
        order, store_orders = self._multi_store_order(
            StoreOrderStatus.REJECTED,
            StoreOrderStatus.REJECTED,
        )
        sync_order_status_from_store_orders(
            order=order,
            actor=order.customer.user,
            reason="All stores rejected",
        )
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.CANCELLED)
        self.assertEqual(order.payment_status, PaymentStatus.CANCELLED)
        self.assertEqual(order.cancellation_reason, "All stores rejected")
        self.assertIsNotNone(order.cancelled_at)

    def test_sync_partial_reject_marks_partially_cancelled(self):
        order, _store_orders = self._multi_store_order(
            StoreOrderStatus.REJECTED,
            StoreOrderStatus.PENDING,
        )
        sync_order_status_from_store_orders(
            order=order,
            actor=order.customer.user,
            reason="One store rejected",
        )
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.PARTIALLY_CANCELLED)

    def test_sync_remaining_completed_after_reject_is_completed(self):
        order, _store_orders = self._multi_store_order(
            StoreOrderStatus.REJECTED,
            StoreOrderStatus.COMPLETED,
        )
        order.status = OrderStatus.PARTIALLY_CANCELLED
        order.save(update_fields=["status", "updated_at"])

        sync_order_status_from_store_orders(
            order=order,
            actor=order.customer.user,
            reason="Remaining store completed",
        )
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.COMPLETED)

    def test_sync_completed_for_facility_pickup_workflow(self):
        order = self.create_facility_pickup_order()
        store = self.create_store()
        pickup = self.create_pickup_location(store=store)
        self.create_store_order(
            order=order,
            store=store,
            status=StoreOrderStatus.COMPLETED,
            pickup_location=pickup,
        )
        sync_order_status_from_store_orders(
            order=order,
            actor=order.customer.user,
            reason="Pickup completed",
        )
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.COMPLETED)

    def test_store_forward_transitions_sync_parent_order(self):
        order, store_orders = self._multi_store_order(StoreOrderStatus.PENDING)
        store_order = store_orders[0]
        store = store_order.store
        actor = order.customer.user

        accept_store_order(store_order=store_order, store=store, actor=actor)
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.CONFIRMED)

        mark_store_order_processing(
            store_order=store_order, store=store, actor=actor
        )
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.IN_PROGRESS)

        mark_store_order_ready(store_order=store_order, store=store, actor=actor)
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.IN_PROGRESS)

        # Idempotent re-sync while already IN_PROGRESS adds no history.
        history_count = OrderStatusHistory.objects.filter(order=order).count()
        sync_order_status_from_store_orders(
            order=order,
            actor=actor,
            reason="Ready again",
        )
        self.assertEqual(
            OrderStatusHistory.objects.filter(order=order).count(),
            history_count,
        )

    def test_multi_store_accept_one_confirms_parent(self):
        order, store_orders = self._multi_store_order(
            StoreOrderStatus.PENDING,
            StoreOrderStatus.PENDING,
        )
        accept_store_order(
            store_order=store_orders[0],
            store=store_orders[0].store,
            actor=order.customer.user,
        )
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.CONFIRMED)
        store_orders[1].refresh_from_db()
        self.assertEqual(store_orders[1].status, StoreOrderStatus.PENDING)
