"""
Order number generation, checkout preview, tokens, and place-order services.

Prices, availability and inventory are always recalculated on the server.
Client POST bodies may only carry fulfillment/payment selections, address or
pickup IDs, notes, and the server-issued checkout token.
"""

from __future__ import annotations

import secrets
import string
from decimal import Decimal
from itertools import groupby

from django.core.exceptions import ValidationError
from django.utils import timezone

from cart.services import (
    build_cart_item_presentation,
    get_or_create_cart_for_customer,
    portal_cart_items_queryset,
)
from catalog.public import public_products_queryset
from customers.models import Customer, CustomerAddress

from .models import (
    FulfillmentType,
    Order,
    PaymentMethod,
    PickupLocation,
    StoreOrder,
)

ORDER_NUMBER_PREFIX = "ORD"
STORE_ORDER_NUMBER_PREFIX = "SO"
NUMBER_DATE_FORMAT = "%Y%m%d"
NUMBER_TOKEN_LENGTH = 8
NUMBER_ALPHABET = string.ascii_uppercase + string.digits
ORDER_NUMBER_MAX_ATTEMPTS = 32
STORE_ORDER_NUMBER_MAX_ATTEMPTS = 32

CHECKOUT_TOKEN_SESSION_KEY = "checkout_token"
CHECKOUT_TOKEN_CUSTOMER_KEY = "checkout_token_customer_id"
CHECKOUT_TOKEN_BYTES = 32


def _candidate_number(prefix):
    date_part = timezone.localdate().strftime(NUMBER_DATE_FORMAT)
    token = "".join(
        secrets.choice(NUMBER_ALPHABET) for _ in range(NUMBER_TOKEN_LENGTH)
    )
    return f"{prefix}-{date_part}-{token}"


def generate_order_number(*, exclude_pk=None):
    for _ in range(ORDER_NUMBER_MAX_ATTEMPTS):
        number = _candidate_number(ORDER_NUMBER_PREFIX)
        queryset = Order.objects.filter(order_number=number)
        if exclude_pk is not None:
            queryset = queryset.exclude(pk=exclude_pk)
        if not queryset.exists():
            return number
    raise RuntimeError(
        "Unable to generate a unique order number after multiple attempts."
    )


def generate_store_order_number(*, exclude_pk=None):
    for _ in range(STORE_ORDER_NUMBER_MAX_ATTEMPTS):
        number = _candidate_number(STORE_ORDER_NUMBER_PREFIX)
        queryset = StoreOrder.objects.filter(store_order_number=number)
        if exclude_pk is not None:
            queryset = queryset.exclude(pk=exclude_pk)
        if not queryset.exists():
            return number
    raise RuntimeError(
        "Unable to generate a unique store order number after multiple attempts."
    )


def generate_checkout_token():
    return secrets.token_urlsafe(CHECKOUT_TOKEN_BYTES)


def issue_checkout_token(request, customer):
    """Create a one-time checkout token bound to this customer session."""
    if not isinstance(customer, Customer):
        raise ValidationError({"customer": "A customer profile is required."})
    token = generate_checkout_token()
    request.session[CHECKOUT_TOKEN_SESSION_KEY] = token
    request.session[CHECKOUT_TOKEN_CUSTOMER_KEY] = customer.pk
    request.session.modified = True
    return token


def peek_checkout_token(request, customer):
    token = request.session.get(CHECKOUT_TOKEN_SESSION_KEY)
    owner_id = request.session.get(CHECKOUT_TOKEN_CUSTOMER_KEY)
    if not token or owner_id != customer.pk:
        return None
    return token


def verify_checkout_token(request, customer, submitted_token):
    """Validate the submitted token against the customer session without consuming it."""
    if not submitted_token:
        raise ValidationError({"checkout_token": "Checkout token is required."})

    session_token = peek_checkout_token(request, customer)
    if session_token is None or not secrets.compare_digest(
        str(session_token), str(submitted_token)
    ):
        raise ValidationError(
            {"checkout_token": "Invalid or expired checkout token."}
        )
    return submitted_token


def clear_checkout_token(request):
    request.session.pop(CHECKOUT_TOKEN_SESSION_KEY, None)
    request.session.pop(CHECKOUT_TOKEN_CUSTOMER_KEY, None)
    request.session.modified = True


def consume_checkout_token(request, customer, submitted_token):
    """Validate and clear the session checkout token."""
    token = verify_checkout_token(request, customer, submitted_token)
    clear_checkout_token(request)
    return token


def active_delivery_addresses_for_customer(customer):
    return (
        CustomerAddress.objects.filter(customer=customer, is_active=True)
        .select_related("address", "customer")
        .order_by("-is_default", "-created_at")
    )


