"""Customer-facing endpoints. The customer is always resolved from the session."""

from decimal import Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from customers.decorators import portal_customer_addresses_queryset
from customers.services import (
    create_customer_delivery_address,
    deactivate_customer_address,
    set_customer_address_as_default,
    update_customer_delivery_address,
)
from geo import quotes
from geo.navigation import navigation_url  # noqa: F401  (re-exported for tests)
from orders.models import FulfillmentType, Order, PaymentMethod
from orders.services import (
    build_checkout_preview,
    clear_checkout_token,
    issue_checkout_token,
    peek_checkout_token,
    place_order,
    verify_checkout_token,
)

from .permissions import IsCustomer
from .serializers import (
    CheckoutRequestSerializer,
    CustomerAddressWriteSerializer,
    QuoteRequestSerializer,
    customer_address_dict,
)
from .throttles import QuoteThrottle


def _owned_address(request, pk, *, active=True):
    qs = portal_customer_addresses_queryset(request.user)
    if active:
        qs = qs.filter(is_active=True)
    address = qs.filter(pk=pk).first()
    if address is None:
        # Same answer for "does not exist" and "belongs to someone else".
        raise NotFound()
    return address


def _convert_validation(exc):
    if hasattr(exc, "error_dict"):
        return DjangoValidationError(exc.message_dict)
    return exc


class AddressListCreateView(APIView):
    permission_classes = [IsCustomer]

    def get(self, request):
        qs = portal_customer_addresses_queryset(request.user).filter(is_active=True)
        return Response({"addresses": [customer_address_dict(a) for a in qs]})

    def post(self, request):
        data = CustomerAddressWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        created = create_customer_delivery_address(customer=request.customer, data=data.validated_data)
        return Response(customer_address_dict(created), status=status.HTTP_201_CREATED)


class AddressDetailView(APIView):
    permission_classes = [IsCustomer]

    def get(self, request, pk):
        return Response(customer_address_dict(_owned_address(request, pk)))

    def patch(self, request, pk):
        current = _owned_address(request, pk)
        merged = {**customer_address_dict(current), **request.data}
        pin_moved = "latitude" in request.data or "longitude" in request.data
        if not pin_moved and current.address.location_confirmed_at is not None:
            merged["location_confirmed"] = True
        elif "location_confirmed" not in request.data:
            merged["location_confirmed"] = False
        data = CustomerAddressWriteSerializer(data=merged)
        data.is_valid(raise_exception=True)
        updated = update_customer_delivery_address(customer_address=current, data=data.validated_data)
        return Response(customer_address_dict(updated))

    def delete(self, request, pk):
        # Addresses are deactivated, not deleted, so past orders keep their history.
        deactivate_customer_address(customer_address=_owned_address(request, pk))
        return Response(status=status.HTTP_204_NO_CONTENT)


class AddressDefaultView(APIView):
    permission_classes = [IsCustomer]

    def post(self, request, pk):
        updated = set_customer_address_as_default(customer_address=_owned_address(request, pk))
        return Response(customer_address_dict(updated))


def quote_customer_dict(quote):
    """Customer-safe quote view: no operational cost, payout or subsidy data."""
    legs = []
    for leg in quote.legs.select_related("store").all():
        legs.append(
            {
                "store_id": leg.store_id,
                "store_name": leg.store.name,
                "items_subtotal": str(leg.items_subtotal),
                "road_distance_km": str((Decimal(leg.route_distance_meters) / 1000).quantize(Decimal("0.1"))),
                "delivery_fee_before_discount": str(leg.fee_before_discount),
                "delivery_discount": str(leg.discount),
                "delivery_fee": str(leg.fee_after_discount),
            }
        )
    return {
        "id": quote.pk,
        "address_id": quote.customer_address_id,
        "expires_at": quote.expires_at.isoformat(),
        "delivery_fee_before_discount": str(quote.delivery_fee_before_discount),
        "delivery_discount": str(quote.delivery_discount),
        "delivery_fee": str(quote.delivery_fee),
        "legs": legs,
        "distance_note": "Distance is measured along roads using Google Maps.",
    }


