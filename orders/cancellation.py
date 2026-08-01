"""
Order cancellation and store-rejection services with once-only stock restore.

Checkout deducts stock once. Cancel / reject restore stock through the Phase 5
inventory service, gated by ``OrderItem.stock_restored`` and immutable
order-item references so repeated requests never restore twice.
"""

from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from catalog.models import Product
from inventory.services import (
    order_item_restore_reference,
    restore_order_stock,
)

from .models import (
    Order,
    OrderItem,
    OrderStatus,
    OrderStatusHistory,
    PaymentStatus,
    StoreOrder,
    StoreOrderStatus,
    StoreOrderStatusHistory,
)
from .order_status_sync import sync_order_status_from_store_orders
from .status import (
    CUSTOMER_CANCELABLE_STORE_STATUSES,
    STORE_ORDER_ACTIVE_STATUSES,
    STORE_ORDER_NON_CHARGEABLE_STATUSES,
    validate_admin_order_cancellation,
    validate_customer_order_cancellation,
    validate_store_order_rejection,
)


def _client_ip(request):
    if request is None:
        return None
    try:
        from accounts.audit_ip import get_client_ip

        return get_client_ip(request)
    except Exception:
        return None


def _require_reason(reason, *, field="reason"):
    cleaned = (reason or "").strip()
    if not cleaned:
        raise ValidationError({field: "A reason is required."})
    return cleaned


def _lock_order_graph(*, order):
    """
    Lock Order, StoreOrders, OrderItems and Product inventory rows.

    Call inside ``transaction.atomic()``. Returns
    (order, store_orders, order_items, locked_products_by_id).
    """
    order = (
        Order.objects.select_for_update()
        .select_related("customer")
        .get(pk=order.pk)
    )
    store_orders = list(
        StoreOrder.objects.select_for_update()
        .filter(order=order)
        .order_by("pk")
    )
    order_items = list(
        OrderItem.objects.select_for_update()
        .select_related("product", "store_order", "store_order__store")
        .filter(store_order__order=order)
        .order_by("pk")
    )
    product_ids = sorted({item.product_id for item in order_items})
    locked_products = {
        product.pk: product
        for product in Product.objects.select_for_update()
        .filter(pk__in=product_ids)
        .order_by("pk")
    }
    return order, store_orders, order_items, locked_products


def _mark_order_items_cancelled(*, order_items, now=None):
    """Mark OrderItem rows cancelled without deleting them."""
    now = now or timezone.now()
    for item in order_items:
        if item.is_cancelled:
            continue
        item.is_cancelled = True
        item.cancelled_at = now
        item.save(update_fields=["is_cancelled", "cancelled_at"])


def _mark_order_items_rejected(*, order_items, now=None):
    """Mark OrderItem rows rejected without deleting them."""
    now = now or timezone.now()
    for item in order_items:
        if item.is_rejected:
            continue
        item.is_rejected = True
        item.rejected_at = now
        item.save(update_fields=["is_rejected", "rejected_at"])


@transaction.atomic
def restore_order_items_stock(
    *,
    order_items,
    actor=None,
    reason,
    request=None,
    locked_products=None,
):
    """
    Restore sellable stock for OrderItems that have not yet been restored.

    Locks each OrderItem and Product row when not already locked by the caller.
    Items with ``stock_restored=True`` are skipped. Each restoration uses the
    immutable ``order_item_restore_reference`` so a repeated call cannot restore
    twice even if the boolean guard were bypassed. Returns the list of
    OrderItems that were restored in this call.
    """
    restored = []
    item_ids = sorted({item.pk for item in order_items if item is not None})
    if not item_ids:
        return restored

    locked_items = list(
        OrderItem.objects.select_for_update()
        .select_related("product", "store_order", "store_order__store")
        .filter(pk__in=item_ids)
        .order_by("pk")
    )
    if locked_products is None:
        product_ids = sorted({item.product_id for item in locked_items})
        locked_products = {
            product.pk: product
            for product in Product.objects.select_for_update()
            .filter(pk__in=product_ids)
            .order_by("pk")
        }

    now = timezone.now()
    for item in locked_items:
        if item.stock_restored:
            continue
        product = locked_products[item.product_id]
        store = item.store_order.store
        restore_order_stock(
            product=product,
            store=store,
            quantity=item.quantity,
            actor=actor,
            reason=reason,
            notes=(
                f"Restored from order item {item.pk} "
                f"({item.product_code} × {item.quantity})."
            ),
            reference=order_item_restore_reference(item.pk),
            request=request,
        )
        item.stock_restored = True
        item.stock_restored_at = now
        item.save(update_fields=["stock_restored", "stock_restored_at"])
        restored.append(item)
    return restored


