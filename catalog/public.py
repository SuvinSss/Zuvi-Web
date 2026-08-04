"""Public catalogue queryset and presentation helpers.

Visibility is enforced only here (and in views that consume these helpers).
Templates must never be the sole gate for what customers can see.
"""

from decimal import Decimal, InvalidOperation

from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404

from inventory.status import (
    expired_q,
    inventory_today,
    stock_status_for_product,
)
from stores.models import StoreStatus

from .models import Product, ProductCategory, ProductImage, ProductStatus
from .pricing import DiscountType

PUBLIC_PAGE_SIZE = 12

# Fields / labels that must never appear in public HTML for a product.
SENSITIVE_PRODUCT_ATTRS = (
    "store_price",
    "profit_margin",
    "profit_margin_type",
    "commission_percentage",
)


def public_products_q(*, today=None):
    """Q object for products that may appear on the public shop."""
    if today is None:
        today = inventory_today()
    return (
        Q(status=ProductStatus.APPROVED)
        & Q(is_active=True)
        & Q(final_price__gt=Decimal("0"))
        & Q(store__status=StoreStatus.ACTIVE)
        & Q(store__is_active=True)
        & Q(category__is_active=True)
        & Q(stock_quantity__gt=Decimal("0"))
        & ~expired_q(today=today)
    )


def public_products_queryset(*, today=None):
    """
    Base queryset for the public catalogue.

    Applies every visibility rule in the database layer. Callers may further
    filter/search/sort but must not widen this set.
    """
    primary_images = Prefetch(
        "images",
        queryset=ProductImage.objects.filter(is_primary=True),
        to_attr="primary_image_list",
    )
    return (
        Product.objects.filter(public_products_q(today=today))
        .select_related("store", "category", "brand")
        .prefetch_related("tags", primary_images)
        .distinct()
    )


def public_product_detail_queryset(*, today=None):
    """Detail queryset with all images ordered for the gallery."""
    images = Prefetch(
        "images",
        queryset=ProductImage.objects.order_by("-is_primary", "sort_order", "pk"),
    )
    return (
        Product.objects.filter(public_products_q(today=today))
        .select_related("store", "category", "brand")
        .prefetch_related("tags", images)
    )


def get_public_product_by_slug(slug, *, today=None):
    """
    Resolve a publicly visible product by slug.

    Slugs are unique per store; if more than one public product shares a slug,
    raise Http404 rather than returning an ambiguous match.
    """
    queryset = public_product_detail_queryset(today=today).filter(slug=slug)
    return get_object_or_404(queryset)


def public_categories_queryset():
    return ProductCategory.objects.filter(is_active=True).order_by("name")


def apply_public_search(queryset, query):
    query = (query or "").strip()
    if not query:
        return queryset
    return queryset.filter(
        Q(name__icontains=query)
        | Q(category__name__icontains=query)
        | Q(brand__name__icontains=query)
        | Q(tags__name__icontains=query)
        | Q(store__name__icontains=query)
    ).distinct()


def apply_public_filters(
    queryset,
    *,
    category_slug="",
    brand_slug="",
    min_price=None,
    max_price=None,
):
    category_slug = (category_slug or "").strip()
    brand_slug = (brand_slug or "").strip()
    if category_slug:
        queryset = queryset.filter(category__slug=category_slug, category__is_active=True)
    if brand_slug:
        queryset = queryset.filter(brand__slug=brand_slug, brand__is_active=True)

    min_price = _parse_price(min_price)
    max_price = _parse_price(max_price)
    if min_price is not None:
        queryset = queryset.filter(final_price__gte=min_price)
    if max_price is not None:
        queryset = queryset.filter(final_price__lte=max_price)
    return queryset


def apply_public_sort(queryset, sort):
    sort = (sort or "newest").strip().lower()
    mapping = {
        "name": ("name", "pk"),
        "name_desc": ("-name", "pk"),
        "price": ("final_price", "pk"),
        "price_desc": ("-final_price", "pk"),
        "newest": ("-created_at", "pk"),
    }
    return queryset.order_by(*mapping.get(sort, mapping["newest"]))


def _parse_price(value):
    if value is None or value == "":
        return None
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, TypeError, ValueError):
        return None
    if amount < 0:
        return None
    return amount


def discount_display_for_product(product):
    """
    Customer-facing discount summary.

    Uses selling_price (pre-discount) vs final_price only — never store_price
    or margin fields.
    """
    if not product.discount_type:
        return None
    if product.selling_price is None or product.final_price is None:
        return None
    if product.final_price >= product.selling_price:
        return None
    if product.discount_type == DiscountType.PERCENTAGE:
        value = product.discount_value or Decimal("0")
        label = format(value.normalize(), "f")
        if "." in label:
            label = label.rstrip("0").rstrip(".")
        return f"{label}% off"
    if product.discount_type == DiscountType.FIXED:
        value = product.discount_value or Decimal("0")
        label = format(value.normalize(), "f")
        if "." in label:
            label = label.rstrip("0").rstrip(".")
        return f"₹{label} off"
    return None


def unit_label_for_product(product):
    unit_value = product.unit_value
    unit = product.unit or ""
    if unit_value is None:
        return unit
    # Drop trailing zeros for cleaner labels (1.000 → 1, 0.500 → 0.5).
    normalized = format(unit_value.normalize(), "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return f"{normalized} {unit}".strip()


def primary_image_for_product(product):
    images = getattr(product, "primary_image_list", None)
    if images:
        return images[0]
    # Detail queryset prefetches all images; prefer primary.
    for image in product.images.all():
        if image.is_primary:
            return image
    return product.images.first() if product.pk else None


def public_product_card(product):
    """Safe dict for list/card templates — no internal pricing fields."""
    primary = primary_image_for_product(product)
    discount = discount_display_for_product(product)
    compare_at = None
    if discount and product.selling_price is not None:
        compare_at = product.selling_price
    return {
        "id": product.pk,
        "slug": product.slug,
        "product_code": product.product_code,
        "name": product.name,
        "brand_name": product.brand.name if product.brand_id else "",
        "category_name": product.category.name if product.category_id else "",
        "category_slug": product.category.slug if product.category_id else "",
        "store_name": product.store.name if product.store_id else "",
        "unit_label": unit_label_for_product(product),
        "final_price": product.final_price,
        "compare_at_price": compare_at,
        "discount_label": discount,
        "stock_label": stock_status_for_product(product),
        "primary_image_url": primary.image.url if primary and primary.image else "",
        "primary_image_alt": (primary.alt_text if primary else "") or product.name,
        "is_featured": product.is_featured,
    }


def public_product_detail_context(product):
    """Safe context for the product detail page."""
    card = public_product_card(product)
    images = []
    for image in product.images.all():
        images.append(
            {
                "url": image.image.url if image.image else "",
                "alt": image.alt_text or product.name,
                "is_primary": image.is_primary,
            }
        )
    tags = [tag.name for tag in product.tags.all()]
    return {
        **card,
        "description": product.description,
        "tags": tags,
        "images": images,
        "product_code": product.product_code,
    }
