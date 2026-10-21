from django.contrib import admin

from .models import InventoryTransaction, PurchaseEntry, PurchaseEntryLine


class ReadOnlyModelAdmin(admin.ModelAdmin):
    """
    Inventory ledger records are append-only outside the service layer.

    Admins may view history; add/change/delete are denied so records cannot be
    silently rewritten from Django Admin.
    """

    actions = None

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        # View-only: deny change so the admin change form cannot submit edits.
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        readonly = list(super().get_readonly_fields(request, obj))
        # Belt-and-suspenders if a subclass ever re-enables change permission.
        return readonly or [field.name for field in self.model._meta.fields]


class PurchaseEntryLineInline(admin.TabularInline):
    model = PurchaseEntryLine
    extra = 0
    can_delete = False
    show_change_link = False
    readonly_fields = (
        "product",
        "quantity",
        "unit_cost",
        "line_total",
        "manufacturing_date",
        "expiry_date",
        "notes",
    )

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PurchaseEntry)
class PurchaseEntryAdmin(ReadOnlyModelAdmin):
    list_display = (
        "entry_number",
        "store",
        "supplier_name",
        "entry_date",
        "status",
        "total_cost",
        "created_by",
        "confirmed_at",
        "created_at",
    )
    list_filter = ("status", "entry_date", "store")
    search_fields = (
        "entry_number",
        "supplier_name",
        "supplier_invoice_number",
        "store__name",
        "store__store_code",
    )
    readonly_fields = (
        "store",
        "entry_number",
        "supplier_name",
        "supplier_invoice_number",
        "entry_date",
        "status",
        "total_cost",
        "notes",
        "created_by",
        "confirmed_by",
        "confirmed_at",
        "created_at",
        "updated_at",
    )
    inlines = [PurchaseEntryLineInline]


@admin.register(InventoryTransaction)
class InventoryTransactionAdmin(ReadOnlyModelAdmin):
    list_display = (
        "transaction_number",
        "store",
        "product",
        "transaction_type",
        "direction",
        "quantity",
        "previous_quantity",
        "new_quantity",
        "unit_cost",
        "created_by",
        "created_at",
    )
    list_filter = ("transaction_type", "direction", "store", "is_system_generated")
    search_fields = (
        "transaction_number",
        "reference",
        "product__name",
        "product__sku",
        "product__product_code",
        "store__name",
        "store__store_code",
    )
    readonly_fields = (
        "store",
        "product",
        "transaction_number",
        "transaction_type",
        "direction",
        "quantity",
        "previous_quantity",
        "new_quantity",
        "unit_cost",
        "reference",
        "reason",
        "notes",
        "manufacturing_date",
        "expiry_date",
        "purchase_entry",
        "purchase_entry_line",
        "created_by",
        "ip_address",
        "is_system_generated",
        "created_at",
    )
