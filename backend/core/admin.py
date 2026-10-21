from django.contrib import admin

from .admin_base import ReadOnlyAdmin
from .models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(ReadOnlyAdmin):
    """Append-only business audit trail (the same events the API's audit endpoint returns)."""

    list_display = ("created_at", "action", "object_type", "object_id", "actor", "summary")
    list_display_links = ("created_at", "action")
    list_filter = ("action", "object_type", "created_at")
    search_fields = ("action", "object_id", "summary", "actor__username")
    list_select_related = ("actor",)
    date_hierarchy = "created_at"
    list_per_page = 100
