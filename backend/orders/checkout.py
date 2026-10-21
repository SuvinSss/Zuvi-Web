"""
Dedicated checkout service for placing customer Orders.

All price, availability and inventory decisions happen here under
``transaction.atomic()``. Views must only collect fulfillment selections and
the server-issued checkout token — never prices or totals.
"""

from __future__ import annotations

from decimal import Decimal
from itertools import groupby

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from cart.models import CartItem
from cart.services import get_or_create_cart_for_customer
from catalog.models import Product, ProductStatus
from inventory.services import (
    deduct_order_stock,
    order_item_deduct_reference,
)
from inventory.status import is_product_expired
from stores.models import StoreStatus

from .models import (
    FulfillmentType,
    Order,
    OrderItem,
    OrderStatus,
    OrderStatusHistory,
    PaymentMethod,
    PaymentStatus,
    StoreOrder,
    StoreOrderStatus,
    StoreOrderStatusHistory,
)
from .services import (
    _client_ip,
    _delivery_snapshot_fields,
    _parse_pickup_selections,
    _validate_payment_for_fulfillment,
    get_owned_active_delivery_address,
)


def _item_review_error(product_name, detail):
    """Safe, customer-facing error naming the cart line that must be reviewed."""
    return ValidationError(
        {
            "cart": (
                f'{detail} Please review "{product_name}" in your cart before '
                "placing the order."
            )
        }
    )


def _validate_sellable_product(product, quantity):
    """
    Confirm a locked Product row is still sellable for ``quantity``.

    Uses live database field values only — never browser input.
    """
    name = product.name

    if product.status != ProductStatus.APPROVED:
        raise _item_review_error(name, "This product is not approved for sale.")
    if not product.is_active:
        raise _item_review_error(name, "This product is inactive.")

    store = product.store
    if store is None or store.status != StoreStatus.ACTIVE or not store.is_active:
        raise _item_review_error(
            name,
            "This product's store is not active.",
        )

    category = product.category
    if category is None or not category.is_active:
        raise _item_review_error(name, "This product's category is inactive.")

    if is_product_expired(product):
        raise _item_review_error(name, "This product has expired.")

    if product.final_price is None or product.final_price <= Decimal("0"):
        raise _item_review_error(name, "This product does not have a valid price.")

    if quantity is None or quantity <= 0:
        raise _item_review_error(name, "Cart quantity must be greater than zero.")

    if quantity > product.stock_quantity:
        raise _item_review_error(
            name,
            f"Only {product.stock_quantity} unit(s) remain in stock.",
        )


def _lock_cart_items(customer, *, allow_empty=False):
    """Lock the customer's cart lines in stable product order."""
    cart = get_or_create_cart_for_customer(customer)
    items = list(
        CartItem.objects.select_for_update()
        .filter(cart=cart)
        .select_related("product")
        .order_by("product_id", "pk")
    )
    if not items and not allow_empty:
        raise ValidationError(
            {"cart": "Your cart is empty. Add items before placing an order."}
        )
    return cart, items


def _lock_products_for_items(cart_items):
    """Lock Product rows (with store/category) for every cart line."""
    product_ids = sorted({item.product_id for item in cart_items})
    products = list(
        Product.objects.select_for_update()
        .select_related("store", "category")
        .filter(pk__in=product_ids)
        .order_by("pk")
    )
    by_id = {product.pk: product for product in products}
    missing = [item for item in cart_items if item.product_id not in by_id]
    if missing:
        raise _item_review_error(
            missing[0].product.name if missing[0].product_id else "Unknown item",
            "This product is no longer available.",
        )
    return by_id


def _build_validated_lines(cart_items, locked_products):
    """Reload each CartItem against locked products and recalculate prices."""
    lines = []
    for item in cart_items:
        product = locked_products[item.product_id]
        quantity = item.quantity
        _validate_sellable_product(product, quantity)
        unit_price = product.final_price
        line_total = (unit_price * quantity).quantize(Decimal("0.01"))
        lines.append(
            {
                "cart_item": item,
                "product": product,
                "store": product.store,
                "quantity": quantity,
                "unit_price": unit_price,
                "line_total": line_total,
            }
        )
    return lines