def active_pickup_locations_for_stores(store_ids):
    store_ids = [sid for sid in store_ids if sid]
    if not store_ids:
        return PickupLocation.objects.none()
    return (
        PickupLocation.objects.filter(
            store_id__in=store_ids,
            is_active=True,
            store__is_active=True,
        )
        .select_related("store", "address")
        .order_by("store__name", "name")
    )


def get_owned_active_delivery_address(*, customer, address_id):
    """Resolve an active delivery address owned by customer, or raise."""
    if not address_id:
        raise ValidationError(
            {"delivery_address_id": "Select a delivery address."}
        )
    try:
        address_id = int(address_id)
    except (TypeError, ValueError) as exc:
        raise ValidationError(
            {"delivery_address_id": "Invalid delivery address."}
        ) from exc

    address = (
        active_delivery_addresses_for_customer(customer)
        .filter(pk=address_id)
        .first()
    )
    if address is None:
        raise ValidationError(
            {
                "delivery_address_id": (
                    "Selected delivery address is not available."
                )
            }
        )
    return address


def get_valid_pickup_location(*, store_id, pickup_location_id):
    """Resolve an active PickupLocation belonging to store_id, or raise."""
    if not pickup_location_id:
        raise ValidationError(
            {"pickup_location_id": "Select a pickup location for each store."}
        )
    try:
        pickup_location_id = int(pickup_location_id)
    except (TypeError, ValueError) as exc:
        raise ValidationError(
            {"pickup_location_id": "Invalid pickup location."}
        ) from exc

    location = (
        active_pickup_locations_for_stores([store_id])
        .filter(pk=pickup_location_id)
        .first()
    )
    if location is None:
        raise ValidationError(
            {
                "pickup_location_id": (
                    "Selected pickup location is not available for this store."
                )
            }
        )
    return location


def _pickup_presentation(location):
    address = location.address
    return {
        "id": location.pk,
        "name": location.name,
        "code": location.code,
        "store_id": location.store_id,
        "store_name": location.store.name if location.store_id else "",
        "contact_phone": location.contact_phone,
        "hours": location.hours,
        "instructions": location.instructions,
        "address": address,
        "address_display": str(address) if address else "",
    }


def build_checkout_preview(customer):
    """
    Recalculate cart lines for checkout and attach fulfillment options.

    Every unit price and line total is derived from live Product.final_price.
    """
    if not isinstance(customer, Customer):
        raise ValidationError({"customer": "A customer profile is required."})

    cart = get_or_create_cart_for_customer(customer)
    items = list(
        portal_cart_items_queryset(customer)
        .select_related(
            "product",
            "product__store",
            "product__category",
            "product__brand",
        )
        .order_by(
            "product__store__name",
            "product__store_id",
            "product__name",
            "pk",
        )
    )

    available_product_ids = set(
        public_products_queryset()
        .filter(pk__in=[row.product_id for row in items])
        .values_list("pk", flat=True)
    )
    presentations = [
        build_cart_item_presentation(
            item,
            available_product_ids=available_product_ids,
        )
        for item in items
    ]
    store_groups = []
    items_subtotal = Decimal("0.00")
    has_blocking_issues = False
    blocking_messages = []

    if not presentations:
        has_blocking_issues = True
        blocking_messages.append("Your cart is empty.")

    for store_key, group in groupby(
        presentations, key=lambda row: (row["store_id"], row["store_name"])
    ):
        group_items = list(group)
        store_id, store_name = store_key
        group_subtotal = Decimal("0.00")
        for row in group_items:
            if not row["is_available"] or row["line_total"] is None:
                has_blocking_issues = True
                blocking_messages.append(
                    f"{row['product_name']} is not available to purchase."
                )
            elif row["quantity"] > row["stock_quantity"]:
                has_blocking_issues = True
                blocking_messages.append(
                    f"{row['product_name']} exceeds available stock "
                    f"({row['stock_quantity']})."
                )
            if row["line_total"] is not None:
                group_subtotal += row["line_total"]
                items_subtotal += row["line_total"]

        pickups = [
            _pickup_presentation(loc)
            for loc in active_pickup_locations_for_stores([store_id])
        ]
        store_groups.append(
            {
                "store_id": store_id,
                "store_name": store_name,
                "items": group_items,
                "items_subtotal": group_subtotal.quantize(Decimal("0.01")),
                "pickup_locations": pickups,
            }
        )

    delivery_charge = Decimal("0.00")
    discount_total = Decimal("0.00")
    grand_total = (items_subtotal + delivery_charge - discount_total).quantize(
        Decimal("0.01")
    )

    delivery_addresses = list(active_delivery_addresses_for_customer(customer))

    return {
        "cart": cart,
        "store_groups": store_groups,
        "item_count": len(presentations),
        "items_subtotal": items_subtotal.quantize(Decimal("0.01")),
        "delivery_charge": delivery_charge,
        "discount_total": discount_total,
        "grand_total": grand_total,
        "delivery_addresses": delivery_addresses,
        "has_blocking_issues": has_blocking_issues,
        "blocking_messages": blocking_messages,
        "is_empty": not presentations,
        "fulfillment_types": FulfillmentType.choices,
        "payment_methods_delivery": [
            (PaymentMethod.COD, PaymentMethod.COD.label),
        ],
        "payment_methods_pickup": [
            (PaymentMethod.PAY_AT_PICKUP, PaymentMethod.PAY_AT_PICKUP.label),
            (PaymentMethod.COD, PaymentMethod.COD.label),
        ],
        "location_eligibility_notice": (
            "Delivery eligibility will be confirmed based on your location. "
            "The 10 km service-area check is not enforced yet."
        ),
    }


