"""Public catalogue: only what an anonymous shopper may see. No store price, margin or commission."""
from django.db.models import Q
from drf_spectacular.utils import extend_schema
from rest_framework import generics, serializers
from rest_framework.permissions import AllowAny

from catalog.models import ProductCategory
from catalog.public import apply_public_search, public_categories_queryset, public_product_detail_queryset, public_products_queryset
from core.pagination import StandardPagination
from reviews.models import RatingAggregate, TargetType
from stores.models import Store, StoreStatus


def _url(field):
    try:
        return field.url if field else None
    except ValueError:
        return None


class PublicProductSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    product_code = serializers.CharField()
    slug = serializers.CharField()
    name = serializers.CharField()
    description = serializers.CharField()
    unit = serializers.CharField()
    unit_value = serializers.DecimalField(max_digits=12, decimal_places=3)
    price = serializers.DecimalField(source="final_price", max_digits=12, decimal_places=2)
    in_stock = serializers.SerializerMethodField()
    category = serializers.SerializerMethodField()
    brand = serializers.SerializerMethodField()
    store = serializers.SerializerMethodField()
    image = serializers.SerializerMethodField()
    thumbnail = serializers.SerializerMethodField()
    rating = serializers.SerializerMethodField()

    def get_in_stock(self, obj) -> bool:
        return obj.stock_quantity > 0

    def get_category(self, obj):
        return {"id": obj.category_id, "name": obj.category.name}

    def get_brand(self, obj):
        return obj.brand.name if obj.brand_id else None

    def get_store(self, obj):
        return {"id": obj.store_id, "name": obj.store.name}

    def _primary(self, obj):
        images = getattr(obj, "primary_image_list", None)
        if images is None:
            images = list(obj.images.all())
        primary = next((i for i in images if i.is_primary), images[0] if images else None)
        return primary

    def get_image(self, obj):
        image = self._primary(obj)
        return _url(image.display_image or image.image) if image else None

    def get_thumbnail(self, obj):
        image = self._primary(obj)
        return _url(image.thumbnail) if image else None

    def get_rating(self, obj):
        agg = self.context.get("ratings", {}).get(obj.pk)
        return {"average": float(agg.average), "count": agg.count} if agg else {"average": 0.0, "count": 0}


class PublicProductDetailSerializer(PublicProductSerializer):
    images = serializers.SerializerMethodField()

    def get_images(self, obj):
        return [{"url": _url(i.display_image or i.image), "thumbnail": _url(i.thumbnail), "alt": getattr(i, "alt_text", "") or obj.name,
                 "is_primary": i.is_primary} for i in obj.images.all()]


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductCategory
        fields = ["id", "name"]


class PublicStoreSerializer(serializers.ModelSerializer):
    city = serializers.CharField(source="address.city")
    image = serializers.SerializerMethodField()
    rating = serializers.SerializerMethodField()

    class Meta:
        model = Store
        fields = ["id", "name", "description", "city", "image", "rating"]

    def get_image(self, obj):
        return _url(obj.image)

    def get_rating(self, obj):
        agg = self.context.get("ratings", {}).get(obj.pk)
        return {"average": float(agg.average), "count": agg.count} if agg else {"average": 0.0, "count": 0}


def _ratings(target_type, ids):
    return {a.target_id: a for a in RatingAggregate.objects.filter(target_type=target_type, target_id__in=ids)}


class PublicCategoriesView(generics.ListAPIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    serializer_class = CategorySerializer
    queryset = public_categories_queryset()
    pagination_class = None


class PublicProductsView(generics.ListAPIView):
    """Every visibility rule (approved, active store, in stock, not expired...) is applied by ``public_products_queryset``."""

    authentication_classes = []
    permission_classes = [AllowAny]
    serializer_class = PublicProductSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        qs = public_products_queryset()
        p = self.request.query_params
        qs = apply_public_search(qs, p.get("q"))
        if p.get("category"):
            qs = qs.filter(category_id=p["category"]) if p["category"].isdigit() else qs.none()
        if p.get("store"):
            qs = qs.filter(store_id=p["store"]) if p["store"].isdigit() else qs.none()
        for key, lookup in (("min_price", "final_price__gte"), ("max_price", "final_price__lte")):
            if p.get(key):
                try:
                    qs = qs.filter(**{lookup: p[key]})
                except Exception:
                    qs = qs.none()
        order = {"price": "final_price", "-price": "-final_price", "name": "name", "newest": "-created_at"}.get(p.get("ordering"), "name")
        return qs.order_by(order, "pk")

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        return ctx

    def list(self, request, *args, **kwargs):
        page = self.paginate_queryset(self.filter_queryset(self.get_queryset()))
        ctx = self.get_serializer_context()
        ctx["ratings"] = _ratings(TargetType.PRODUCT, [p.pk for p in page])
        return self.get_paginated_response(PublicProductSerializer(page, many=True, context=ctx).data)


class PublicProductDetailView(generics.RetrieveAPIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    serializer_class = PublicProductDetailSerializer
    lookup_field = "product_code"

    def get_queryset(self):
        return public_product_detail_queryset()

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["ratings"] = _ratings(TargetType.PRODUCT, [self.get_object().pk])
        return ctx


class PublicStoresView(generics.ListAPIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    serializer_class = PublicStoreSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        qs = Store.objects.filter(status=StoreStatus.ACTIVE, is_active=True).select_related("address")
        if self.request.query_params.get("q"):
            qs = qs.filter(Q(name__icontains=self.request.query_params["q"]))
        return qs.order_by("name")

    def list(self, request, *args, **kwargs):
        page = self.paginate_queryset(self.get_queryset())
        ratings = _ratings(TargetType.STORE, [s.pk for s in page])
        return self.get_paginated_response(PublicStoreSerializer(page, many=True, context={"ratings": ratings}).data)


class PublicStoreDetailView(generics.RetrieveAPIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    serializer_class = PublicStoreSerializer

    def get_queryset(self):
        return Store.objects.filter(status=StoreStatus.ACTIVE, is_active=True).select_related("address")

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["ratings"] = _ratings(TargetType.STORE, [self.kwargs["pk"]])
        return ctx
