"""Queryset helpers for management-portal Order screens."""

from __future__ import annotations

from decimal import Decimal

from django.db.models import Count, DecimalField, Exists, OuterRef, Prefetch, Q, Sum
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date

from inventory.models import InventoryTransaction
from inventory.services import (
    order_item_deduct_reference,
    order_item_restore_reference,
)

from .models import Order, OrderItem, OrderStatus, StoreOrder
from .order_status_sync import STORE_ORDER_READY_TIER_STATUSES


def get_order_dashboard_stats():
    """
    Management order card metrics in one aggregate query.

    Ready Orders are Orders that have at least one StoreOrder in the ready
    tier (Order has no READY status of its own). Call only when the viewer
    is authorized for ``orders.view_order``.
    """
    today = timezone.localdate()
    has_ready_store_order = Exists(
        StoreOrder.objects.filter(
            order_id=OuterRef("pk"),
            status__in=STORE_ORDER_READY_TIER_STATUSES,
        )
    )
    return (
        Order.objects.annotate(has_ready_store_order=has_ready_store_order)
        .aggregate(
            orders_today=Count("id", filter=Q(placed_at__date=today)),
            pending=Count("id", filter=Q(status=OrderStatus.PLACED)),
            processing=Count("id", filter=Q(status=OrderStatus.IN_PROGRESS)),
            ready=Count("id", filter=Q(has_ready_store_order=True)),
            cancelled=Count("id", filter=Q(status=OrderStatus.CANCELLED)),
            total_order_value=Coalesce(
                Sum("grand_total"),
                Decimal("0.00"),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            ),
        )
    )


def management_orders_queryset():
    """Base Order queryset for management list/detail with useful annotations."""
    return (
        Order.objects.select_related(
            "customer",
            "customer__user",
            "cancelled_by",
        )
        .annotate(
            store_count=Count("store_orders", distinct=True),
            item_count=Count("store_orders__items", distinct=True),
        )
        .order_by("-placed_at", "-pk")
    )


def apply_management_order_filters(queryset, params):
    """
    Apply list search and filters from request.GET-style params.

    Search covers order number, store-order number, customer name/email/phone.
    """
    search_query = (params.get("q") or "").strip()
    status_filter = (params.get("status") or "").strip()
    store_filter = (params.get("store") or "").strip()
    customer_filter = (params.get("customer") or "").strip()
    fulfillment_filter = (params.get("fulfillment_type") or "").strip()
    payment_method_filter = (params.get("payment_method") or "").strip()
    payment_status_filter = (params.get("payment_status") or "").strip()
    date_from = (params.get("date_from") or "").strip()
    date_to = (params.get("date_to") or "").strip()

    if search_query:
        queryset = queryset.filter(
            Q(order_number__icontains=search_query)
            | Q(store_orders__store_order_number__icontains=search_query)
            | Q(customer__user__first_name__icontains=search_query)
            | Q(customer__user__last_name__icontains=search_query)
            | Q(customer__user__email__icontains=search_query)
            | Q(customer__user__phone_number__icontains=search_query)
            | Q(customer__user__username__icontains=search_query)
        ).distinct()

    if status_filter:
        queryset = queryset.filter(status=status_filter)
    if store_filter:
        queryset = queryset.filter(store_orders__store_id=store_filter).distinct()
    if customer_filter:
        queryset = queryset.filter(customer_id=customer_filter)
    if fulfillment_filter:
        queryset = queryset.filter(fulfillment_type=fulfillment_filter)
    if payment_method_filter:
        queryset = queryset.filter(payment_method=payment_method_filter)
    if payment_status_filter:
        queryset = queryset.filter(payment_status=payment_status_filter)

    parsed_from = parse_date(date_from) if date_from else None
    parsed_to = parse_date(date_to) if date_to else None
    if parsed_from:
        queryset = queryset.filter(placed_at__date__gte=parsed_from)
    if parsed_to:
        queryset = queryset.filter(placed_at__date__lte=parsed_to)

    return queryset, {
        "search_query": search_query,
        "status_filter": status_filter,
        "store_filter": store_filter,
        "customer_filter": customer_filter,
        "fulfillment_filter": fulfillment_filter,
        "payment_method_filter": payment_method_filter,
        "payment_status_filter": payment_status_filter,
        "date_from": date_from,
        "date_to": date_to,
    }


def get_management_order_or_404(order_number):
    return get_object_or_404(
        Order.objects.select_related(
            "customer",
            "customer__user",
            "cancelled_by",
            "delivery_address",
            "delivery_address__address",
        ).prefetch_related(
            Prefetch(
                "store_orders",
                queryset=StoreOrder.objects.select_related(
                    "store",
                    "pickup_location",
                    "pickup_location__address",
                )
                .prefetch_related(
                    Prefetch(
                        "items",
                        queryset=OrderItem.objects.select_related("product").order_by(
                            "pk"
                        ),
                    ),
                    "status_history",
                )
                .order_by("pk"),
            ),
            "status_history",
        ),
        order_number=order_number,
    )


def get_management_store_order_or_404(store_order_number):
    return get_object_or_404(
        StoreOrder.objects.select_related(
            "order",
            "order__customer",
            "order__customer__user",
            "store",
            "pickup_location",
            "pickup_location__address",
        ).prefetch_related(
            Prefetch(
                "items",
                queryset=OrderItem.objects.select_related("product").order_by("pk"),
            ),
            "status_history",
            "order__status_history",
        ),
        store_order_number=store_order_number,
    )


def inventory_transactions_for_order_items(order_items):
    """
    Load inventory ledger rows referenced by OrderItem deduct/restore keys.

    Returns a list of dicts: {item, deduct, restore} preserving item order.
    """
    items = list(order_items)
    if not items:
        return []

    references = []
    for item in items:
        references.append(order_item_deduct_reference(item.pk))
        references.append(order_item_restore_reference(item.pk))

    by_reference = {
        txn.reference: txn
        for txn in InventoryTransaction.objects.filter(reference__in=references)
        .select_related("product", "store", "created_by")
        .order_by("pk")
    }

    rows = []
    for item in items:
        rows.append(
            {
                "item": item,
                "deduct": by_reference.get(order_item_deduct_reference(item.pk)),
                "restore": by_reference.get(order_item_restore_reference(item.pk)),
                "deduct_reference": order_item_deduct_reference(item.pk),
                "restore_reference": order_item_restore_reference(item.pk),
            }
        )
    return rows
