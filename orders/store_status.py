"""StoreOrder fulfillment status transitions for the store portal."""

from __future__ import annotations

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from stores.status import store_allows_portal_access

from .cancellation import reject_store_order
from .models import Order, StoreOrder, StoreOrderStatus, StoreOrderStatusHistory
from .order_status_sync import sync_order_status_from_store_orders


def _client_ip(request):
    if request is None:
        return None
    try:
        from accounts.audit_ip import get_client_ip

        return get_client_ip(request)
    except Exception:
        return None


def _require_active_store(*, store):
    if not store_allows_portal_access(store):
        raise ValidationError(
            {"store": "Suspended or inactive stores cannot process orders."}
        )


# action_key → (allowed source statuses, target status)
STORE_ORDER_FORWARD_TRANSITIONS = {
    "accept": (
        frozenset({StoreOrderStatus.PENDING}),
        StoreOrderStatus.ACCEPTED,
    ),
    "processing": (
        frozenset({StoreOrderStatus.ACCEPTED}),
        StoreOrderStatus.PREPARING,
    ),
    "ready": (
        frozenset({StoreOrderStatus.PREPARING}),
        StoreOrderStatus.READY,
    ),
}


def available_store_order_actions(store_order) -> list[str]:
    """Return action keys currently valid for this StoreOrder."""
    actions = []
    status = store_order.status
    for action, (sources, _target) in STORE_ORDER_FORWARD_TRANSITIONS.items():
        if status in sources:
            actions.append(action)
    if status == StoreOrderStatus.PENDING:
        actions.append("reject")
    return actions


@transaction.atomic
def transition_store_order(
    *,
    store_order,
    store,
    action,
    actor=None,
    reason="",
    request=None,
):
    """
    Apply a forward StoreOrder status transition.

    ``store`` must be the caller's resolved store (never a client-supplied id).
    Invalid transitions raise ValidationError. Ownership mismatches raise
    PermissionDenied.
    """
    _require_active_store(store=store)

    # Lock Order before StoreOrder so the order matches cancel/reject
    # (_lock_order_graph) and concurrent accept + cancel cannot deadlock.
    order_id = StoreOrder.objects.values_list("order_id", flat=True).get(
        pk=store_order.pk
    )
    order = Order.objects.select_for_update().get(pk=order_id)
    store_order = (
        StoreOrder.objects.select_for_update()
        .select_related("order", "store")
        .get(pk=store_order.pk)
    )
    if store_order.store_id != store.pk:
        raise PermissionDenied(
            "Store users may only manage store orders for their own store."
        )

    action = (action or "").strip().lower()
    if action == "reject":
        cleaned_reason = (reason or "").strip()
        if not cleaned_reason:
            raise ValidationError({"reason": "A rejection reason is required."})
        return reject_store_order(
            store_order=store_order,
            store=store,
            reason=cleaned_reason,
            actor=actor,
            request=request,
        )

    if action not in STORE_ORDER_FORWARD_TRANSITIONS:
        raise ValidationError({"action": f"Unknown store order action '{action}'."})

    allowed_sources, new_status = STORE_ORDER_FORWARD_TRANSITIONS[action]
    if store_order.status not in allowed_sources:
        raise ValidationError(
            {
                "status": (
                    f"Store order {store_order.store_order_number} cannot "
                    f"move to {new_status} from {store_order.status}."
                )
            }
        )

    # Idempotent if somehow already at target (should not happen with source check).
    if store_order.status == new_status:
        return store_order

    old_status = store_order.status
    store_order.status = new_status
    store_order.save(update_fields=["status", "updated_at"])
    StoreOrderStatusHistory.objects.create(
        store_order=store_order,
        old_status=old_status,
        new_status=new_status,
        changed_by=actor,
        reason=(reason or "").strip(),
        ip_address=_client_ip(request),
    )
    sync_order_status_from_store_orders(
        order=order,
        actor=actor,
        reason=(
            (reason or "").strip()
            or (
                f"Store order {store_order.store_order_number} "
                f"{old_status} → {new_status}"
            )
        ),
        request=request,
    )
    store_order.refresh_from_db()
    return store_order


def accept_store_order(*, store_order, store, actor=None, reason="", request=None):
    return transition_store_order(
        store_order=store_order,
        store=store,
        action="accept",
        actor=actor,
        reason=reason,
        request=request,
    )


def mark_store_order_processing(
    *, store_order, store, actor=None, reason="", request=None
):
    return transition_store_order(
        store_order=store_order,
        store=store,
        action="processing",
        actor=actor,
        reason=reason,
        request=request,
    )


def mark_store_order_ready(*, store_order, store, actor=None, reason="", request=None):
    return transition_store_order(
        store_order=store_order,
        store=store,
        action="ready",
        actor=actor,
        reason=reason,
        request=request,
    )
