"""CSV export helpers for inventory listings."""

import csv
from io import StringIO

from django.db.models import OuterRef, Q, Subquery
from django.http import HttpResponse
from django.utils import timezone

from .models import InventoryTransaction
from .status import (
    expired_q,
    expiring_soon_q,
    in_stock_q,
    low_stock_q,
    out_of_stock_q,
    stock_status_for_product,
)

CSV_FORMULA_PREFIXES = ("=", "+", "-", "@")

EXPORT_HEADERS = (
    "Store code",
    "Store name",
    "Product code",
    "SKU",
    "Product name",
    "Category",
    "Current stock",
    "Unit",
    "Low-stock threshold",
    "Stock status",
    "Last movement date",
)


def csv_safe_text(value):
    """
    Neutralize spreadsheet formula injection for exported text cells.

    Values beginning with =, +, -, or @ are prefixed with a single quote so
    spreadsheet apps treat them as plain text.
    """
    if value is None:
        return ""
    text = str(value)
    if text and text[0] in CSV_FORMULA_PREFIXES:
        return f"'{text}"
    return text


def latest_movement_at_subquery():
    latest = InventoryTransaction.objects.filter(product_id=OuterRef("pk")).order_by(
        "-created_at"
    )
    return Subquery(latest.values("created_at")[:1])


def apply_inventory_list_filters(
    queryset,
    *,
    search_query="",
    store_filter="",
    category_filter="",
    status_filter="",
    stock_filter="",
):
    """Apply the same search/filter rules used by inventory list pages."""
    search_query = (search_query or "").strip()
    store_filter = (store_filter or "").strip()
    category_filter = (category_filter or "").strip()
    status_filter = (status_filter or "").strip()
    stock_filter = (stock_filter or "").strip()

    if search_query:
        queryset = queryset.filter(
            Q(name__icontains=search_query)
            | Q(product_code__icontains=search_query)
            | Q(sku__icontains=search_query)
        )
    if store_filter:
        queryset = queryset.filter(store_id=store_filter)
    if category_filter:
        queryset = queryset.filter(category_id=category_filter)
    if status_filter:
        queryset = queryset.filter(status=status_filter)
    if stock_filter == "in_stock":
        queryset = queryset.filter(in_stock_q())
    elif stock_filter == "out_of_stock":
        queryset = queryset.filter(out_of_stock_q())
    elif stock_filter == "low_stock":
        queryset = queryset.filter(low_stock_q())
    elif stock_filter == "expired":
        queryset = queryset.filter(expired_q())
    elif stock_filter == "expiring":
        queryset = queryset.filter(expiring_soon_q())
    return queryset


def format_last_movement_date(value):
    if value is None:
        return ""
    if timezone.is_aware(value):
        value = timezone.localtime(value)
    return value.strftime("%Y-%m-%d %H:%M:%S")


def product_export_row(product):
    category_name = product.category.name if product.category_id else ""
    last_movement = getattr(product, "last_movement_at", None)
    return [
        csv_safe_text(product.store.store_code),
        csv_safe_text(product.store.name),
        csv_safe_text(product.product_code),
        csv_safe_text(product.sku),
        csv_safe_text(product.name),
        csv_safe_text(category_name),
        str(product.stock_quantity),
        csv_safe_text(product.get_unit_display()),
        str(product.low_stock_threshold),
        csv_safe_text(stock_status_for_product(product)),
        csv_safe_text(format_last_movement_date(last_movement)),
    ]


def build_inventory_export_queryset(base_queryset):
    return (
        base_queryset.select_related("store", "category")
        .annotate(last_movement_at=latest_movement_at_subquery())
        .order_by("store__name", "name")
    )


def render_inventory_csv_response(queryset, *, filename="inventory_export.csv"):
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(EXPORT_HEADERS)
    for product in queryset.iterator(chunk_size=500):
        writer.writerow(product_export_row(product))

    response = HttpResponse(buffer.getvalue(), content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
