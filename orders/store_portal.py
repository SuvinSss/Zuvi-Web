"""Store-portal helpers for StoreOrder management (ownership-scoped)."""

from __future__ import annotations

from django.db.models import Count, Prefetch, Q, Sum
from django.shortcuts import get_object_or_404

from .models import OrderItem, StoreOrder, StoreOrderStatus
from .store_status import available_store_order_actions

STORE_DASHBOARD_RECENT_ORDER_LIMIT = 5


def portal_store_orders_queryset(store):
    """
    StoreOrders for ``store`` only.

    Never accept a store id from the client — always pass ``request.store``.
    """
    if store is None:
        return StoreOrder.objects.none()
    return (
        StoreOrder.objects.filter(store=store)
        .select_related("order", "pickup_location", "pickup_location__address")
        .annotate(item_count=Sum("items__quantity"))
        .order_by("-created_at", "-pk")
    )


def get_store_order_dashboard_stats(store):
    """
    Store-portal order card counts, scoped to ``store`` only.

    Processing maps to ``PREPARING`` (portal action key ``processing``).
    """
    if store is None:
        return {
            "pending": 0,
            "accepted": 0,
            "processing": 0,
            "ready": 0,
        }
    return StoreOrder.objects.filter(store_id=store.pk).aggregate(
        pending=Count("id", filter=Q(status=StoreOrderStatus.PENDING)),
        accepted=Count("id", filter=Q(status=StoreOrderStatus.ACCEPTED)),
        processing=Count("id", filter=Q(status=StoreOrderStatus.PREPARING)),
        ready=Count("id", filter=Q(status=StoreOrderStatus.READY)),
    )


def get_store_recent_store_orders(
    store, *, limit=STORE_DASHBOARD_RECENT_ORDER_LIMIT
):
    """Newest StoreOrders for the logged-in store dashboard."""
    if store is None:
        return []
    return list(portal_store_orders_queryset(store)[:limit])


def get_portal_store_order_or_404(store, store_order_number):
    """
    Return one StoreOrder owned by ``store``, or raise Http404.

    Another store's number must look missing (404), not forbidden.
    """
    queryset = (
        StoreOrder.objects.filter(store=store)
        .select_related(
            "order",
            "pickup_location",
            "pickup_location__address",
        )
        .prefetch_related(
            Prefetch(
                "items",
                queryset=OrderItem.objects.order_by("pk"),
            ),
            "status_history",
        )
    )
    return get_object_or_404(queryset, store_order_number=store_order_number)


def store_order_action_context(store_order):
    actions = available_store_order_actions(store_order)
    return {
        "available_actions": actions,
        "can_accept": "accept" in actions,
        "can_reject": "reject" in actions,
        "can_processing": "processing" in actions,
        "can_ready": "ready" in actions,
    }