def _validate_payment_for_fulfillment(fulfillment_type, payment_method):
    if fulfillment_type == FulfillmentType.DELIVERY:
        if payment_method != PaymentMethod.COD:
            raise ValidationError(
                {
                    "payment_method": (
                        "Cash on Delivery is required for delivery orders."
                    )
                }
            )
    elif fulfillment_type == FulfillmentType.FACILITY_PICKUP:
        if payment_method not in (
            PaymentMethod.PAY_AT_PICKUP,
            PaymentMethod.COD,
        ):
            raise ValidationError(
                {
                    "payment_method": (
                        "Choose Pay at Pickup or Cash on Delivery for "
                        "facility pickup."
                    )
                }
            )
    else:
        raise ValidationError(
            {"fulfillment_type": "Select a valid fulfillment method."}
        )


def _parse_pickup_selections(post_data, store_ids):
    """
    Read pickup_location_<store_id> values from POST for cart stores only.

    Ignores any store IDs that are not part of the authenticated customer's cart.
    """
    selections = {}
    for store_id in store_ids:
        key = f"pickup_location_{store_id}"
        raw = post_data.get(key)
        if raw in (None, "") and len(store_ids) == 1:
            raw = post_data.get("pickup_location_id")
        location = get_valid_pickup_location(
            store_id=store_id,
            pickup_location_id=raw,
        )
        selections[store_id] = location
    return selections


def _delivery_snapshot_fields(customer_address):
    address = customer_address.address
    return {
        "delivery_address": customer_address,
        "delivery_recipient_name": customer_address.recipient_name,
        "delivery_phone_number": customer_address.phone_number,
        "delivery_line1": address.line1,
        "delivery_line2": address.line2,
        "delivery_landmark": address.landmark,
        "delivery_city": address.city,
        "delivery_district": address.district,
        "delivery_state": address.state,
        "delivery_postal_code": address.postal_code,
        "delivery_country": address.country,
        "delivery_latitude": address.latitude,
        "delivery_longitude": address.longitude,
        "delivery_instructions": customer_address.delivery_instructions,
    }


def validate_checkout_selections(
    *,
    customer,
    fulfillment_type,
    payment_method,
    delivery_address_id=None,
    pickup_post_data=None,
    preview=None,
):
    """
    Validate fulfillment selections against the live checkout preview.

    Returns (preview, delivery_address_or_None, pickup_by_store_id).
    """
    preview = preview or build_checkout_preview(customer)
    if preview["is_empty"] or preview["has_blocking_issues"]:
        message = "; ".join(preview["blocking_messages"]) or (
            "Cart items are not available for checkout."
        )
        raise ValidationError({"cart": message})

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

    store_ids = [group["store_id"] for group in preview["store_groups"]]

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

    return preview, delivery_address, pickup_by_store


def _client_ip(request):
    if request is None:
        return None
    try:
        from accounts.audit_ip import get_client_ip

        return get_client_ip(request)
    except Exception:
        return None


def place_order(
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
    Compatibility wrapper around the dedicated checkout service.

    Implementation lives in ``orders.checkout.place_customer_order``.
    """
    from .checkout import place_customer_order

    return place_customer_order(
        customer=customer,
        checkout_token=checkout_token,
        fulfillment_type=fulfillment_type,
        payment_method=payment_method,
        delivery_address_id=delivery_address_id,
        pickup_post_data=pickup_post_data,
        customer_notes=customer_notes,
        actor=actor,
        request=request,
    )
