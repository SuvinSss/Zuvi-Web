from django.contrib import admin

from .models import Address


@admin.register(Address)
class AddressAdmin(admin.ModelAdmin):
    list_display = (
        "line1",
        "city",
        "district",
        "state",
        "postal_code",
        "country",
        "latitude",
        "longitude",
        "updated_at",
    )
    list_filter = ("country", "state", "district", "city")
    search_fields = (
        "line1",
        "line2",
        "landmark",
        "city",
        "district",
        "state",
        "postal_code",
        "country",
    )
    ordering = ("country", "state", "city", "line1")
    readonly_fields = ("created_at", "updated_at")
