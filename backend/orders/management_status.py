"""Management-portal Order status and payment transitions."""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .cancellation import cancel_order_by_admin
from .models import (
    Order,
    OrderPaymentHistory,
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

# Backward corrections. Each one requires a correction note and is recorded in
# the audit history. Inventory is never touched by these moves.
ADMIN_ORDER_STATUS_REVERSALS = {
    OrderStatus.COMPLETED: frozenset({OrderStatus.IN_PROGRESS}),
}

ADMIN_PAYMENT_STATUS_REVERSALS = {
    PaymentStatus.COLLECTED: frozenset({PaymentStatus.PENDING}),
}

CORRECTION_NOTE_REQUIRED_MESSAGE = (
    "A correction note is required when reversing a status."
)

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


def is_order_status_reversal(order, new_status) -> bool:
    return new_status in ADMIN_ORDER_STATUS_REVERSALS.get(order.status, frozenset())


def is_payment_status_reversal(order, new_payment_status) -> bool:
    return new_payment_status in ADMIN_PAYMENT_STATUS_REVERSALS.get(
        order.payment_status, frozenset()
    )


def _order_reversals_allowed(order) -> frozenset:
    # Delivery cannot be undone while cash is recorded as collected; reverse
    # the payment first so payment is never COLLECTED on an undelivered order.
    if order.payment_status == PaymentStatus.COLLECTED:
        return frozenset()
    return ADMIN_ORDER_STATUS_REVERSALS.get(order.status, frozenset())


def available_admin_order_statuses(order) -> list[str]:
    """Return OrderStatus values the management portal may move this order to."""
    if order.status == OrderStatus.CANCELLED:
        return []
    allowed = set(ADMIN_ORDER_STATUS_TRANSITIONS.get(order.status, frozenset()))
    allowed |= _order_reversals_allowed(order)
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
    allowed |= ADMIN_PAYMENT_STATUS_REVERSALS.get(order.payment_status, frozenset())
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


def _reopen_completed_store_orders(*, order, actor, correction_note, request=None):
    """
    Undo the COMPLETED cascade from ``_complete_active_store_orders``.

    Each StoreOrder returns to the ready-tier status it held before completion
    (READY when unknown) so a later Delivered update can cascade again.
    """
    for store_order in StoreOrder.objects.select_for_update().filter(
        order=order,
        status=StoreOrderStatus.COMPLETED,
    ).order_by("pk"):
        last_completion = (
            store_order.status_history.filter(
                new_status=StoreOrderStatus.COMPLETED
            )
            .order_by("-created_at", "-pk")
            .first()
        )
        restored_status = StoreOrderStatus.READY
        if (
            last_completion
            and last_completion.old_status in STORE_ORDER_READY_TIER_STATUSES
        ):
            restored_status = last_completion.old_status
        store_order.status = restored_status
        store_order.save(update_fields=["status", "updated_at"])
        StoreOrderStatusHistory.objects.create(
            store_order=store_order,
            old_status=StoreOrderStatus.COMPLETED,
            new_status=restored_status,
            changed_by=actor,
            reason=f"Correction: {correction_note}",
            ip_address=_client_ip(request),
        )


@transaction.atomic
def update_order_status(
    *,
    order,
    new_status,
    actor,
    reason="",
    correction_note="",
    request=None,
):
    """
    Apply a permitted overall Order status transition.

    Cancellation must use ``cancel_order_by_admin`` (and cancel_order permission).
    Marking an order Delivered (COMPLETED) requires every active StoreOrder to be
    ready (or already completed), cascades those rows to COMPLETED and records
    ``delivered_at``. Reversing Delivered requires ``correction_note``.
    Stock is not touched: it is deducted once at checkout.
    """
    order = Order.objects.select_for_update().get(pk=order.pk)
    correction_note = (correction_note or "").strip()
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

    is_reversal = is_order_status_reversal(order, cleaned_status)
    if is_reversal:
        if not correction_note:
            raise ValidationError({"correction_note": CORRECTION_NOTE_REQUIRED_MESSAGE})
        if cleaned_status not in _order_reversals_allowed(order):
            raise ValidationError(
                {
                    "status": (
                        "Reverse the collected payment before reversing "
                        "delivery."
                    )
                }
            )
    else:
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

    update_fields = ["status", "updated_at"]
    if cleaned_status == OrderStatus.COMPLETED:
        _complete_active_store_orders(
            order=order,
            actor=actor,
            reason=reason,
            request=request,
        )
        order.delivered_at = timezone.now()
        update_fields.append("delivered_at")
    if is_reversal and order.status == OrderStatus.COMPLETED:
        _reopen_completed_store_orders(
            order=order,
            actor=actor,
            correction_note=correction_note,
            request=request,
        )
        order.delivered_at = None
        update_fields.append("delivered_at")

    old_status = order.status
    order.status = cleaned_status
    order.save(update_fields=update_fields)
    OrderStatusHistory.objects.create(
        order=order,
        old_status=old_status,
        new_status=cleaned_status,
        changed_by=actor,
        reason=(reason or "").strip(),
        correction_note=correction_note if is_reversal else "",
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
    correction_note="",
    request=None,
):
    """
    Apply a permitted payment-status transition.

    Customers and Store Users must never call this. COLLECTED is for successful
    COD / pay-at-pickup cash collection after delivery (Order COMPLETED) and
    records ``payment_collected_at``. Reversing COLLECTED requires
    ``correction_note``. Every change is written to OrderPaymentHistory.
    """
    order = Order.objects.select_for_update().get(pk=order.pk)
    correction_note = (correction_note or "").strip()
    cleaned = (new_payment_status or "").strip()
    if not cleaned:
        raise ValidationError(
            {"payment_status": "A new payment status is required."}
        )
    if cleaned == order.payment_status:
        return order

    is_reversal = is_payment_status_reversal(order, cleaned)
    if is_reversal and not correction_note:
        raise ValidationError({"correction_note": CORRECTION_NOTE_REQUIRED_MESSAGE})

    allowed = set(
        ADMIN_PAYMENT_STATUS_TRANSITIONS.get(order.payment_status, frozenset())
    )
    allowed |= ADMIN_PAYMENT_STATUS_REVERSALS.get(order.payment_status, frozenset())
    if cleaned == PaymentStatus.COLLECTED and order.status != OrderStatus.COMPLETED:
        raise ValidationError(
            {
                "payment_status": (
                    "Payment can only be marked collected after the order "
                    "is delivered."
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
    update_fields = ["payment_status", "updated_at"]
    if cleaned == PaymentStatus.COLLECTED:
        order.payment_collected_at = timezone.now()
        update_fields.append("payment_collected_at")
    elif old_payment == PaymentStatus.COLLECTED:
        order.payment_collected_at = None
        update_fields.append("payment_collected_at")
    order.save(update_fields=update_fields)
    OrderPaymentHistory.objects.create(
        order=order,
        old_payment_status=old_payment,
        new_payment_status=cleaned,
        changed_by=actor,
        reason=(reason or "").strip(),
        correction_note=correction_note if is_reversal else "",
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
