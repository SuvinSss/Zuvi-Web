"""
Single Order status synchronization service.

Derives the overall ``Order.status`` from sibling ``StoreOrder`` statuses using
deterministic rules. Callers (store transitions, rejection, tests) must use this
module instead of duplicating aggregation in views or templates.

Domain mapping from the informal rule names:

- PENDING (all StoreOrders pending) → Order ``PLACED``
- PROCESSING (any preparing, none ready-tier) → Order ``IN_PROGRESS``
- READY (all active ready-tier) → Order ``IN_PROGRESS``
  (Order has no READY; ready / out-for-delivery / ready-for-pickup stay
  ``IN_PROGRESS`` until fulfillment completes)
- COMPLETED / DELIVERED (all active completed) → Order ``COMPLETED``
  (no separate DELIVERED status; both delivery and facility-pickup succeed as
  ``COMPLETED``)
- Some REJECTED/CANCELLED + some active → ``PARTIALLY_CANCELLED``
- All REJECTED/CANCELLED → ``CANCELLED``

Accepted-only progress (no preparing yet) maps to ``CONFIRMED``.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from .models import (
    Order,
    OrderStatus,
    OrderStatusHistory,
    PaymentStatus,
    StoreOrder,
    StoreOrderStatus,
)
from .status import STORE_ORDER_NON_CHARGEABLE_STATUSES

# StoreOrder statuses that mean "ready for customer fulfillment".
STORE_ORDER_READY_TIER_STATUSES = frozenset(
    {
        StoreOrderStatus.READY,
        StoreOrderStatus.OUT_FOR_DELIVERY,
        StoreOrderStatus.READY_FOR_PICKUP,
    }
)

# StoreOrder "processing" equivalent (portal action key ``processing``).
STORE_ORDER_PROCESSING_STATUSES = frozenset(
    {
        StoreOrderStatus.PREPARING,
    }
)


def _client_ip(request):
    if request is None:
        return None
    try:
        from accounts.audit_ip import get_client_ip

        return get_client_ip(request)
    except Exception:
        return None


def calculate_order_status(store_order_statuses) -> str:
    """
    Pure calculation: iterable of StoreOrder status values → OrderStatus.

    Rules are evaluated in the documented order below; the first match wins.

    1. No StoreOrders → ``PLACED``
    2. All REJECTED/CANCELLED → ``CANCELLED``
    3. All *active* COMPLETED → ``COMPLETED``
    4. Some REJECTED/CANCELLED and some still active → ``PARTIALLY_CANCELLED``
    5. All active in ready tier → ``IN_PROGRESS``
    6. Any PREPARING and none in ready tier → ``IN_PROGRESS``
    7. All active PENDING → ``PLACED``
    8. Active only PENDING and/or ACCEPTED (at least one ACCEPTED) → ``CONFIRMED``
    9. Any other active mix → ``IN_PROGRESS``
    """
    statuses = [str(status) for status in store_order_statuses]
    if not statuses:
        return OrderStatus.PLACED

    active = [
        status
        for status in statuses
        if status not in STORE_ORDER_NON_CHARGEABLE_STATUSES
    ]
    has_non_chargeable = any(
        status in STORE_ORDER_NON_CHARGEABLE_STATUSES for status in statuses
    )

    # All REJECTED/CANCELLED → CANCELLED
    if not active:
        return OrderStatus.CANCELLED

    # All active COMPLETED → COMPLETED (DELIVERED maps here)
    if all(status == StoreOrderStatus.COMPLETED for status in active):
        return OrderStatus.COMPLETED

    # Some REJECTED/CANCELLED and some active → PARTIALLY_CANCELLED
    if has_non_chargeable:
        return OrderStatus.PARTIALLY_CANCELLED

    # All active ready-tier → IN_PROGRESS (Order has no READY)
    if all(status in STORE_ORDER_READY_TIER_STATUSES for status in active):
        return OrderStatus.IN_PROGRESS

    # Any PROCESSING and none READY-tier → IN_PROGRESS
    if any(status in STORE_ORDER_PROCESSING_STATUSES for status in active) and not any(
        status in STORE_ORDER_READY_TIER_STATUSES for status in active
    ):
        return OrderStatus.IN_PROGRESS

    # All PENDING → PLACED
    if all(status == StoreOrderStatus.PENDING for status in active):
        return OrderStatus.PLACED

    # Only PENDING / ACCEPTED with at least one ACCEPTED → CONFIRMED
    pending_or_accepted = frozenset(
        {
            StoreOrderStatus.PENDING,
            StoreOrderStatus.ACCEPTED,
        }
    )
    if all(status in pending_or_accepted for status in active) and any(
        status == StoreOrderStatus.ACCEPTED for status in active
    ):
        return OrderStatus.CONFIRMED

    # Mixed progress (e.g. PENDING+READY, ACCEPTED+PREPARING, COMPLETED+READY)
    return OrderStatus.IN_PROGRESS


def calculate_order_status_from_store_orders(store_orders) -> str:
    """Convenience wrapper over StoreOrder instances (or objects with ``.status``)."""
    return calculate_order_status(so.status for so in store_orders)


def _apply_order_status(
    *,
    order,
    new_status,
    actor,
    reason,
    request=None,
):
    """Persist a new overall status and write history. Caller ensures it changed."""
    old_status = order.status
    order.status = new_status
    update_fields = ["status", "updated_at"]

    if new_status == OrderStatus.CANCELLED:
        order.cancellation_reason = reason or order.cancellation_reason
        order.cancelled_at = timezone.now()
        order.cancelled_by = actor
        update_fields.extend(
            ["cancellation_reason", "cancelled_at", "cancelled_by"]
        )
        if order.payment_status == PaymentStatus.PENDING:
            order.payment_status = PaymentStatus.CANCELLED
            update_fields.append("payment_status")

    order.save(update_fields=update_fields)
    OrderStatusHistory.objects.create(
        order=order,
        old_status=old_status,
        new_status=new_status,
        changed_by=actor,
        reason=(reason or "").strip(),
        ip_address=_client_ip(request),
    )
    return order


@transaction.atomic
def sync_order_status_from_store_orders(
    *,
    order,
    store_orders=None,
    actor=None,
    reason="",
    request=None,
):
    """
    Recalculate and apply overall Order status from its StoreOrders.

    Creates ``OrderStatusHistory`` only when the overall status actually changes.
    """
    order = Order.objects.select_for_update().get(pk=order.pk)

    if store_orders is None:
        store_orders = list(
            StoreOrder.objects.filter(order_id=order.pk).order_by("pk")
        )
    else:
        store_orders = list(store_orders)

    new_status = calculate_order_status_from_store_orders(store_orders)
    if new_status == order.status:
        return order

    return _apply_order_status(
        order=order,
        new_status=new_status,
        actor=actor,
        reason=reason,
        request=request,
    )
