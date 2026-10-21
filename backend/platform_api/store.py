"""Store-owner / store-staff endpoints. The store is always resolved from the caller's own membership."""
from decimal import Decimal, InvalidOperation

from django.db.models import Count, F, Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import generics, serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser

from catalog.api.serializers import StoreProductDetailSerializer, ProductImageSerializer, ProductWriteSerializer, to_drf_error
from catalog.models import Product, ProductStatus
from catalog.services import add_product_image, create_product, record_product_status_change, update_product
from core.pagination import StandardPagination
from core.permissions import IsStoreOrderManager, IsStoreUser, get_store_membership
from inventory import services as inventory
from orders.models import FulfillmentType, StoreOrder, StoreOrderStatus
from orders.store_status import available_store_order_actions, transition_store_order
from reviews.services import aggregate_for
from reviews.models import TargetType


def _store(request):
    return get_store_membership(request.user).store


def store_order_payload(so, *, detail=False) -> dict:
    order = so.order
    data = {"id": so.pk, "store_order_number": so.store_order_number, "order_number": order.order_number, "status": so.status,
            "fulfillment_type": order.fulfillment_type, "payment_method": order.payment_method, "store_total": str(so.store_total),
            "created_at": so.created_at, "actions": available_store_order_actions(so),
            # Stores prepare the order; they do not get the customer's phone number or home address.
            "recipient_first_name": (order.delivery_recipient_name or order.customer.user.first_name or "Customer").split(" ")[0]}
    if detail:
        data["customer_notes"] = order.customer_notes
        data["items"] = [{"id": i.pk, "product_id": i.product_id, "product_name": i.product_name, "sku": i.sku, "unit": i.unit,
                          "quantity": str(i.quantity), "unit_price": str(i.unit_price), "line_total": str(i.line_total)} for i in so.items.all()]
        data["timeline"] = [{"status": h.new_status, "at": h.created_at, "reason": h.reason} for h in so.status_history.all()]
        delivery = getattr(so, "delivery", None)
        data["delivery"] = ({"id": delivery.pk, "status": delivery.status, "partner_name": delivery.partner.user.first_name if delivery.partner_id else None}
                            if delivery else None)
    return data


class StoreMeView(APIView):
    permission_classes = [IsStoreUser]

    @extend_schema(responses=dict)
    def get(self, request):
        membership = get_store_membership(request.user)
        store = membership.store
        orders = StoreOrder.objects.filter(store=store)
        by_status = dict(orders.values_list("status").annotate(n=Count("pk")))
        low = Product.objects.filter(store=store, is_active=True, stock_quantity__lte=F("low_stock_threshold")).count()
        return Response({"store": {"id": store.pk, "name": store.name, "code": store.store_code, "status": store.status},
                         "membership": {"can_manage_orders": membership.can_manage_orders, "can_manage_inventory": membership.can_manage_inventory,
                                        "is_primary": membership.is_primary},
                         "orders_by_status": by_status, "low_stock_products": low, "rating": aggregate_for(TargetType.STORE, store.pk)})


class StoreMetaView(APIView):
    """Reference data for the store's product form (the admin meta endpoint is management-only)."""

    permission_classes = [IsStoreUser]

    @extend_schema(responses=dict)
    def get(self, request):
        from catalog.models import Brand, ProductCategory, ProductUnit, Tag
        from catalog.validators import MAX_IMAGES_PER_PRODUCT

        membership = get_store_membership(request.user)
        return Response({
            "categories": [{"id": c.pk, "name": str(c), "slug": c.slug}
                           for c in ProductCategory.objects.filter(is_active=True).select_related("parent__parent")],
            "brands": list(Brand.objects.filter(is_active=True).values("id", "name")),
            "tags": list(Tag.objects.filter(is_active=True).values("id", "name")),
            "units": [{"value": v, "label": l} for v, l in ProductUnit.choices],
            "max_images": MAX_IMAGES_PER_PRODUCT,
            "can": {"manage_inventory": membership.can_manage_inventory, "manage_orders": membership.can_manage_orders},
        })


