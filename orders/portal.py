"""Customer-portal helpers for order history (ownership-scoped querysets)."""

from __future__ import annotations

from django.db.models import Count, Prefetch, Q, Sum
from django.shortcuts import get_object_or_404

from .models import Order, OrderStatus, StoreOrder
from .status import (
    CUSTOMER_CANCEL_BLOCKING_STORE_STATUSES,
    CUSTOMER_CANCELLABLE_ORDER_STATUSES,
)

CUSTOMER_DASHBOARD_RECENT_ORDER_LIMIT = 5


def customer_orders_queryset(customer):
    """
    Orders belonging to ``customer`` only, newest first.

    Annotates ``item_count`` (sum of line quantities) for list pages. Never
    accept a customer id from the request — always pass ``request.customer``.
    """
    return (
        Order.objects.filter(customer=customer)
        .annotate(item_count=Sum("store_orders__items__quantity"))
        .order_by("-placed_at", "-created_at")
    )


def get_customer_order_dashboard_stats(customer):
    """
    Customer-portal order card counts for ``customer`` only.

    Pending uses ``PLACED`` (domain equivalent of a pending customer order).
    """
    return Order.objects.filter(customer_id=customer.pk).aggregate(
        pending=Count("id", filter=Q(status=OrderStatus.PLACED)),
        total=Count("id"),
    )


def get_customer_recent_orders(customer, *, limit=CUSTOMER_DASHBOARD_RECENT_ORDER_LIMIT):
    """Newest orders for the customer dashboard recent list."""
    return list(customer_orders_queryset(customer)[:limit])


def get_customer_order_or_404(customer, order_number):
    """
    Return one Order owned by ``customer``, or raise Http404.

    Another customer's order number must look like a missing order (404), not
    403, so existence is not leaked across accounts.
    """
    queryset = (
        Order.objects.filter(customer=customer)
        .prefetch_related(
            Prefetch(
                "store_orders",
                queryset=(
                    StoreOrder.objects.select_related(
                        "pickup_location",
                        "pickup_location__address",
                    )
                    .prefetch_related("items", "status_history")
                    .order_by("pk")
                ),
            ),
            "status_history",
        )
    )
    return get_object_or_404(queryset, order_number=order_number)


def customer_can_cancel_order(order) -> bool:
    """
    Whether the customer UI may offer cancel for this order.

    Mirrors ``validate_customer_order_cancellation`` without raising.
    Already-cancelled orders are not shown as cancellable (retry is still
    idempotent at the service layer).
    """
    if order.status == OrderStatus.CANCELLED:
        return False
    if order.status not in CUSTOMER_CANCELLABLE_ORDER_STATUSES:
        return False
    store_orders = list(order.store_orders.all())
    return not any(
        so.status in CUSTOMER_CANCEL_BLOCKING_STORE_STATUSES
        for so in store_orders
    )
