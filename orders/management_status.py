"""Management-portal Order status and payment transitions."""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction

from .cancellation import cancel_order_by_admin
from .models import (
    Order,
    OrderStatus,
    OrderStatusHistory,
    PaymentStatus,
    StoreOrder,
    StoreOrderStatus,
    StoreOrderStatusHistory,
)
from .order_status_sync import STORE_ORDER_READY_TIER_STATUSES
from .status import (
    ADMIN_CANCELLABLE_ORDER_STATUSES,
    STORE_ORDER_NON_CHARGEABLE_STATUSES,
    validate_admin_order_cancellation,
)

# Forward overall-order status transitions available to management staff.
ADMIN_ORDER_STATUS_TRANSITIONS = {
    OrderStatus.PLACED: frozenset(
        {
            OrderStatus.CONFIRMED,
            OrderStatus.IN_PROGRESS,
        }
    ),
    OrderStatus.CONFIRMED: frozenset(
        {
            OrderStatus.IN_PROGRESS,
            OrderStatus.COMPLETED,
        }
    ),
    OrderStatus.IN_PROGRESS: frozenset(
        {
            OrderStatus.COMPLETED,
        }
    ),
    OrderStatus.PARTIALLY_CANCELLED: frozenset(
        {
            OrderStatus.IN_PROGRESS,
            OrderStatus.COMPLETED,
        }
    ),
}

ADMIN_PAYMENT_STATUS_TRANSITIONS = {
    PaymentStatus.PENDING: frozenset(
        {
            PaymentStatus.COLLECTED,
            PaymentStatus.CANCELLED,
        }
    ),
}

# Active StoreOrders that may be completed by management (fulfillment done).
_STORE_ORDER_COMPLETABLE_STATUSES = STORE_ORDER_READY_TIER_STATUSES | frozenset(
    {StoreOrderStatus.COMPLETED}
)


def _client_ip(request):
    if request is None:
        return None
    try:
        from accounts.audit_ip import get_client_ip

        return get_client_ip(request)
    except Exception:
        return None


def available_admin_order_statuses(order) -> list[str]:
    """Return OrderStatus values the management portal may move this order to."""
    if order.status == OrderStatus.CANCELLED:
        return []
    allowed = set(ADMIN_ORDER_STATUS_TRANSITIONS.get(order.status, frozenset()))
    if OrderStatus.COMPLETED in allowed:
        active = [
            so
            for so in order.store_orders.all()
            if so.status not in STORE_ORDER_NON_CHARGEABLE_STATUSES
        ]
        if any(so.status not in _STORE_ORDER_COMPLETABLE_STATUSES for so in active):
            allowed.discard(OrderStatus.COMPLETED)
    return sorted(allowed)


def admin_can_cancel_order(order) -> bool:
    if order.status == OrderStatus.CANCELLED:
        return False
    return order.status in ADMIN_CANCELLABLE_ORDER_STATUSES


def available_admin_payment_statuses(order) -> list[str]:
    if order.status == OrderStatus.CANCELLED:
        return []
    allowed = set(
        ADMIN_PAYMENT_STATUS_TRANSITIONS.get(order.payment_status, frozenset())
    )
    # MVP: cash collection only after successful fulfillment.
    if (
        PaymentStatus.COLLECTED in allowed
        and order.status != OrderStatus.COMPLETED
    ):
        allowed.discard(PaymentStatus.COLLECTED)
    return sorted(allowed)


def _active_store_orders(order):
    return [
        so
        for so in StoreOrder.objects.select_for_update()
        .filter(order=order)
        .order_by("pk")
        if so.status not in STORE_ORDER_NON_CHARGEABLE_STATUSES
    ]


def _complete_active_store_orders(*, order, actor, reason, request=None):
    """
    Mark every still-active StoreOrder COMPLETED so parent COMPLETED stays
    consistent with later store-order sync.
    """
    active = _active_store_orders(order)
    not_ready = [
        so
        for so in active
        if so.status not in _STORE_ORDER_COMPLETABLE_STATUSES
    ]
    if not_ready:
        numbers = ", ".join(so.store_order_number for so in not_ready)
        raise ValidationError(
            {
                "status": (
                    "Cannot complete the order until every active store order "
                    "is ready for fulfillment "
                    f"(not ready: {numbers})."
                )
            }
        )

    for store_order in active:
        if store_order.status == StoreOrderStatus.COMPLETED:
            continue
        old_status = store_order.status
        store_order.status = StoreOrderStatus.COMPLETED
        store_order.save(update_fields=["status", "updated_at"])
        StoreOrderStatusHistory.objects.create(
            store_order=store_order,
            old_status=old_status,
            new_status=StoreOrderStatus.COMPLETED,
            changed_by=actor,
            reason=(
                (reason or "").strip()
                or f"Order {order.order_number} marked completed by management."
            ),
            ip_address=_client_ip(request),
        )