def _resolve_fulfillment(
    *,
    customer,
    fulfillment_type,
    payment_method,
    delivery_address_id,
    pickup_post_data,
    store_ids,
):
    if fulfillment_type not in FulfillmentType.values:
        raise ValidationError(
            {"fulfillment_type": "Select a valid fulfillment method."}
        )
    if payment_method not in PaymentMethod.values:
        raise ValidationError(
            {"payment_method": "Select a valid payment method."}
        )
    _validate_payment_for_fulfillment(fulfillment_type, payment_method)

    delivery_address = None
    pickup_by_store = {}
    if fulfillment_type == FulfillmentType.DELIVERY:
        delivery_address = get_owned_active_delivery_address(
            customer=customer,
            address_id=delivery_address_id,
        )
    else:
        pickup_by_store = _parse_pickup_selections(
            pickup_post_data or {},
            store_ids,
        )
    return delivery_address, pickup_by_store


def _get_existing_order_for_token(*, customer, checkout_token):
    if not checkout_token:
        raise ValidationError({"checkout_token": "Checkout token is required."})
    existing = Order.objects.filter(checkout_token=checkout_token).first()
    if existing is None:
        return None
    if existing.customer_id != customer.pk:
        raise ValidationError(
            {"checkout_token": "Invalid or expired checkout token."}
        )
    return existing


def _create_order_row(
    *,
    customer,
    checkout_token,
    fulfillment_type,
    payment_method,
    items_subtotal,
    delivery_charge,
    discount_total,
    grand_total,
    customer_notes,
    delivery_address,
):
    """
    Insert the Order row.

    Uses a savepoint so a unique-token race can be converted into an idempotent
    return of the winning Order without poisoning the outer transaction.
    """
    order_kwargs = {
        "customer": customer,
        "status": OrderStatus.PLACED,
        "fulfillment_type": fulfillment_type,
        "payment_method": payment_method,
        "payment_status": PaymentStatus.PENDING,
        "checkout_token": checkout_token,
        "items_subtotal": items_subtotal,
        "delivery_charge": delivery_charge,
        "discount_total": discount_total,
        "grand_total": grand_total,
        "customer_notes": (customer_notes or "").strip(),
    }
    if fulfillment_type == FulfillmentType.DELIVERY:
        order_kwargs.update(_delivery_snapshot_fields(delivery_address))

    order = Order(**order_kwargs)
    order.full_clean()
    try:
        with transaction.atomic():
            order.save()
    except IntegrityError:
        existing = _get_existing_order_for_token(
            customer=customer,
            checkout_token=checkout_token,
        )
        if existing is None:
            raise
        return existing, True
    return order, False