class StoreOrdersView(generics.ListAPIView):
    permission_classes = [IsStoreUser]
    pagination_class = StandardPagination
    serializer_class = serializers.Serializer

    def list(self, request, *args, **kwargs):
        qs = StoreOrder.objects.filter(store=_store(request)).select_related("order__customer__user").order_by("-created_at")
        p = request.query_params
        if p.get("status"):
            qs = qs.filter(status=p["status"])
        if p.get("q"):
            qs = qs.filter(Q(store_order_number__icontains=p["q"]) | Q(order__order_number__icontains=p["q"]))
        page = self.paginate_queryset(qs)
        return self.get_paginated_response([store_order_payload(so) for so in page])


def _own_store_order(request, pk):
    return get_object_or_404(StoreOrder.objects.select_related("order__customer__user", "store").prefetch_related("items", "status_history"),
                             pk=pk, store=_store(request))  # another store's order is a 404


class StoreOrderDetailView(APIView):
    permission_classes = [IsStoreUser]

    @extend_schema(responses=dict)
    def get(self, request, pk):
        return Response(store_order_payload(_own_store_order(request, pk), detail=True))


class ActionSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=["accept", "processing", "ready", "reject"])
    reason = serializers.CharField(required=False, allow_blank=True, max_length=500)


class StoreOrderActionView(APIView):
    permission_classes = [IsStoreOrderManager]

    @extend_schema(request=ActionSerializer, responses=dict)
    def post(self, request, pk):
        store_order = _own_store_order(request, pk)
        data = ActionSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        transition_store_order(store_order=store_order, store=_store(request), action=data.validated_data["action"],
                               actor=request.user, reason=data.validated_data.get("reason", ""), request=request._request)
        return Response(store_order_payload(_own_store_order(request, pk), detail=True))


class StoreProductsView(generics.ListCreateAPIView):
    permission_classes = [IsStoreUser]
    pagination_class = StandardPagination
    serializer_class = serializers.Serializer
    parser_classes = [JSONParser]

    @extend_schema(request=ProductWriteSerializer, responses={201: StoreProductDetailSerializer})
    def create(self, request, *args, **kwargs):
        """New products always belong to the caller's own store and wait for admin approval."""
        membership = get_store_membership(request.user)
        if not membership.can_manage_inventory:
            raise PermissionDenied("You do not have permission to manage products for this store.")
        data = ProductWriteSerializer(data={**request.data, "store": membership.store_id})
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        values.pop("store")
        tags = values.pop("tags", [])
        draft = values.pop("save_as_draft", False)
        values.pop("is_featured", None)  # featuring is a management privilege
        if values.get("brand") is None:
            values.pop("brand", None)
        try:
            product = create_product(store=membership.store, product_data=values, created_by=request.user, tag_ids=[t.pk for t in tags],
                                     initial_status=ProductStatus.DRAFT if draft else ProductStatus.PENDING, request=request._request)
        except DjangoValidationError as exc:
            raise to_drf_error(exc) from exc
        return Response(StoreProductDetailSerializer(product).data, status=201)

    def list(self, request, *args, **kwargs):
        qs = Product.objects.filter(store=_store(request)).select_related("category").order_by("name")
        p = request.query_params
        if p.get("q"):
            qs = qs.filter(Q(name__icontains=p["q"]) | Q(sku__icontains=p["q"]) | Q(product_code__icontains=p["q"]))
        if p.get("low_stock") in {"1", "true"}:
            qs = qs.filter(stock_quantity__lte=F("low_stock_threshold"))
        if p.get("status"):
            qs = qs.filter(status=p["status"])
        page = self.paginate_queryset(qs)
        return self.get_paginated_response([
            {"id": x.pk, "product_code": x.product_code, "sku": x.sku, "name": x.name, "category": x.category.name, "status": x.status,
             "is_active": x.is_active, "unit": x.unit, "stock_quantity": str(x.stock_quantity), "low_stock_threshold": str(x.low_stock_threshold),
             "store_price": str(x.store_price), "final_price": str(x.final_price), "expiry_date": x.expiry_date} for x in page])


MOVEMENTS = {
    "STOCK_IN": inventory.record_manual_stock_in, "STOCK_OUT": inventory.record_manual_stock_out,
    "ADJUST_IN": inventory.record_adjustment_in, "ADJUST_OUT": inventory.record_adjustment_out,
    "DAMAGED": inventory.record_damaged_stock, "EXPIRED": inventory.record_expired_stock,
}


