from django.contrib import admin

from core.admin_base import ReadOnlyAdmin

from .models import Notification, NotificationPreference


@admin.register(Notification)
class NotificationAdmin(ReadOnlyAdmin):
    """Delivery record of what each user was told. Message body and payload are not shown."""

    list_display = ("id", "recipient", "kind", "title", "is_read", "email_status", "created_at")
    list_filter = ("kind", "is_read", "email_status", "created_at")
    search_fields = ("title", "recipient__username", "recipient__email")
    list_select_related = ("recipient",)
    date_hierarchy = "created_at"
    fields = ("recipient", "kind", "title", "is_read", "read_at", "email_status", "email_error", "created_at")
    readonly_fields = fields


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(ReadOnlyAdmin):
    list_display = ("user", "email_enabled", "updated_at")
    list_filter = ("email_enabled",)
    search_fields = ("user__username", "user__email")
    list_select_related = ("user",)