def _cancel_store_order_row(*, store_order, actor, reason, request=None):
    """Mark an eligible StoreOrder as CANCELLED and write history."""
    if store_order.status in (
        StoreOrderStatus.CANCELLED,
        StoreOrderStatus.REJECTED,
        StoreOrderStatus.COMPLETED,
    ):
        return store_order

    old_status = store_order.status
    store_order.status = StoreOrderStatus.CANCELLED
    store_order.save(update_fields=["status", "updated_at"])
    StoreOrderStatusHistory.objects.create(
        store_order=store_order,
        old_status=old_status,
        new_status=StoreOrderStatus.CANCELLED,
        changed_by=actor,
        reason=reason,
        ip_address=_client_ip(request),
    )
    return store_order


def _mark_order_cancelled(*, order, actor, reason, request=None):
    if order.status == OrderStatus.CANCELLED:
        return order

    old_status = order.status
    order.status = OrderStatus.CANCELLED
    order.cancellation_reason = reason
    order.cancelled_at = timezone.now()
    order.cancelled_by = actor
    update_fields = [
        "status",
        "cancellation_reason",
        "cancelled_at",
        "cancelled_by",
        "updated_at",
    ]
    if order.payment_status == PaymentStatus.PENDING:
        order.payment_status = PaymentStatus.CANCELLED
        update_fields.append("payment_status")
    order.save(update_fields=update_fields)
    OrderStatusHistory.objects.create(
        order=order,
        old_status=old_status,
        new_status=OrderStatus.CANCELLED,
        changed_by=actor,
        reason=reason,
        ip_address=_client_ip(request),
    )
    return order


def _recalculate_order_payable_totals(*, order, store_orders=None):
    """
    Recalculate customer-payable Order totals from still-chargeable StoreOrders.

    Rejected and cancelled StoreOrders no longer contribute to the payable total.
    Historical StoreOrder snapshot amounts are left unchanged.
    """
    if store_orders is None:
        store_orders = list(StoreOrder.objects.filter(order=order).order_by("pk"))

    chargeable = [
        so
        for so in store_orders
        if so.status not in STORE_ORDER_NON_CHARGEABLE_STATUSES
    ]
    items_subtotal = sum(
        (so.items_subtotal for so in chargeable),
        Decimal("0.00"),
    ).quantize(Decimal("0.01"))
    delivery_charge = sum(
        (so.delivery_charge for so in chargeable),
        Decimal("0.00"),
    ).quantize(Decimal("0.01"))
    # Scale any existing discount with the remaining chargeable subtotal so a
    # partial reject cannot leave the full parent discount against fewer lines.
    previous_subtotal = order.items_subtotal or Decimal("0.00")
    previous_discount = order.discount_total or Decimal("0.00")
    if not chargeable or previous_discount <= 0 or previous_subtotal <= 0:
        discount_total = Decimal("0.00")
    else:
        discount_total = (
            previous_discount * items_subtotal / previous_subtotal
        ).quantize(Decimal("0.01"))
    grand_total = (items_subtotal + delivery_charge - discount_total).quantize(
        Decimal("0.01")
    )
    if grand_total < 0:
        grand_total = Decimal("0.00")

    order.items_subtotal = items_subtotal
    order.delivery_charge = delivery_charge
    order.discount_total = discount_total
    order.grand_total = grand_total
    order.save(
        update_fields=[
            "items_subtotal",
            "delivery_charge",
            "discount_total",
            "grand_total",
            "updated_at",
        ]
    )
    return order


@transaction.atomic
def cancel_customer_order(
    *,
    order,
    customer,
    reason,
    actor=None,
    request=None,
):
    """
    Full customer cancellation under row locks.

    Allowed when the order belongs to ``customer``, parent status is PLACED
    (pending) or CONFIRMED, no StoreOrder is processing/ready/completed, and
    the order is not already cancelled (already-cancelled retries are
    idempotent). Restores inventory exactly once via the Phase 5 service.
    Records are never deleted.
    """
    order, store_orders, order_items, locked_products = _lock_order_graph(
        order=order
    )

    if order.customer_id != customer.pk:
        raise PermissionDenied("Customers may only cancel their own orders.")

    reason = _require_reason(reason)
    validate_customer_order_cancellation(
        order=order,
        store_orders=store_orders,
    )

    already_cancelled = order.status == OrderStatus.CANCELLED
    if not already_cancelled:
        for store_order in store_orders:
            if store_order.status in CUSTOMER_CANCELABLE_STORE_STATUSES:
                _cancel_store_order_row(
                    store_order=store_order,
                    actor=actor,
                    reason=reason,
                    request=request,
                )
        _mark_order_cancelled(
            order=order,
            actor=actor,
            reason=reason,
            request=request,
        )
        _mark_order_items_cancelled(order_items=order_items)

    restore_order_items_stock(
        order_items=order_items,
        actor=actor,
        reason=f"Customer cancellation of {order.order_number}: {reason}",
        request=request,
        locked_products=locked_products,
    )
    # Ensure cancelled markers stick even on an idempotent retry that missed them.
    _mark_order_items_cancelled(order_items=order_items)
    # Refresh statuses after cancels so payable totals drop to zero.
    store_orders = list(StoreOrder.objects.filter(order=order).order_by("pk"))
    _recalculate_order_payable_totals(order=order, store_orders=store_orders)
    order.refresh_from_db()
    return order


