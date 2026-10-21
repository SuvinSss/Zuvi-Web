"""Customer endpoints: addresses, cart, checkout and orders. The customer is always request.user's profile."""
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import generics, serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from cart import services as cart_services
from core.pagination import StandardPagination
from core.permissions import IsCustomer, get_customer
from customers import services as customer_services
from customers.models import AddressLabel, CustomerAddress
from orders import services as order_services
from orders.cancellation import cancel_customer_order
from orders.checkout import place_customer_order
from orders.models import FulfillmentType, Order, PaymentMethod, StoreOrder
from orders.portal import customer_can_cancel_order, customer_orders_queryset
from orders.services import build_checkout_preview


class DrfFromDjango:
    """Context manager translating Django ValidationError from services into DRF 400s."""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type and issubclass(exc_type, DjangoValidationError):
            detail = exc.message_dict if hasattr(exc, "error_dict") else {"detail": exc.messages}
            raise serializers.ValidationError(detail)
        return False


# ------------------------------------------------------------------ addresses

class AddressSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    label = serializers.ChoiceField(choices=AddressLabel.choices)
    recipient_name = serializers.CharField(max_length=150)
    phone_number = serializers.CharField(max_length=20)
    line1 = serializers.CharField(max_length=255)
    line2 = serializers.CharField(max_length=255, required=False, allow_blank=True)
    landmark = serializers.CharField(max_length=255, required=False, allow_blank=True)
    city = serializers.CharField(max_length=100)
    district = serializers.CharField(max_length=100, required=False, allow_blank=True)
    state = serializers.CharField(max_length=100)
    postal_code = serializers.RegexField(r"^(\d{6})?$", max_length=6, required=False, allow_blank=True,
                                         error_messages={"invalid": "PIN code must be 6 digits."})
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6, min_value=Decimal("-90"), max_value=Decimal("90"))
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6, min_value=Decimal("-180"), max_value=Decimal("180"))
    delivery_instructions = serializers.CharField(required=False, allow_blank=True, max_length=500)
    is_default = serializers.BooleanField(required=False, default=False)
    custom_label = serializers.CharField(required=False, allow_blank=True, max_length=32)
    place_id = serializers.CharField(required=False, allow_blank=True, max_length=64)
    location_source = serializers.ChoiceField(choices=["GPS", "SEARCH", "PIN", "MANUAL"], required=False, allow_blank=True)
    location_accuracy_m = serializers.IntegerField(required=False, allow_null=True, min_value=0, max_value=100000)
    location_confirmed = serializers.BooleanField(required=False, default=False, write_only=True)

    def validate(self, attrs):
        if not attrs["latitude"] and not attrs["longitude"]:
            raise serializers.ValidationError({"latitude": "Choose the location on the map."})
        return attrs


def address_payload(ca: CustomerAddress) -> dict:
    a = ca.address
    return {"id": ca.pk, "label": ca.label, "recipient_name": ca.recipient_name, "phone_number": ca.phone_number,
            "line1": a.line1, "line2": a.line2, "landmark": a.landmark, "city": a.city, "district": a.district,
            "state": a.state, "postal_code": a.postal_code, "latitude": str(a.latitude), "longitude": str(a.longitude),
            "delivery_instructions": ca.delivery_instructions, "is_default": ca.is_default,
            "custom_label": ca.custom_label, "place_id": ca.place_id, "location_source": ca.location_source,
            "location_accuracy_m": ca.location_accuracy_m, "location_confirmed": ca.location_confirmed_at is not None,
            "short_label": ca.custom_label or ca.get_label_display(),
            "summary": ", ".join(x for x in (a.line2 or a.line1, a.city, a.state) if x)}


def _own_addresses(request):
    return CustomerAddress.objects.filter(customer=get_customer(request.user), is_active=True).select_related("address")


