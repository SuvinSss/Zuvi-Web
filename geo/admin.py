from django.contrib import admin

from .models import DeliveryPricingConfig, DeliveryQuote, DeliveryQuoteLeg, MapsHealthCheck


class ReadOnlyAdmin(admin.ModelAdmin):
    """Pricing versions, quotes and checks are evidence: view only in Django admin."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(DeliveryPricingConfig)
class DeliveryPricingConfigAdmin(ReadOnlyAdmin):
    list_display = ("version", "name", "is_active", "created_at", "created_by")


class LegInline(admin.TabularInline):
    model = DeliveryQuoteLeg
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(DeliveryQuote)
class DeliveryQuoteAdmin(ReadOnlyAdmin):
    list_display = ("id", "customer", "status", "delivery_fee", "expires_at", "created_at")
    list_filter = ("status",)
    inlines = [LegInline]


@admin.register(MapsHealthCheck)
class MapsHealthCheckAdmin(ReadOnlyAdmin):
    list_display = ("service", "ok", "error_code", "latency_ms", "checked_at")
    list_filter = ("service", "ok")