@transaction.atomic
def update_order_status(
    *,
    order,
    new_status,
    actor,
    reason="",
    request=None,
):
    """
    Apply a permitted overall Order status transition.

    Cancellation must use ``cancel_order_by_admin`` (and cancel_order permission).
    Completing an order requires every active StoreOrder to be ready (or already
    completed) and cascades those rows to COMPLETED.
    """
    order = Order.objects.select_for_update().get(pk=order.pk)
    cleaned_status = (new_status or "").strip()
    if not cleaned_status:
        raise ValidationError({"status": "A new status is required."})
    if cleaned_status == OrderStatus.CANCELLED:
        raise ValidationError(
            {
                "status": (
                    "Use administrative cancellation to cancel an order."
                )
            }
        )
    if cleaned_status == order.status:
        return order

    allowed = ADMIN_ORDER_STATUS_TRANSITIONS.get(order.status, frozenset())
    if cleaned_status not in allowed:
        raise ValidationError(
            {
                "status": (
                    f"Order {order.order_number} cannot move from "
                    f"{order.status} to {cleaned_status}."
                )
            }
        )

    if cleaned_status == OrderStatus.COMPLETED:
        _complete_active_store_orders(
            order=order,
            actor=actor,
            reason=reason,
            request=request,
        )

    old_status = order.status
    order.status = cleaned_status
    order.save(update_fields=["status", "updated_at"])
    OrderStatusHistory.objects.create(
        order=order,
        old_status=old_status,
        new_status=cleaned_status,
        changed_by=actor,
        reason=(reason or "").strip(),
        ip_address=_client_ip(request),
    )
    order.refresh_from_db()
    return order


@transaction.atomic
def update_order_payment_status(
    *,
    order,
    new_payment_status,
    actor,
    reason="",
    request=None,
):
    """
    Apply a permitted payment-status transition.

    Customers and Store Users must never call this. COLLECTED is for successful
    COD / pay-at-pickup cash collection after fulfillment (Order COMPLETED).
    """
    order = Order.objects.select_for_update().get(pk=order.pk)
    cleaned = (new_payment_status or "").strip()
    if not cleaned:
        raise ValidationError(
            {"payment_status": "A new payment status is required."}
        )
    if cleaned == order.payment_status:
        return order

    allowed = set(
        ADMIN_PAYMENT_STATUS_TRANSITIONS.get(order.payment_status, frozenset())
    )
    if cleaned == PaymentStatus.COLLECTED and order.status != OrderStatus.COMPLETED:
        raise ValidationError(
            {
                "payment_status": (
                    "Payment can only be marked collected after the order "
                    "is completed."
                )
            }
        )
    if cleaned not in allowed:
        raise ValidationError(
            {
                "payment_status": (
                    f"Payment status cannot move from "
                    f"{order.payment_status} to {cleaned}."
                )
            }
        )

    old_payment = order.payment_status
    order.payment_status = cleaned
    order.save(update_fields=["payment_status", "updated_at"])
    # Reuse order status history with a payment note so audits remain visible.
    OrderStatusHistory.objects.create(
        order=order,
        old_status=order.status,
        new_status=order.status,
        changed_by=actor,
        reason=(
            f"Payment status {old_payment} → {cleaned}"
            + (f": {(reason or '').strip()}" if (reason or "").strip() else "")
        ),
        ip_address=_client_ip(request),
    )
    order.refresh_from_db()
    return order


def admin_cancel_order(*, order, actor, reason, request=None):
    """Thin wrapper validating eligibility then cancelling via the service layer."""
    validate_admin_order_cancellation(order=order)
    return cancel_order_by_admin(
        order=order,
        actor=actor,
        reason=reason,
        request=request,
    )