class AddressListCreateView(APIView):
    permission_classes = [IsCustomer]

    @extend_schema(responses=AddressSerializer(many=True))
    def get(self, request):
        return Response([address_payload(a) for a in _own_addresses(request).order_by("-is_default", "-pk")])

    @extend_schema(request=AddressSerializer, responses={201: AddressSerializer})
    def post(self, request):
        data = AddressSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        with DrfFromDjango():
            created = customer_services.create_customer_delivery_address(customer=get_customer(request.user), data=data.validated_data)
        return Response(address_payload(created), status=201)


class AddressDetailView(APIView):
    permission_classes = [IsCustomer]

    def _obj(self, request, pk):
        return get_object_or_404(_own_addresses(request), pk=pk)  # another customer's id is just "not found"

    @extend_schema(responses=AddressSerializer)
    def get(self, request, pk):
        return Response(address_payload(self._obj(request, pk)))

    @extend_schema(request=AddressSerializer, responses=AddressSerializer)
    def put(self, request, pk):
        obj = self._obj(request, pk)
        data = AddressSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        with DrfFromDjango():
            customer_services.update_customer_delivery_address(customer_address=obj, data=data.validated_data)
        return Response(address_payload(self._obj(request, pk)))

    @extend_schema(responses={204: None})
    def delete(self, request, pk):
        with DrfFromDjango():
            customer_services.deactivate_customer_address(customer_address=self._obj(request, pk))
        return Response(status=204)


class AddressDefaultView(APIView):
    permission_classes = [IsCustomer]

    @extend_schema(request=None, responses=AddressSerializer)
    def post(self, request, pk):
        obj = get_object_or_404(_own_addresses(request), pk=pk)
        with DrfFromDjango():
            customer_services.set_customer_address_as_default(customer_address=obj)
        return Response(address_payload(_own_addresses(request).get(pk=pk)))


# ------------------------------------------------------------------ cart

def _line(row) -> dict:
    return {"id": row["item"].pk, "product_id": row["product"].pk, "product_code": row["product_code"], "name": row["product_name"],
            "store": {"id": row["store_id"], "name": row["store_name"]}, "quantity": str(row["quantity"]),
            "unit_price": str(row["unit_price"]) if row["unit_price"] is not None else None,
            "line_total": str(row["line_total"]) if row["line_total"] is not None else None,
            "is_available": row["is_available"], "stock_quantity": str(row["stock_quantity"]), "warnings": row["warnings"]}


def cart_payload(customer) -> dict:
    items = list(cart_services.portal_cart_items_queryset(customer).select_related("product", "product__store", "product__category", "product__brand"))
    available = cart_services._publicly_available_product_ids([i.product_id for i in items])
    lines = [_line(cart_services.build_cart_item_presentation(i, available_product_ids=available)) for i in items]
    subtotal = sum((Decimal(l["line_total"]) for l in lines if l["line_total"]), Decimal("0.00"))
    return {"items": lines, "item_count": len(lines), "subtotal": str(subtotal.quantize(Decimal("0.01"))),
            "has_issues": any(not l["is_available"] or l["warnings"] for l in lines)}


def _quantity(value) -> Decimal:
    try:
        quantity = Decimal(str(value))
    except InvalidOperation:
        raise serializers.ValidationError({"quantity": "Quantity must be a number."}) from None
    if quantity <= 0:
        raise serializers.ValidationError({"quantity": "Quantity must be greater than zero."})
    return quantity


class CartView(APIView):
    permission_classes = [IsCustomer]

    @extend_schema(responses=dict)
    def get(self, request):
        return Response(cart_payload(get_customer(request.user)))

    @extend_schema(responses={204: None})
    def delete(self, request):
        cart_services.clear_cart(customer=get_customer(request.user))
        return Response(status=204)


class CartAddSerializer(serializers.Serializer):
    product_id = serializers.IntegerField()
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3, default=Decimal("1"))


class CartItemsView(APIView):
    permission_classes = [IsCustomer]

    @extend_schema(request=CartAddSerializer, responses=dict)
    def post(self, request):
        data = CartAddSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        customer = get_customer(request.user)
        with DrfFromDjango():
            cart_services.add_product_to_cart(customer=customer, product_id=data.validated_data["product_id"], quantity=_quantity(data.validated_data["quantity"]))
        return Response(cart_payload(customer), status=201)


