from django.contrib import admin

from core.admin_base import ActionAdmin, EmptyForm, ReadOnlyInline, run_confirmed

from . import services
from .models import Feedback, FeedbackReply, FeedbackStatus


class FeedbackReplyInline(ReadOnlyInline):
    model = FeedbackReply
    fields = ("created_at", "author", "is_internal", "body")
    readonly_fields = fields
    show_change_link = False


@admin.register(Feedback)
class FeedbackAdmin(ActionAdmin):
    list_display = ("reference", "kind", "subject_type", "short_message", "author", "store", "status", "assigned_to", "created_at")
    list_display_links = ("reference",)
    list_filter = ("status", "kind", "subject_type", "created_at")
    search_fields = ("reference", "message", "author__username", "author__email", "store__name")
    list_select_related = ("author", "store", "assigned_to")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    actions = ("mark_in_review", "mark_closed")
    inlines = (FeedbackReplyInline,)
    fields = ("reference", "kind", "subject_type", "author", "store", "order", "message", "status", "assigned_to", "ticket",
              "created_at", "updated_at")
    readonly_fields = fields

    @admin.display(description="Message")
    def short_message(self, obj):
        return (obj.message[:70] + "…") if len(obj.message) > 70 else obj.message

    def _set(self, request, queryset, status, verb):
        return run_confirmed(self, request, queryset, title=f"Mark feedback {verb.lower()}", verb=verb, form_class=EmptyForm,
                             apply=lambda obj, data: services.set_status(obj.pk, actor=request.user, status=status))

    @admin.action(description="Mark selected feedback as in review", permissions=["moderate"])
    def mark_in_review(self, request, queryset):
        return self._set(request, queryset, FeedbackStatus.IN_REVIEW, "Marked in review")

    @admin.action(description="Close selected feedback", permissions=["moderate"])
    def mark_closed(self, request, queryset):
        return self._set(request, queryset, FeedbackStatus.CLOSED, "Closed")
