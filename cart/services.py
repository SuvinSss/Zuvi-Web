"""
Cart mutations and presentation helpers for authenticated Customers.

Prices shown in the cart are previews only — checkout recalculates totals.
Ownership always comes from the authenticated Customer's profile, never from
client-supplied customer_id or cart_id values.
"""

from decimal import Decimal, InvalidOperation
from itertools import groupby

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404

from catalog.models import Product
from catalog.public import public_products_q, public_products_queryset
from customers.models import Customer

from .models import Cart, CartItem


def get_or_create_cart_for_customer(customer):
    if not isinstance(customer, Customer):
        raise ValidationError({"customer": "A customer profile is required."})
    cart, _created = Cart.objects.get_or_create(customer=customer)
    return cart


def portal_cart_items_queryset(customer):
    """CartItem queryset strictly limited to the authenticated Customer's cart."""
    return CartItem.objects.filter(cart__customer_id=customer.pk).select_related(
        "product",
        "product__store",
        "product__category",
        "product__brand",
        "cart",
        "cart__customer",
    )


def get_cart_item_count(customer):
    """Return the number of cart lines for ``customer`` (one efficient COUNT)."""
    return CartItem.objects.filter(cart__customer_id=customer.pk).count()


def get_portal_cart_item_or_404(customer, pk):
    """Return a CartItem owned by the authenticated customer, or 404."""
    return get_object_or_404(portal_cart_items_queryset(customer), pk=pk)


def _parse_positive_quantity(quantity):
    try:
        value = Decimal(str(quantity).strip())
    except (InvalidOperation, AttributeError, TypeError, ValueError) as exc:
        raise ValidationError({"quantity": "Enter a valid quantity."}) from exc
    if value <= 0:
        raise ValidationError({"quantity": "Quantity must be greater than zero."})
    return value


def _lock_public_product(*, product_id=None, product_code=None):
    """
    Lock a product row and ensure it is still publicly sellable.

    Accepts either primary key or product_code. Never trusts browser prices.
    """
    if product_id is not None:
        lookup = {"pk": product_id}
    elif product_code is not None:
        lookup = {"product_code": product_code}
    else:
        raise ValidationError({"product": "A product is required."})

    product = (
        Product.objects.select_for_update()
        .select_related("store", "category")
        .filter(**lookup)
        .first()
    )
    if product is None or not Product.objects.filter(
        public_products_q(), pk=product.pk
    ).exists():
        raise ValidationError(
            {"product": "This product is not available for purchase."}
        )
    return product


def _ensure_quantity_within_stock(product, quantity):
    if quantity > product.stock_quantity:
        raise ValidationError(
            {
                "quantity": (
                    "Only "
                    f"{product.stock_quantity} unit(s) are available in stock."
                )
            }
        )


@transaction.atomic
def add_product_to_cart(*, customer, quantity, product_id=None, product_code=None):
    """
    Add a publicly sellable product to the customer's cart.

    If the product is already in the cart, increase its quantity.
    """
    if not isinstance(customer, Customer):
        raise ValidationError({"customer": "A customer profile is required."})

    quantity = _parse_positive_quantity(quantity)
    product = _lock_public_product(product_id=product_id, product_code=product_code)

    cart = get_or_create_cart_for_customer(customer)
    item = (
        CartItem.objects.select_for_update()
        .filter(cart=cart, product=product)
        .first()
    )
    if item is None:
        _ensure_quantity_within_stock(product, quantity)
        item = CartItem(
            cart=cart,
            product=product,
            quantity=quantity,
            unit_price_snapshot=product.final_price,
        )
        item.full_clean()
        try:
            with transaction.atomic():
                item.save()
        except IntegrityError:
            # Concurrent first-add for the same product — merge into the winner.
            item = (
                CartItem.objects.select_for_update()
                .filter(cart=cart, product=product)
                .get()
            )
            new_quantity = item.quantity + quantity
            _ensure_quantity_within_stock(product, new_quantity)
            item.quantity = new_quantity
            item.unit_price_snapshot = product.final_price
            item.full_clean()
            item.save(
                update_fields=["quantity", "unit_price_snapshot", "updated_at"]
            )
    else:
        new_quantity = item.quantity + quantity
        _ensure_quantity_within_stock(product, new_quantity)
        item.quantity = new_quantity
        item.unit_price_snapshot = product.final_price
        item.full_clean()
        item.save()

    cart.save(update_fields=["updated_at"])
    return item


@transaction.atomic
def update_cart_item_quantity(*, customer, cart_item_id, quantity):
    """Set an absolute quantity for a CartItem owned by the customer."""
    if not isinstance(customer, Customer):
        raise ValidationError({"customer": "A customer profile is required."})

    quantity = _parse_positive_quantity(quantity)
    item = (
        portal_cart_items_queryset(customer)
        .select_for_update()
        .filter(pk=cart_item_id)
        .first()
    )
    if item is None:
        raise CartItem.DoesNotExist

    product = _lock_public_product(product_id=item.product_id)
    _ensure_quantity_within_stock(product, quantity)

    item.quantity = quantity
    item.unit_price_snapshot = product.final_price
    item.full_clean()
    item.save(update_fields=["quantity", "unit_price_snapshot", "updated_at"])
    item.cart.save(update_fields=["updated_at"])
    return item