class CartQuantitySerializer(serializers.Serializer):
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3)


class CartItemView(APIView):
    permission_classes = [IsCustomer]

    @extend_schema(request=CartQuantitySerializer, responses=dict)
    def patch(self, request, pk):
        data = CartQuantitySerializer(data=request.data)
        data.is_valid(raise_exception=True)
        customer = get_customer(request.user)
        with DrfFromDjango():
            cart_services.update_cart_item_quantity(customer=customer, cart_item_id=pk, quantity=_quantity(data.validated_data["quantity"]))
        return Response(cart_payload(customer))

    @extend_schema(responses=dict)
    def delete(self, request, pk):
        customer = get_customer(request.user)
        with DrfFromDjango():
            cart_services.remove_cart_item(customer=customer, cart_item_id=pk)
        return Response(cart_payload(customer))


# ------------------------------------------------------------------ checkout

class CheckoutPreviewView(APIView):
    permission_classes = [IsCustomer]

    @extend_schema(responses=dict)
    def get(self, request):
        customer = get_customer(request.user)
        preview = build_checkout_preview(customer)
        groups = [{"store": {"id": g["store_id"], "name": g["store_name"]}, "items_subtotal": str(g["items_subtotal"]),
                   "items": [_line(row) for row in g["items"]],
                   "pickup_locations": [{"id": loc.pk, "name": loc.name} for loc in order_services.active_pickup_locations_for_stores([g["store_id"]])]}
                  for g in preview["store_groups"]]
        return Response({"store_groups": groups, "items_subtotal": str(preview["items_subtotal"]),
                         "delivery_charge": str(preview["delivery_charge"]), "discount_total": str(preview["discount_total"]),
                         "grand_total": str(preview["grand_total"]), "has_blocking_issues": preview["has_blocking_issues"],
                         "blocking_messages": preview["blocking_messages"],
                         "addresses": [address_payload(a) for a in preview["delivery_addresses"]],
                         "fulfillment_types": [{"value": v, "label": l} for v, l in preview["fulfillment_types"]],
                         "payment_methods": [{"value": PaymentMethod.COD, "label": PaymentMethod.COD.label}]})


class CheckoutSerializer(serializers.Serializer):
    fulfillment_type = serializers.ChoiceField(choices=FulfillmentType.choices)
    payment_method = serializers.ChoiceField(choices=PaymentMethod.choices, default=PaymentMethod.COD)
    delivery_address_id = serializers.IntegerField(required=False, allow_null=True)
    pickup_locations = serializers.DictField(child=serializers.IntegerField(), required=False,
                                             help_text="store id -> pickup location id (facility pickup only)")
    customer_notes = serializers.CharField(required=False, allow_blank=True, max_length=500)
    quote_token = serializers.UUIDField(required=False, allow_null=True,
                                        help_text="From POST /checkout/quote/. If the total changed since, the order is refused with 409.")


class CheckoutView(APIView):
    """Place the order. ``Idempotency-Key`` makes retries safe: the same key never creates a second order."""

    permission_classes = [IsCustomer]

    @extend_schema(request=CheckoutSerializer, responses={201: dict, 200: dict})
    def post(self, request):
        key = (request.headers.get("Idempotency-Key") or "").strip()
        if not key or len(key) > 64:
            raise serializers.ValidationError({"detail": "Send an Idempotency-Key header (1-64 characters) with this request."})
        data = CheckoutSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        customer = get_customer(request.user)
        from orders.models import Order as OrderModel

        existed = OrderModel.objects.filter(customer=customer, checkout_token=key).exists()
        pickup = {f"pickup_location_{sid}": loc for sid, loc in (v.get("pickup_locations") or {}).items()}
        from logistics.checkout import PriceChanged
        changed = None
        with DrfFromDjango():
            try:
                order = place_customer_order(customer=customer, checkout_token=key, fulfillment_type=v["fulfillment_type"],
                                             payment_method=v["payment_method"], delivery_address_id=v.get("delivery_address_id"),
                                             pickup_post_data=pickup, customer_notes=v.get("customer_notes", ""), actor=request.user,
                                             request=request._request, quote_token=v.get("quote_token"))
            except PriceChanged as exc:
                changed = exc
        if changed is not None:
            return Response({**changed.message_dict, "price_changed": True}, status=409)
        return Response(order_detail(order), status=200 if existed else 201)


