from django.contrib import admin

from .models import (
    Order,
    OrderItem,
    OrderStatusHistory,
    PickupLocation,
    StoreOrder,
    StoreOrderStatusHistory,
)


class ReadOnlyModelAdmin(admin.ModelAdmin):
    """
    Orders are service-managed. Admin is for inspection only — no add/change/delete.
    """

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


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    can_delete = False
    show_change_link = False
    # Customer-facing snapshot only — no store_price / margin fields exist on the model.
    readonly_fields = (
        "product",
        "product_name",
        "product_code",
        "sku",
        "unit",
        "unit_value",
        "unit_price",
        "quantity",
        "line_total",
        "stock_restored",
        "stock_restored_at",
        "is_cancelled",
        "cancelled_at",
        "is_rejected",
        "rejected_at",
        "created_at",
    )

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class StoreOrderInline(admin.TabularInline):
    model = StoreOrder
    extra = 0
    can_delete = False
    show_change_link = True
    readonly_fields = (
        "store",
        "store_order_number",
        "status",
        "pickup_location",
        "store_name",
        "store_code",
        "items_subtotal",
        "delivery_charge",
        "store_total",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class OrderStatusHistoryInline(admin.TabularInline):
    model = OrderStatusHistory
    extra = 0
    can_delete = False
    readonly_fields = (
        "old_status",
        "new_status",
        "changed_by",
        "reason",
        "ip_address",
        "created_at",
    )

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PickupLocation)
class PickupLocationAdmin(ReadOnlyModelAdmin):
    list_display = (
        "name",
        "code",
        "store",
        "is_active",
        "contact_phone",
        "updated_at",
    )
    list_filter = ("is_active", "store")
    search_fields = ("name", "code", "store__name", "store__store_code")
    readonly_fields = (
        "store",
        "name",
        "code",
        "address",
        "contact_phone",
        "hours",
        "instructions",
        "is_active",
        "created_at",
        "updated_at",
    )


@admin.register(Order)
class OrderAdmin(ReadOnlyModelAdmin):
    list_display = (
        "order_number",
        "customer",
        "status",
        "fulfillment_type",
        "payment_method",
        "payment_status",
        "grand_total",
        "placed_at",
    )
    list_filter = ("status", "fulfillment_type", "payment_method", "payment_status")
    search_fields = (
        "order_number",
        "checkout_token",
        "customer__customer_code",
        "customer__user__username",
        "delivery_recipient_name",
        "delivery_phone_number",
    )
    readonly_fields = (
        "order_number",
        "customer",
        "status",
        "fulfillment_type",
        "payment_method",
        "payment_status",
        "checkout_token",
        "delivery_address",
        "delivery_recipient_name",
        "delivery_phone_number",
        "delivery_line1",
        "delivery_line2",
        "delivery_landmark",
        "delivery_city",
        "delivery_district",
        "delivery_state",
        "delivery_postal_code",
        "delivery_country",
        "delivery_latitude",
        "delivery_longitude",
        "delivery_instructions",
        "items_subtotal",
        "delivery_charge",
        "discount_total",
        "grand_total",
        "customer_notes",
        "cancellation_reason",
        "cancelled_at",
        "cancelled_by",
        "placed_at",
        "created_at",
        "updated_at",
    )
    inlines = [StoreOrderInline, OrderStatusHistoryInline]


@admin.register(StoreOrder)
class StoreOrderAdmin(ReadOnlyModelAdmin):
    list_display = (
        "store_order_number",
        "order",
        "store",
        "status",
        "store_total",
        "created_at",
    )
    list_filter = ("status", "store")
    search_fields = (
        "store_order_number",
        "order__order_number",
        "store_name",
        "store_code",
        "store__store_code",
    )
    readonly_fields = (
        "order",
        "store",
        "store_order_number",
        "status",
        "pickup_location",
        "store_name",
        "store_code",
        "items_subtotal",
        "delivery_charge",
        "store_total",
        "created_at",
        "updated_at",
    )
    inlines = [OrderItemInline]


@admin.register(OrderItem)
class OrderItemAdmin(ReadOnlyModelAdmin):
    list_display = (
        "id",
        "store_order",
        "product_code",
        "product_name",
        "unit_price",
        "quantity",
        "line_total",
    )
    search_fields = (
        "product_name",
        "product_code",
        "sku",
        "store_order__store_order_number",
        "store_order__order__order_number",
    )
    readonly_fields = (
        "store_order",
        "product",
        "product_name",
        "product_code",
        "sku",
        "unit",
        "unit_value",
        "unit_price",
        "quantity",
        "line_total",
        "stock_restored",
        "stock_restored_at",
        "is_cancelled",
        "cancelled_at",
        "is_rejected",
        "rejected_at",
        "created_at",
    )


@admin.register(OrderStatusHistory)
class OrderStatusHistoryAdmin(ReadOnlyModelAdmin):
    list_display = ("order", "old_status", "new_status", "changed_by", "created_at")
    list_filter = ("new_status",)
    search_fields = ("order__order_number", "reason")
    readonly_fields = (
        "order",
        "old_status",
        "new_status",
        "changed_by",
        "reason",
        "ip_address",
        "created_at",
    )


@admin.register(StoreOrderStatusHistory)
class StoreOrderStatusHistoryAdmin(ReadOnlyModelAdmin):
    list_display = (
        "store_order",
        "old_status",
        "new_status",
        "changed_by",
        "created_at",
    )
    list_filter = ("new_status",)
    search_fields = ("store_order__store_order_number", "reason")
    readonly_fields = (
        "store_order",
        "old_status",
        "new_status",
        "changed_by",
        "reason",
        "ip_address",
        "created_at",
    )