@transaction.atomic
def remove_cart_item(*, customer, cart_item_id):
    if not isinstance(customer, Customer):
        raise ValidationError({"customer": "A customer profile is required."})

    item = (
        portal_cart_items_queryset(customer)
        .select_for_update()
        .filter(pk=cart_item_id)
        .first()
    )
    if item is None:
        raise CartItem.DoesNotExist

    cart = item.cart
    item.delete()
    cart.save(update_fields=["updated_at"])
    return cart


@transaction.atomic
def clear_cart(*, customer):
    if not isinstance(customer, Customer):
        raise ValidationError({"customer": "A customer profile is required."})

    cart = get_or_create_cart_for_customer(customer)
    CartItem.objects.filter(cart=cart).delete()
    cart.save(update_fields=["updated_at"])
    return cart


def _publicly_available_product_ids(product_ids):
    """Return the subset of ``product_ids`` that are still publicly sellable."""
    if not product_ids:
        return set()
    return set(
        public_products_queryset()
        .filter(pk__in=product_ids)
        .values_list("pk", flat=True)
    )


def build_cart_item_presentation(item, *, available_product_ids=None):
    """
    Build a display dict for one CartItem.

    Uses live Product.final_price for the preview line total. Snapshot is only
    used to detect price changes since the line was last updated.

    Pass ``available_product_ids`` (from one bulk lookup) to avoid N+1
    availability queries when rendering a full cart.
    """
    product = item.product
    store = product.store
    if available_product_ids is None:
        is_available = product.pk in _publicly_available_product_ids([product.pk])
    else:
        is_available = product.pk in available_product_ids
    current_price = product.final_price
    snapshot = item.unit_price_snapshot
    stock = product.stock_quantity

    warnings = []
    if not is_available:
        warnings.append(
            "This product is no longer available (inactive, unapproved, "
            "expired, out of stock, or its store is suspended)."
        )
    else:
        if snapshot is not None and current_price != snapshot:
            warnings.append(
                f"Price changed from ₹{snapshot} to ₹{current_price}."
            )
        if item.quantity > stock:
            warnings.append(
                f"Only {stock} unit(s) remain in stock "
                f"(you have {item.quantity} in your cart)."
            )

    line_total = None
    if is_available and current_price is not None and item.quantity <= stock:
        line_total = (current_price * item.quantity).quantize(Decimal("0.01"))

    return {
        "item": item,
        "product": product,
        "product_name": product.name,
        "product_code": product.product_code,
        "product_slug": product.slug,
        "sku": product.sku,
        "store": store,
        "store_id": store.pk if store else None,
        "store_name": store.name if store else "Unknown store",
        "quantity": item.quantity,
        "unit_price": current_price,
        "unit_price_snapshot": snapshot,
        "line_total": line_total,
        "is_available": is_available,
        "stock_quantity": stock,
        "warnings": warnings,
    }


def build_cart_view_context(customer):
    """
    Group cart lines by store and compute preview totals.

    Preview totals exclude unavailable lines and lines that exceed stock.
    """
    cart = Cart.objects.filter(customer=customer).first()
    if cart is None:
        return {
            "cart": None,
            "store_groups": [],
            "item_count": 0,
            "preview_subtotal": Decimal("0.00"),
            "has_warnings": False,
            "is_empty": True,
        }

    items = list(
        portal_cart_items_queryset(customer)
        .order_by("product__store__name", "product__store_id", "product__name", "pk")
    )
    available_ids = _publicly_available_product_ids(
        [item.product_id for item in items]
    )
    presentations = [
        build_cart_item_presentation(item, available_product_ids=available_ids)
        for item in items
    ]

    store_groups = []
    preview_subtotal = Decimal("0.00")
    has_warnings = False

    for store_id, group in groupby(
        presentations, key=lambda row: (row["store_id"], row["store_name"])
    ):
        group_items = list(group)
        group_subtotal = Decimal("0.00")
        for row in group_items:
            if row["warnings"]:
                has_warnings = True
            if row["line_total"] is not None:
                group_subtotal += row["line_total"]
                preview_subtotal += row["line_total"]
        store_groups.append(
            {
                "store_id": store_id[0],
                "store_name": store_id[1],
                "items": group_items,
                "preview_subtotal": group_subtotal,
            }
        )

    return {
        "cart": cart,
        "store_groups": store_groups,
        "item_count": len(presentations),
        "preview_subtotal": preview_subtotal.quantize(Decimal("0.01")),
        "has_warnings": has_warnings,
        "is_empty": not presentations,
    }