def cart_dict(preview):
    return {
        "is_empty": preview["is_empty"],
        "items_subtotal": str(preview["items_subtotal"]),
        "blocking_messages": preview["blocking_messages"],
        "stores": [
            {
                "store_id": g["store_id"],
                "store_name": g["store_name"],
                "items_subtotal": str(g["items_subtotal"]),
                "items": [
                    {
                        "product_name": i["product_name"],
                        "quantity": i["quantity"],
                        "unit_price": str(i["unit_price"]) if i["unit_price"] is not None else None,
                        "line_total": str(i["line_total"]) if i["line_total"] is not None else None,
                        "is_available": i["is_available"],
                        "warnings": i["warnings"],
                    }
                    for i in g["items"]
                ],
            }
            for g in preview["store_groups"]
        ],
    }


class CheckoutSummaryView(APIView):
    """Basket, saved addresses and a one-time checkout token for the current session."""

    permission_classes = [IsCustomer]

    def get(self, request):
        preview = build_checkout_preview(request.customer)
        token = peek_checkout_token(request._request, request.customer) or issue_checkout_token(
            request._request, request.customer
        )
        addresses = [customer_address_dict(a) for a in preview["delivery_addresses"]]
        return Response(
            {
                "cart": cart_dict(preview),
                "addresses": addresses,
                "checkout_token": token,
                "payment_methods": [{"value": PaymentMethod.COD, "label": PaymentMethod.COD.label}],
            }
        )


class DeliveryQuoteView(APIView):
    """Create a fresh server-side delivery quote for the basket and one saved address."""

    permission_classes = [IsCustomer]
    throttle_classes = [QuoteThrottle]

    def post(self, request):
        data = QuoteRequestSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        address = _owned_address(request, data.validated_data["address_id"])
        quote = quotes.create_quote(request.customer, address)
        return Response(quote_customer_dict(quote), status=status.HTTP_201_CREATED)


class PlaceOrderView(APIView):
    permission_classes = [IsCustomer]

    def post(self, request):
        data = CheckoutRequestSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        address = _owned_address(request, v["address_id"])
        verify_checkout_token(request._request, request.customer, v["checkout_token"])
        try:
            order = place_order(
                customer=request.customer,
                checkout_token=v["checkout_token"],
                fulfillment_type=FulfillmentType.DELIVERY,
                payment_method=PaymentMethod.COD,
                delivery_address_id=address.pk,
                customer_notes=v["customer_notes"],
                actor=request.user,
                request=request._request,
                delivery_quote_id=v["quote_id"],
            )
        except DjangoValidationError as exc:
            raise _convert_validation(exc) from exc
        clear_checkout_token(request._request)
        return Response(
            {
                "order_number": order.order_number,
                "items_subtotal": str(order.items_subtotal),
                "delivery_charge": str(order.delivery_charge),
                "delivery_discount": str(order.discount_total),
                "grand_total": str(order.grand_total),
            },
            status=status.HTTP_201_CREATED,
        )


class OrderTrackingView(APIView):
    """Order progress and map points. Never exposes rider identity or live position."""

    permission_classes = [IsCustomer]

    def get(self, request, order_number):
        order = (
            Order.objects.filter(customer=request.customer, order_number=order_number)
            .prefetch_related("store_orders__store__address", "store_orders__delivery_assignment")
            .first()
        )
        if order is None:
            raise NotFound()
        stores = []
        for so in order.store_orders.all():
            assignment = getattr(so, "delivery_assignment", None)
            stores.append(
                {
                    "store_name": so.store_name,
                    "status": so.status,
                    "status_display": so.get_status_display(),
                    "pickup": {
                        "latitude": str(so.store.address.latitude),
                        "longitude": str(so.store.address.longitude),
                    },
                    "delivery_partner_status": assignment.get_status_display() if assignment else None,
                    "delivery_fee": str(so.delivery_charge),
                }
            )
        return Response(
            {
                "order_number": order.order_number,
                "status": order.status,
                "status_display": order.get_status_display(),
                "delivery": {
                    "label": ", ".join(p for p in (order.delivery_line1, order.delivery_city) if p),
                    "latitude": str(order.delivery_latitude) if order.delivery_latitude is not None else None,
                    "longitude": str(order.delivery_longitude) if order.delivery_longitude is not None else None,
                },
                "delivery_charge": str(order.delivery_charge),
                "delivery_discount": str(order.discount_total),
                "grand_total": str(order.grand_total),
                "stores": stores,
                # No delivery time is promised: only measured road distance is available.
                "delivery_time_note": "We don't estimate delivery times yet.",
            }
        )
