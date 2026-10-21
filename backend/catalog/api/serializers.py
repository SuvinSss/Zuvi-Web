from decimal import Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from catalog.models import Brand, Product, ProductCategory, ProductImage, ProductStatus, ProductUnit, Tag
from stores.models import Store


def _url(field):
    try:
        return field.url if field else None
    except Exception:  # storage unavailable: never break a list because of one image
        return None


class ProductImageSerializer(serializers.ModelSerializer):
    thumbnail_url = serializers.SerializerMethodField()
    display_url = serializers.SerializerMethodField()
    original_url = serializers.SerializerMethodField()

    class Meta:
        model = ProductImage
        fields = ("id", "alt_text", "sort_order", "is_primary", "thumbnail_url", "display_url",
                  "original_url", "width", "height", "file_size")

    def get_thumbnail_url(self, obj):
        # Legacy rows pre-date thumbnails; run `backfill_product_thumbnails` to replace this fallback.
        return _url(obj.thumbnail) or _url(obj.display_image) or _url(obj.image)

    def get_display_url(self, obj):
        return _url(obj.display_image) or _url(obj.image)

    def get_original_url(self, obj):
        return _url(obj.image)


def card_image(product):
    """Primary image for grids, or the fallback descriptor the UI renders offline.

    ``fallback`` is only a hint (category + brand); the UI owns bundled SVG
    placeholders, so a product with no photo never shows a broken image.
    """
    images = list(product.images.all())  # prefetched by the viewset
    chosen = next((i for i in images if i.is_primary), images[0] if images else None)
    if chosen is not None and chosen.image:
        data = ProductImageSerializer(chosen).data
        return {"source": "uploaded", "alt_text": chosen.alt_text or product.name,
                "thumbnail_url": data["thumbnail_url"], "display_url": data["display_url"],
                "width": chosen.width, "height": chosen.height}
    return {"source": "fallback", "alt_text": product.name, "thumbnail_url": None, "display_url": None,
            "fallback": {"category": product.category.name if product.category_id else "",
                         "category_slug": product.category.slug if product.category_id else "",
                         "brand": product.brand.name if product.brand_id else ""}}


class ProductListSerializer(serializers.ModelSerializer):
    store = serializers.SerializerMethodField()
    category = serializers.SerializerMethodField()
    brand = serializers.SerializerMethodField()
    image = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = ("id", "product_code", "name", "sku", "slug", "store", "category", "brand", "status", "is_active",
                  "unit", "unit_value", "store_price", "selling_price", "final_price", "stock_quantity",
                  "image", "generated_fields", "updated_at")

    def get_store(self, obj):
        return {"id": obj.store_id, "name": obj.store.name, "store_code": obj.store.store_code}

    def get_category(self, obj):
        return {"id": obj.category_id, "name": obj.category.name}

    def get_brand(self, obj):
        return {"id": obj.brand_id, "name": obj.brand.name} if obj.brand_id else None

    def get_image(self, obj):
        return card_image(obj)


class ProductDetailSerializer(ProductListSerializer):
    tags = serializers.SerializerMethodField()
    images = ProductImageSerializer(many=True, read_only=True)

    class Meta(ProductListSerializer.Meta):
        fields = ProductListSerializer.Meta.fields + (
            "description", "tags", "low_stock_threshold", "manufacturing_date", "expiry_date", "is_featured",
            "profit_margin_type", "profit_margin", "discount_type", "discount_value", "rejection_reason",
            "images", "created_at",
        )

    def get_tags(self, obj):
        return [{"id": t.pk, "name": t.name} for t in obj.tags.all()]


class ProductWriteSerializer(serializers.Serializer):
    """Catalogue fields only. Pricing margin, status and stock have their own workflows."""

    store = serializers.PrimaryKeyRelatedField(queryset=Store.objects.all(), required=False)
    name = serializers.CharField(max_length=200)
    description = serializers.CharField(allow_blank=True, required=False)
    sku = serializers.CharField(max_length=64)
    category = serializers.PrimaryKeyRelatedField(queryset=ProductCategory.objects.filter(is_active=True))
    brand = serializers.PrimaryKeyRelatedField(queryset=Brand.objects.filter(is_active=True), allow_null=True, required=False)
    tags = serializers.PrimaryKeyRelatedField(queryset=Tag.objects.filter(is_active=True), many=True, required=False)
    unit = serializers.ChoiceField(choices=ProductUnit.choices, required=False)
    unit_value = serializers.DecimalField(max_digits=12, decimal_places=3, min_value=Decimal("0"), required=False)
    low_stock_threshold = serializers.DecimalField(max_digits=12, decimal_places=3, min_value=Decimal("0"), required=False)
    manufacturing_date = serializers.DateField(allow_null=True, required=False)
    expiry_date = serializers.DateField(allow_null=True, required=False)
    store_price = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0"))
    is_active = serializers.BooleanField(required=False)
    is_featured = serializers.BooleanField(required=False)
    save_as_draft = serializers.BooleanField(required=False, write_only=True)

    def validate(self, attrs):
        if self.instance is None and "store" not in attrs:
            raise serializers.ValidationError({"store": "This field is required."})
        if self.instance is not None and "store" in attrs and attrs["store"].pk != self.instance.store_id:
            raise serializers.ValidationError({"store": "A product's store cannot be changed."})
        return attrs


def to_drf_error(exc: DjangoValidationError) -> serializers.ValidationError:
    if hasattr(exc, "error_dict"):
        return serializers.ValidationError({k: [m for e in v for m in e.messages] for k, v in exc.error_dict.items()})
    return serializers.ValidationError({"non_field_errors": exc.messages})


class ImagePreviewUploadSerializer(serializers.Serializer):
    image = serializers.ImageField()  # shape check only; the pipeline does the real validation
    alt_text = serializers.CharField(max_length=200, allow_blank=True, required=False)
    is_primary = serializers.BooleanField(required=False)
