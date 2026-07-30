"""Inventory stock and expiry status helpers for lists and dashboards."""

from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, F, Q
from django.utils import timezone

from catalog.models import Product

EXPIRING_SOON_DAYS = 30

STOCK_STATUS_IN_STOCK = "In stock"
STOCK_STATUS_LOW_STOCK = "Low stock"
STOCK_STATUS_OUT_OF_STOCK = "Out of stock"


def inventory_today():
    """Timezone-aware local calendar date used for expiry calculations."""
    return timezone.localdate()


def out_of_stock_q():
    return Q(stock_quantity__lte=0)


def low_stock_q():
    """Positive stock at or below a positive low-stock threshold."""
    return Q(
        stock_quantity__gt=0,
        low_stock_threshold__gt=0,
        stock_quantity__lte=F("low_stock_threshold"),
    )


def in_stock_q():
    """Positive stock that is not in the low-stock band."""
    return Q(stock_quantity__gt=0) & ~low_stock_q()


def expired_q(*, today=None):
    """
    Products whose catalogue expiry_date is before today.

    This is informational only — stock is never reduced automatically when the
    date passes. Expired stock must be recorded via record_expired_stock().
    """
    if today is None:
        today = inventory_today()
    return Q(expiry_date__isnull=False, expiry_date__lt=today)


def expiring_soon_q(*, today=None, days=EXPIRING_SOON_DAYS):
    """
    Products expiring on or after today through ``today + days`` inclusive.

    Already-expired products are excluded (use expired_q for those).
    """
    if today is None:
        today = inventory_today()
    cutoff = today + timedelta(days=days)
    return Q(
        expiry_date__isnull=False,
        expiry_date__gte=today,
        expiry_date__lte=cutoff,
    )


def stock_status_for_product(product):
    """Human-readable stock band for a single Product instance."""
    qty = product.stock_quantity or Decimal("0")
    threshold = product.low_stock_threshold or Decimal("0")
    if qty <= 0:
        return STOCK_STATUS_OUT_OF_STOCK
    if threshold > 0 and qty <= threshold:
        return STOCK_STATUS_LOW_STOCK
    return STOCK_STATUS_IN_STOCK


def is_product_expired(product, *, today=None):
    if today is None:
        today = inventory_today()
    return bool(product.expiry_date and product.expiry_date < today)


def is_product_expiring_soon(product, *, today=None, days=EXPIRING_SOON_DAYS):
    if today is None:
        today = inventory_today()
    if not product.expiry_date:
        return False
    cutoff = today + timedelta(days=days)
    return today <= product.expiry_date <= cutoff


def get_inventory_dashboard_stats(*, store=None, queryset=None):
    """
    Return inventory status counts in one aggregate query.

    When ``store`` is provided, counts are limited to that store only.
    Passing ``queryset`` allows callers to apply additional permission filters.
    """
    if queryset is not None:
        qs = queryset
    else:
        qs = Product.objects.all()
    if store is not None:
        qs = qs.filter(store_id=store.pk)

    today = inventory_today()
    return qs.aggregate(
        total=Count("id"),
        in_stock=Count("id", filter=in_stock_q()),
        low_stock=Count("id", filter=low_stock_q()),
        out_of_stock=Count("id", filter=out_of_stock_q()),
        expired=Count("id", filter=expired_q(today=today)),
        expiring_soon=Count(
            "id",
            filter=expiring_soon_q(today=today, days=EXPIRING_SOON_DAYS),
        ),
    )


def get_store_inventory_dashboard_stats(store):
    """Store-portal inventory card counts, scoped to the logged-in store."""
    return get_inventory_dashboard_stats(store=store)
