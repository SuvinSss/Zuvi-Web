from django.contrib import admin

from .models import Cart, CartItem


class ReadOnlyModelAdmin(admin.ModelAdmin):
    actions = None

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        readonly = list(super().get_readonly_fields(request, obj))
        return readonly or [field.name for field in self.model._meta.fields]


class CartItemInline(admin.TabularInline):
    model = CartItem
    extra = 0
    can_delete = False
    show_change_link = False
    readonly_fields = (
        "product",
        "quantity",
        "unit_price_snapshot",
        "added_at",
        "updated_at",
    )

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Cart)
class CartAdmin(ReadOnlyModelAdmin):
    list_display = ("id", "customer", "updated_at", "created_at")
    search_fields = (
        "customer__customer_code",
        "customer__user__username",
        "customer__user__email",
    )
    readonly_fields = ("customer", "created_at", "updated_at")
    inlines = [CartItemInline]


@admin.register(CartItem)
class CartItemAdmin(ReadOnlyModelAdmin):
    list_display = ("id", "cart", "product", "quantity", "updated_at")
    search_fields = (
        "product__name",
        "product__sku",
        "product__product_code",
        "cart__customer__customer_code",
    )
    readonly_fields = (
        "cart",
        "product",
        "quantity",
        "unit_price_snapshot",
        "added_at",
        "updated_at",
    )
