from django.contrib import admin

from .models import (
    Brand,
    Product,
    ProductCategory,
    ProductImage,
    ProductPriceHistory,
    ProductStatusHistory,
    Tag,
)


@admin.register(ProductCategory)
class ProductCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "parent", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("name", "slug", "description")
    autocomplete_fields = ("parent",)
    readonly_fields = ("slug", "created_at", "updated_at")
    ordering = ("name",)


@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("name", "slug", "description")
    readonly_fields = ("slug", "created_at", "updated_at")
    ordering = ("name",)


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("name", "slug")
    readonly_fields = ("slug", "created_at", "updated_at")
    ordering = ("name",)


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 0
    readonly_fields = ("created_at",)


class ProductStatusHistoryInline(admin.TabularInline):
    model = ProductStatusHistory
    extra = 0
    can_delete = False
    autocomplete_fields = ("changed_by",)
    readonly_fields = (
        "old_status",
        "new_status",
        "changed_by",
        "reason",
        "ip_address",
        "created_at",
    )
    fields = readonly_fields

    def has_add_permission(self, request, obj=None):
        return False


class ProductPriceHistoryInline(admin.TabularInline):
    model = ProductPriceHistory
    extra = 0
    can_delete = False
    autocomplete_fields = ("changed_by",)
    readonly_fields = (
        "store_price",
        "profit_margin_type",
        "profit_margin",
        "selling_price",
        "discount_type",
        "discount_value",
        "final_price",
        "changed_by",
        "reason",
        "ip_address",
        "created_at",
    )
    fields = readonly_fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "product_code",
        "sku",
        "slug",
        "store",
        "status",
        "unit",
        "stock_quantity",
        "store_price",
        "selling_price",
        "final_price",
        "category",
        "brand",
        "is_active",
        "is_featured",
        "created_at",
    )
    list_filter = (
        "status",
        "is_active",
        "is_featured",
        "unit",
        "category",
        "brand",
        "profit_margin_type",
        "discount_type",
        "created_at",
    )
    search_fields = (
        "name",
        "product_code",
        "sku",
        "slug",
        "store__name",
        "store__store_code",
        "description",
    )
    autocomplete_fields = (
        "store",
        "category",
        "brand",
        "created_by",
        "updated_by",
        "approved_by",
    )
    filter_horizontal = ("tags",)
    # Workflow, computed prices, and stock balance must go through services.
    readonly_fields = (
        "product_code",
        "status",
        "stock_quantity",
        "store_price",
        "profit_margin_type",
        "profit_margin",
        "discount_type",
        "discount_value",
        "selling_price",
        "final_price",
        "approved_by",
        "approved_at",
        "rejection_reason",
        "created_at",
        "updated_at",
    )
    inlines = (
        ProductImageInline,
        ProductStatusHistoryInline,
        ProductPriceHistoryInline,
    )
    ordering = ("-created_at",)
    date_hierarchy = "created_at"


@admin.register(ProductImage)
class ProductImageAdmin(admin.ModelAdmin):
    list_display = ("product", "is_primary", "sort_order", "alt_text", "created_at")
    list_filter = ("is_primary", "created_at")
    search_fields = ("product__product_code", "product__name", "alt_text")
    autocomplete_fields = ("product",)
    readonly_fields = ("created_at",)


@admin.register(ProductStatusHistory)
class ProductStatusHistoryAdmin(admin.ModelAdmin):
    list_display = (
        "product",
        "old_status",
        "new_status",
        "changed_by",
        "created_at",
    )
    list_filter = ("old_status", "new_status", "created_at")
    search_fields = ("product__product_code", "changed_by__username", "reason")
    autocomplete_fields = ("product", "changed_by")
    readonly_fields = (
        "product",
        "old_status",
        "new_status",
        "changed_by",
        "reason",
        "ip_address",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(ProductPriceHistory)
class ProductPriceHistoryAdmin(admin.ModelAdmin):
    list_display = (
        "product",
        "store_price",
        "profit_margin_type",
        "selling_price",
        "discount_type",
        "final_price",
        "changed_by",
        "created_at",
    )
    list_filter = ("profit_margin_type", "discount_type", "created_at")
    search_fields = ("product__product_code", "changed_by__username", "reason")
    autocomplete_fields = ("product", "changed_by")
    readonly_fields = (
        "product",
        "store_price",
        "profit_margin_type",
        "profit_margin",
        "selling_price",
        "discount_type",
        "discount_value",
        "final_price",
        "changed_by",
        "reason",
        "ip_address",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