class StockSerializer(serializers.Serializer):
    movement = serializers.ChoiceField(choices=list(MOVEMENTS))
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3, min_value=Decimal("0.001"))
    reason = serializers.CharField(max_length=255)
    notes = serializers.CharField(required=False, allow_blank=True, max_length=500)


class StoreStockView(APIView):
    """Stock changes always go through the inventory service (never a client-supplied stock_quantity)."""

    permission_classes = [IsStoreUser]

    @extend_schema(request=StockSerializer, responses=dict)
    def post(self, request, pk):
        membership = get_store_membership(request.user)
        if not membership.can_manage_inventory:
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("You do not have permission to manage inventory for this store.")
        product = get_object_or_404(Product, pk=pk, store=membership.store)
        data = StockSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        MOVEMENTS[v["movement"]](product=product, store=membership.store, quantity=v["quantity"], actor=request.user,
                                 reason=v["reason"], notes=v.get("notes", ""), request=request._request)
        product.refresh_from_db()
        return Response({"id": product.pk, "stock_quantity": str(product.stock_quantity)})


def _own_product(request, pk):
    return get_object_or_404(Product.objects.select_related("store", "category", "brand").prefetch_related("tags", "images"),
                             pk=pk, store=_store(request))


class StoreProductDetailView(APIView):
    permission_classes = [IsStoreUser]
    parser_classes = [JSONParser]

    @extend_schema(responses=StoreProductDetailSerializer)
    def get(self, request, pk):
        return Response(StoreProductDetailSerializer(_own_product(request, pk)).data)

    @extend_schema(request=ProductWriteSerializer, responses=StoreProductDetailSerializer)
    def patch(self, request, pk):
        membership = get_store_membership(request.user)
        if not membership.can_manage_inventory:
            raise PermissionDenied("You do not have permission to manage products for this store.")
        product = _own_product(request, pk)
        payload = {k: v for k, v in request.data.items() if k not in {"store", "is_featured", "status", "stock_quantity"}}
        data = ProductWriteSerializer(product, data=payload, partial=True)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        values.pop("save_as_draft", None)
        tags = values.pop("tags", None)
        try:
            update_product(product=product, product_data=values, updated_by=request.user,
                           tag_ids=None if tags is None else [t.pk for t in tags], request=request._request)
        except DjangoValidationError as exc:
            raise to_drf_error(exc) from exc
        return Response(StoreProductDetailSerializer(_own_product(request, pk)).data)


class StoreProductSubmitView(APIView):
    """Send a draft, rejected or needs-information product (back) for review."""

    permission_classes = [IsStoreUser]

    def post(self, request, pk):
        membership = get_store_membership(request.user)
        if not membership.can_manage_inventory:
            raise PermissionDenied("You do not have permission to manage products for this store.")
        product = _own_product(request, pk)
        if product.status not in (ProductStatus.DRAFT, ProductStatus.REJECTED, ProductStatus.NEEDS_INFO):
            return Response({"detail": "Only draft, rejected or needs-information products can be submitted."}, status=400)
        try:
            record_product_status_change(product=product, new_status=ProductStatus.PENDING, changed_by=request.user,
                                         reason="Submitted by store", request=request._request, actor_is_store_user=True)
        except DjangoValidationError as exc:
            raise to_drf_error(exc) from exc
        return Response(StoreProductDetailSerializer(_own_product(request, pk)).data)


class StoreProductImagesView(APIView):
    """Store photos use the same image pipeline as every other upload path."""

    permission_classes = [IsStoreUser]
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(request={"multipart/form-data": {"type": "object", "properties": {"image": {"type": "string", "format": "binary"}}}},
                   responses={201: ProductImageSerializer})
    def post(self, request, pk):
        membership = get_store_membership(request.user)
        if not membership.can_manage_inventory:
            raise PermissionDenied("You do not have permission to manage products for this store.")
        product = _own_product(request, pk)
        upload = request.FILES.get("image")
        if upload is None:
            return Response({"image": ["Choose an image file."]}, status=400)
        try:
            image = add_product_image(product=product, image=upload, alt_text=(request.data.get("alt_text") or "")[:200],
                                      is_primary=str(request.data.get("is_primary", "")).lower() in {"1", "true", "on", "yes"},
                                      changed_by=request.user, request=request._request)
        except DjangoValidationError as exc:
            raise to_drf_error(exc) from exc
        return Response(ProductImageSerializer(image).data, status=201)