@transaction.atomic
def place_customer_order(
    *,
    customer,
    checkout_token,
    fulfillment_type,
    payment_method,
    delivery_address_id=None,
    pickup_post_data=None,
    customer_notes="",
    actor=None,
    request=None,
):
    """
    Place one multi-store Order from the authenticated Customer's cart.

    Steps (all inside one atomic block):
      1. Reject / return an already-used checkout token (idempotent retry)
      2. Lock CartItem and Product rows with ``select_for_update``
      3. Revalidate every cart line and recalculate prices from the database
      4. Create Order, StoreOrders, OrderItems, status histories
      5. Deduct stock via the Phase 5 inventory service
      6. Clear CartItems only after every prior step succeeds

    On any ValidationError the transaction rolls back: no partial order graph,
    no stock change, and the cart remains intact.
    """
    from customers.models import Customer

    if not isinstance(customer, Customer):
        raise ValidationError({"customer": "A customer profile is required."})

    existing = _get_existing_order_for_token(
        customer=customer,
        checkout_token=checkout_token,
    )
    if existing is not None:
        return existing

    # Allow empty while locking so a concurrent same-token winner that already
    # cleared the cart can be resolved idempotently instead of raising.
    cart, cart_items = _lock_cart_items(customer, allow_empty=True)
    existing = _get_existing_order_for_token(
        customer=customer,
        checkout_token=checkout_token,
    )
    if existing is not None:
        return existing
    if not cart_items:
        raise ValidationError(
            {"cart": "Your cart is empty. Add items before placing an order."}
        )

    locked_products = _lock_products_for_items(cart_items)
    lines = _build_validated_lines(cart_items, locked_products)

    store_ids = sorted({line["store"].pk for line in lines})
    delivery_address, pickup_by_store = _resolve_fulfillment(
        customer=customer,
        fulfillment_type=fulfillment_type,
        payment_method=payment_method,
        delivery_address_id=delivery_address_id,
        pickup_post_data=pickup_post_data,
        store_ids=store_ids,
    )

    items_subtotal = sum(
        (line["line_total"] for line in lines), Decimal("0.00")
    ).quantize(Decimal("0.01"))
    delivery_charge = Decimal("0.00")
    discount_total = Decimal("0.00")
    grand_total = (items_subtotal + delivery_charge - discount_total).quantize(
        Decimal("0.01")
    )

    order, already_placed = _create_order_row(
        customer=customer,
        checkout_token=checkout_token,
        fulfillment_type=fulfillment_type,
        payment_method=payment_method,
        items_subtotal=items_subtotal,
        delivery_charge=delivery_charge,
        discount_total=discount_total,
        grand_total=grand_total,
        customer_notes=customer_notes,
        delivery_address=delivery_address,
    )
    if already_placed:
        # Another concurrent request with the same token won. Do not mutate
        # stock or cart again — the winner already completed checkout.
        return order

    ip_address = _client_ip(request)
    OrderStatusHistory.objects.create(
        order=order,
        old_status="",
        new_status=OrderStatus.PLACED,
        changed_by=actor,
        reason="Order placed at checkout.",
        ip_address=ip_address,
    )

    lines_by_store = []
    for store_id, group in groupby(
        sorted(lines, key=lambda row: (row["store"].pk, row["product"].pk)),
        key=lambda row: row["store"].pk,
    ):
        lines_by_store.append((store_id, list(group)))

    for store_id, store_lines in lines_by_store:
        store = store_lines[0]["store"]
        store_subtotal = sum(
            (line["line_total"] for line in store_lines), Decimal("0.00")
        ).quantize(Decimal("0.01"))
        pickup = None
        if fulfillment_type == FulfillmentType.FACILITY_PICKUP:
            pickup = pickup_by_store[store_id]

        store_order = StoreOrder(
            order=order,
            store=store,
            status=StoreOrderStatus.PENDING,
            pickup_location=pickup,
            store_name=store.name,
            store_code=store.store_code,
            items_subtotal=store_subtotal,
            delivery_charge=Decimal("0.00"),
            store_total=store_subtotal,
        )
        store_order.full_clean()
        store_order.save()

        StoreOrderStatusHistory.objects.create(
            store_order=store_order,
            old_status="",
            new_status=StoreOrderStatus.PENDING,
            changed_by=actor,
            reason="Store order created at checkout.",
            ip_address=ip_address,
        )

        for line in store_lines:
            product = line["product"]
            order_item = OrderItem(
                store_order=store_order,
                product=product,
                product_name=product.name,
                product_code=product.product_code,
                sku=product.sku,
                unit=product.unit,
                unit_value=product.unit_value or Decimal("0"),
                unit_price=line["unit_price"],
                quantity=line["quantity"],
                line_total=line["line_total"],
            )
            order_item.full_clean()
            order_item.save()

            # Phase 5 inventory service — STOCK_OUT with immutable order-item
            # reference so a retry cannot deduct the same line twice.
            deduct_order_stock(
                product=product,
                store=store,
                quantity=line["quantity"],
                actor=actor,
                reason=f"Order {order.order_number}",
                notes=(
                    f"Stock deducted at checkout for order item {order_item.pk}."
                ),
                reference=order_item_deduct_reference(order_item.pk),
                request=request,
            )

    # Clear cart only after the full order graph and stock movements succeed.
    CartItem.objects.filter(cart=cart).delete()
    cart.save(update_fields=["updated_at"])
    return order


# Backwards-compatible alias used by views and older imports.
place_order = place_customer_order