# ------------------------------------------------------------------ orders

def order_summary(order) -> dict:
    return {"id": order.pk, "order_number": order.order_number, "status": order.status, "fulfillment_type": order.fulfillment_type,
            "payment_method": order.payment_method, "payment_status": order.payment_status, "grand_total": str(order.grand_total),
            "item_count": str(getattr(order, "item_count", None) or ""), "placed_at": order.placed_at}


def _delivery_for_customer(snapshot):
    if not snapshot:
        return None
    from logistics.services import customer_view
    return customer_view(snapshot)


def order_detail(order) -> dict:
    order = Order.objects.prefetch_related("store_orders__items", "store_orders__status_history", "status_history").get(pk=order.pk)
    data = order_summary(order)
    data.update({
        "items_subtotal": str(order.items_subtotal), "delivery_charge": str(order.delivery_charge), "discount_total": str(order.discount_total),
        "customer_notes": order.customer_notes, "delivered_at": order.delivered_at, "cancellation_reason": order.cancellation_reason,
        "can_cancel": customer_can_cancel_order(order),
        "delivery_address": {"recipient_name": order.delivery_recipient_name, "phone_number": order.delivery_phone_number,
                             "line1": order.delivery_line1, "line2": order.delivery_line2, "landmark": order.delivery_landmark,
                             "city": order.delivery_city, "state": order.delivery_state, "postal_code": order.delivery_postal_code}
        if order.fulfillment_type == FulfillmentType.DELIVERY else None,
        "timeline": [{"status": h.new_status, "at": h.created_at} for h in order.status_history.all()],
        "store_orders": [{
            "id": so.pk, "store_order_number": so.store_order_number, "store": {"id": so.store_id, "name": so.store_name}, "status": so.status,
            "store_total": str(so.store_total), "delivery_charge": str(so.delivery_charge),
            "delivery": _delivery_for_customer(so.delivery_pricing),
            "items": [{"product_name": i.product_name, "sku": i.sku, "unit": i.unit, "quantity": str(i.quantity), "unit_price": str(i.unit_price),
                       "line_total": str(i.line_total), "product_id": i.product_id} for i in so.items.all()],
            "timeline": [{"status": h.new_status, "at": h.created_at} for h in so.status_history.all()],
        } for so in order.store_orders.all()]})
    return data


class OrderListView(generics.ListAPIView):
    permission_classes = [IsCustomer]
    pagination_class = StandardPagination

    def get_serializer_class(self):
        return serializers.Serializer

    def list(self, request, *args, **kwargs):
        qs = customer_orders_queryset(get_customer(request.user))
        if request.query_params.get("status"):
            qs = qs.filter(status=request.query_params["status"])
        page = self.paginate_queryset(qs)
        return self.get_paginated_response([order_summary(o) for o in page])


class OrderDetailView(APIView):
    permission_classes = [IsCustomer]

    @extend_schema(responses=dict)
    def get(self, request, pk):
        order = get_object_or_404(Order, pk=pk, customer=get_customer(request.user))  # someone else's order is a 404
        return Response(order_detail(order))


class CancelSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500)


class OrderCancelView(APIView):
    permission_classes = [IsCustomer]

    @extend_schema(request=CancelSerializer, responses=dict)
    def post(self, request, pk):
        customer = get_customer(request.user)
        order = get_object_or_404(Order, pk=pk, customer=customer)
        data = CancelSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        with DrfFromDjango():
            order = cancel_customer_order(order=order, customer=customer, reason=data.validated_data["reason"], actor=request.user, request=request._request)
        return Response(order_detail(order))