@transaction.atomic
def reject_store_order(
    *,
    store_order,
    store,
    reason,
    actor=None,
    request=None,
):
    """
    Store rejection: reject one PENDING StoreOrder and restore only its items.

    Locks the parent Order graph and relevant inventory rows. Marks OrderItems
    as rejected, restores stock exactly once, writes StoreOrder status history,
    recalculates the customer-payable Order total, and syncs overall Order
    status to PARTIALLY_CANCELLED or CANCELLED as appropriate.
    """
    # Lock Order first, then StoreOrders / items / products, to keep lock order
    # consistent with cancel paths and avoid deadlocks.
    order, store_orders, all_items, locked_products = _lock_order_graph(
        order=store_order.order
    )
    locked_store_order = next(
        (so for so in store_orders if so.pk == store_order.pk),
        None,
    )
    if locked_store_order is None:
        raise ValidationError({"store_order": "Store order was not found."})
    store_order = locked_store_order

    if store_order.store_id != store.pk:
        raise PermissionDenied(
            "Store users may only reject store orders for their own store."
        )

    reason = _require_reason(reason)
    validate_store_order_rejection(store_order=store_order)

    already_rejected = store_order.status == StoreOrderStatus.REJECTED
    items = [item for item in all_items if item.store_order_id == store_order.pk]
    item_product_ids = {item.product_id for item in items}
    item_locked_products = {
        pk: product
        for pk, product in locked_products.items()
        if pk in item_product_ids
    }

    if not already_rejected:
        old_status = store_order.status
        store_order.status = StoreOrderStatus.REJECTED
        store_order.save(update_fields=["status", "updated_at"])
        StoreOrderStatusHistory.objects.create(
            store_order=store_order,
            old_status=old_status,
            new_status=StoreOrderStatus.REJECTED,
            changed_by=actor,
            reason=reason,
            ip_address=_client_ip(request),
        )
        _mark_order_items_rejected(order_items=items)

    restore_order_items_stock(
        order_items=items,
        actor=actor,
        reason=(
            f"Store rejection of {store_order.store_order_number}: {reason}"
        ),
        request=request,
        locked_products=item_locked_products,
    )
    _mark_order_items_rejected(order_items=items)

    # Keep the in-memory sibling list consistent with the row we just updated.
    store_orders = [
        store_order if so.pk == store_order.pk else so for so in store_orders
    ]
    sync_order_status_from_store_orders(
        order=order,
        store_orders=store_orders,
        actor=actor,
        reason=f"Store order rejected: {reason}",
        request=request,
    )
    _recalculate_order_payable_totals(order=order, store_orders=store_orders)

    store_order.refresh_from_db()
    return store_order


@transaction.atomic
def cancel_order_by_admin(
    *,
    order,
    actor,
    reason,
    request=None,
):
    """
    Admin cancellation: cancel remaining active StoreOrders and restore only
    OrderItems that have not already been restored (e.g. after a prior reject).
    """
    if actor is None:
        raise ValidationError({"actor": "An admin actor is required."})

    order, store_orders, order_items, locked_products = _lock_order_graph(
        order=order
    )
    reason = _require_reason(reason)
    validate_admin_order_cancellation(order=order)

    already_cancelled = order.status == OrderStatus.CANCELLED
    if not already_cancelled:
        for store_order in store_orders:
            if store_order.status in STORE_ORDER_ACTIVE_STATUSES:
                _cancel_store_order_row(
                    store_order=store_order,
                    actor=actor,
                    reason=reason,
                    request=request,
                )
        _mark_order_cancelled(
            order=order,
            actor=actor,
            reason=reason,
            request=request,
        )
        _mark_order_items_cancelled(order_items=order_items)

    restore_order_items_stock(
        order_items=order_items,
        actor=actor,
        reason=f"Admin cancellation of {order.order_number}: {reason}",
        request=request,
        locked_products=locked_products,
    )
    _mark_order_items_cancelled(order_items=order_items)
    store_orders = list(StoreOrder.objects.filter(order=order).order_by("pk"))
    _recalculate_order_payable_totals(order=order, store_orders=store_orders)
    order.refresh_from_db()
    return order
