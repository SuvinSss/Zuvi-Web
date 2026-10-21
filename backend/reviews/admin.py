from django.contrib import admin
from django.utils.html import format_html

from core.admin_base import ActionAdmin, EmptyForm, ReadOnlyAdmin, ReadOnlyInline, ReasonForm, run_confirmed

from . import services
from .models import RatingAggregate, Review, ReviewReply, ReviewReport


class ReplyInline(ReadOnlyInline):
    model = ReviewReply
    fields = ("author", "body", "created_at")
    readonly_fields = fields
    show_change_link = False


class ReportInline(ReadOnlyInline):
    model = ReviewReport
    fields = ("reporter", "reason", "note", "resolved", "created_at")
    readonly_fields = fields
    show_change_link = False


@admin.register(Review)
class ReviewAdmin(ActionAdmin):
    list_display = ("id", "stars", "target_type", "target", "customer", "short_comment", "status", "report_count", "created_at")
    list_display_links = ("id", "stars")
    list_filter = ("status", "target_type", "rating", "created_at")
    search_fields = ("title", "comment", "store__name", "product__name", "customer__customer_code", "customer__user__username")
    list_select_related = ("customer", "customer__user", "store", "product", "partner", "partner__user")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    actions = ("hide", "reject", "restore")
    inlines = (ReplyInline, ReportInline)
    fieldsets = (
        ("Review", {"fields": ("customer", "store_order", "target_type", "store", "product", "partner", "rating", "title", "comment")}),
        ("Moderation", {"fields": ("status", "report_count", "moderation_reason", "moderated_by", "moderated_at")}),
        ("Timestamps", {"fields": ("created_at", "edited_at", "updated_at")}),
    )

    def get_readonly_fields(self, request, obj=None):
        return [f for fs in self.fieldsets for f in fs[1]["fields"]]

    @admin.display(description="Rating", ordering="rating")
    def stars(self, obj):
        return format_html('<span class="zv-stars" aria-label="{} out of 5">{}</span>', obj.rating, "★" * obj.rating + "☆" * (5 - obj.rating))

    @admin.display(description="About")
    def target(self, obj):
        return obj.store or obj.product or obj.partner

    @admin.display(description="Comment")
    def short_comment(self, obj):
        return (obj.comment[:60] + "…") if len(obj.comment) > 60 else obj.comment

    def _moderate(self, request, queryset, action, verb, form_class):
        return run_confirmed(self, request, queryset, title=f"{verb} reviews", verb=verb, form_class=form_class,
                             apply=lambda obj, data: services.moderate_review(obj, action=action, actor=request.user,
                                                                              reason=data.get("reason", ""), request=request))

    @admin.action(description="Hide selected reviews…", permissions=["moderate"])
    def hide(self, request, queryset):
        return self._moderate(request, queryset, "hide", "Hidden", ReasonForm)

    @admin.action(description="Reject selected reviews…", permissions=["moderate"])
    def reject(self, request, queryset):
        return self._moderate(request, queryset, "reject", "Rejected", ReasonForm)

    @admin.action(description="Restore selected reviews", permissions=["moderate"])
    def restore(self, request, queryset):
        return self._moderate(request, queryset, "restore", "Restored", EmptyForm)


@admin.register(ReviewReport)
class ReviewReportAdmin(ReadOnlyAdmin):
    list_display = ("id", "review", "reporter", "reason", "resolved", "created_at")
    list_filter = ("resolved", "reason", "created_at")
    search_fields = ("note", "reporter__username", "review__title")
    list_select_related = ("review", "reporter")
    date_hierarchy = "created_at"


@admin.register(RatingAggregate)
class RatingAggregateAdmin(ReadOnlyAdmin):
    """Derived from reviews by the service layer; shown for checking only."""

    list_display = ("target_type", "target_id", "count", "average", "updated_at")
    list_filter = ("target_type",)
    search_fields = ("target_id",)
