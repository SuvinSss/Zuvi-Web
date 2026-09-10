from django import forms
from django.contrib import admin
from django.core.exceptions import ValidationError

from config.storage_errors import ImageAdminErrorMixin
from .services import PRICING_FIELDS, guard_product_image_cascade, mutate_product_images

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


class ProductImageAdminForm(forms.ModelForm):
    class Meta:
        model = ProductImage
        fields = "__all__"

    def _get_validation_exclusions(self):
        exclusions = super()._get_validation_exclusions()
        # Primary uniqueness is resolved under the parent lock by the service.
        exclusions.add("is_primary")
        return exclusions


def image_form_fields(form):
    names = ("image", "alt_text", "sort_order", "is_primary")
    return {name: form.cleaned_data[name] for name in names
            if name in form.cleaned_data and (not form.instance.pk or name in form.changed_data)}


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    form = ProductImageAdminForm
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

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
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

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Product)
class ProductAdmin(ImageAdminErrorMixin, admin.ModelAdmin):
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

    def get_object(self, request, object_id, from_field=None):
        obj = super().get_object(request, object_id, from_field)
        if obj is not None and request.method == "POST":
            # changeform_view owns the transaction. Lock before binding a form
            # whose instance could otherwise overwrite a concurrent reapproval.
            return Product.objects.select_for_update().get(pk=obj.pk)
        return obj

    def save_model(self, request, obj, form, change):
        if change:
            current = Product.objects.get(pk=obj.pk)
            # ModelForm.clean recalculates these read-only fields in memory.
            # Image/admin catalogue edits must not change approved pricing.
            for name in PRICING_FIELDS:
                setattr(obj, name, getattr(current, name))
        super().save_model(request, obj, form, change)

    def save_formset(self, request, form, formset, change):
        if formset.model is not ProductImage:
            return super().save_formset(request, form, formset, change)
        formset.save(commit=False)
        additions, updates, deletions = [], {}, []
        changed_forms = []
        for image_form in formset.forms:
            if not image_form.cleaned_data:
                continue
            obj = image_form.instance
            if image_form.cleaned_data.get("DELETE"):
                if obj.pk:
                    deletions.append(obj.pk)
            elif image_form.has_changed():
                fields = image_form_fields(image_form)
                if obj.pk:
                    updates[obj.pk] = fields
                else:
                    additions.append(fields)
                changed_forms.append(image_form)
        saved = mutate_product_images(mutations={form.instance.pk: {
            "add": additions, "update": updates, "delete": deletions,
        }}, changed_by=request.user, request=request)[form.instance.pk]
        # Keep Django's normal addition/change message and LogEntry machinery.
        ordered_forms = [f for f in changed_forms if f.instance.pk] + [
            f for f in changed_forms if not f.instance.pk]
        for image_form, obj in zip(ordered_forms, saved):
            image_form.instance.__dict__.update(obj.__dict__)
        formset.save_m2m()

    def delete_model(self, request, obj):
        guard_product_image_cascade([obj])
        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        guard_product_image_cascade(queryset.order_by("pk"))
        super().delete_queryset(request, queryset)


@admin.register(ProductImage)
class ProductImageAdmin(ImageAdminErrorMixin, admin.ModelAdmin):
    form = ProductImageAdminForm
    list_display = ("product", "is_primary", "sort_order", "alt_text", "created_at")
    list_filter = ("is_primary", "created_at")
    search_fields = ("product__product_code", "product__name", "alt_text")
    autocomplete_fields = ("product",)
    readonly_fields = ("created_at",)

    def get_readonly_fields(self, request, obj=None):
        return self.readonly_fields + (("product",) if obj else ())

    def save_model(self, request, obj, form, change):
        if change:
            original = ProductImage.objects.get(pk=obj.pk)
            supplied = request.POST.get("product", str(original.product_id))
            if str(original.product_id) != supplied or obj.product_id != original.product_id:
                raise ValidationError("An existing image cannot be reassigned to another product.")
        batch = {"update": {obj.pk: image_form_fields(form)}} if change else {
            "add": [image_form_fields(form)]}
        saved = mutate_product_images(mutations={obj.product_id: batch},
                                      changed_by=request.user, request=request)[obj.product_id][0]
        obj.__dict__.update(saved.__dict__)

    def delete_model(self, request, obj):
        mutate_product_images(mutations={obj.product_id: {"delete": [obj.pk]}},
                              changed_by=request.user, request=request)

    def delete_queryset(self, request, queryset):
        batches = {}
        for pk, product_id in queryset.values_list("pk", "product_id"):
            batches.setdefault(product_id, {"delete": []})["delete"].append(pk)
        mutate_product_images(mutations=batches, changed_by=request.user, request=request)


@admin.register(ProductStatusHistory)
class ProductStatusHistoryAdmin(admin.ModelAdmin):
    actions = None

    def has_delete_permission(self, request, obj=None):
        return False

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
    actions = None

    def has_delete_permission(self, request, obj=None):
        return False

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
