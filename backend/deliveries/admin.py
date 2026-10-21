from django.contrib import admin
from django.utils.html import format_html

from core.admin_base import ActionAdmin, EmptyForm, ReadOnlyAdmin, ReadOnlyInline, ReasonForm, run_confirmed

from . import services
from .models import (
    Delivery,
    DeliveryAssignment,
    DeliveryAttempt,
    DeliveryEvidence,
    DeliveryPartner,
    DeliveryStatusHistory,
    LocationPing,
    PartnerStatus,
)


class StatusHistoryInline(ReadOnlyInline):
    model = DeliveryStatusHistory
    fields = ("created_at", "old_status", "new_status", "changed_by", "note")
    readonly_fields = fields
    show_change_link = False


class AssignmentInline(ReadOnlyInline):
    model = DeliveryAssignment
    fields = ("offered_at", "partner", "attempt_number", "status", "automatic", "assigned_by", "responded_at", "reason")
    readonly_fields = fields
    show_change_link = False


class AttemptInline(ReadOnlyInline):
    model = DeliveryAttempt
    fields = ("number", "partner", "outcome", "failure_reason", "failure_note", "started_at", "ended_at")
    readonly_fields = fields
    show_change_link = False


class EvidenceInline(ReadOnlyInline):
    model = DeliveryEvidence
    fields = ("kind", "attempt_number", "captured_by", "within_tolerance", "distance_from_target_m", "recipient_name", "created_at")
    readonly_fields = fields


@admin.register(DeliveryPartner)
class DeliveryPartnerAdmin(ActionAdmin):
    list_display = ("partner", "phone", "status_badge", "vehicle_type", "vehicle_number", "is_online", "last_location_at", "created_at")
    list_display_links = ("partner",)
    list_filter = ("status", "is_online", "vehicle_type", "created_at")
    search_fields = ("user__username", "user__first_name", "user__last_name", "user__email", "user__phone_number", "vehicle_number")
    list_select_related = ("user",)
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    actions = ("approve", "reject", "suspend")
    fieldsets = (
        ("Account", {"fields": ("user", "status", "status_reason", "approved_by", "approved_at")}),
        ("Vehicle", {"fields": ("vehicle_type", "vehicle_number")}),
        ("Availability", {"fields": ("is_online", "last_location_at")}),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )  # coordinates are deliberately not shown

    def get_readonly_fields(self, request, obj=None):
        return [f for f in ("user", "status", "status_reason", "approved_by", "approved_at", "vehicle_type", "vehicle_number",
                            "is_online", "last_location_at", "created_at", "updated_at")]

    @admin.display(description="Partner", ordering="user__username")
    def partner(self, obj):
        return obj.user.get_full_name() or obj.user.get_username()

    @admin.display(description="Phone")
    def phone(self, obj):
        return obj.user.phone_number

    @admin.display(description="Status", ordering="status")
    def status_badge(self, obj):
        return format_html('<span class="zv-badge zv-{}">{}</span>', obj.status.lower(), obj.get_status_display())

    def _decide(self, request, queryset, target, verb, form_class):
        return run_confirmed(
            self, request, queryset, title=f"{verb} delivery partners", verb=verb, form_class=form_class,
            apply=lambda obj, data: services.decide_partner(obj.pk, target, actor=request.user, reason=data.get("reason", "")),
        )

    @admin.action(description="Approve selected partners", permissions=["moderate"])
    def approve(self, request, queryset):
        return self._decide(request, queryset, PartnerStatus.APPROVED, "Approved", EmptyForm)

    @admin.action(description="Reject selected pending partners…", permissions=["moderate"])
    def reject(self, request, queryset):
        return self._decide(request, queryset, PartnerStatus.REJECTED, "Rejected", ReasonForm)

    @admin.action(description="Suspend selected partners…", permissions=["moderate"])
    def suspend(self, request, queryset):
        return self._decide(request, queryset, PartnerStatus.SUSPENDED, "Suspended", ReasonForm)


@admin.register(Delivery)
class DeliveryAdmin(ActionAdmin):
    list_display = ("id", "order_number", "status", "partner", "attempt_number", "needs_attention", "created_at", "delivered_at")
    list_display_links = ("id", "order_number")
    list_filter = ("status", "needs_attention", "created_at")
    search_fields = ("store_order__store_order_number", "store_order__order__order_number", "partner__user__username",
                     "partner__vehicle_number")
    list_select_related = ("store_order", "store_order__order", "partner", "partner__user")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    actions = ("retry", "cancel")
    inlines = (AssignmentInline, AttemptInline, StatusHistoryInline, EvidenceInline)
    fieldsets = (
        ("Order", {"fields": ("store_order", "status", "partner", "attempt_number", "needs_attention", "rejection_count")}),
        ("Progress", {"fields": ("assigned_at", "picked_up_at", "delivered_at", "eta_at")}),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )  # OTP values and raw coordinates are never displayed

    def get_readonly_fields(self, request, obj=None):
        return ["store_order", "status", "partner", "attempt_number", "needs_attention", "rejection_count", "assigned_at",
                "picked_up_at", "delivered_at", "eta_at", "created_at", "updated_at"]

    @admin.display(description="Order", ordering="store_order__store_order_number")
    def order_number(self, obj):
        return obj.store_order.store_order_number or obj.store_order.order.order_number

    @admin.action(description="Approve a retry for failed deliveries", permissions=["moderate"])
    def retry(self, request, queryset):
        return run_confirmed(self, request, queryset, title="Retry deliveries", verb="Retry started", form_class=EmptyForm,
                             intro="Starts a new delivery attempt with a fresh OTP and puts the delivery back in the assignment queue.",
                             apply=lambda obj, data: services.retry_delivery(obj.pk, actor=request.user))

    @admin.action(description="Cancel selected deliveries…", permissions=["moderate"])
    def cancel(self, request, queryset):
        return run_confirmed(self, request, queryset, title="Cancel deliveries", verb="Cancelled", form_class=ReasonForm,
                             apply=lambda obj, data: services.cancel_delivery(obj.pk, actor=request.user, reason=data["reason"]))


@admin.register(DeliveryEvidence)
class DeliveryEvidenceAdmin(ReadOnlyAdmin):
    list_display = ("id", "delivery", "kind", "attempt_number", "captured_by", "within_tolerance", "distance_from_target_m", "created_at")
    list_filter = ("kind", "within_tolerance", "created_at")
    search_fields = ("delivery__store_order__store_order_number", "captured_by__username", "recipient_name")
    list_select_related = ("delivery", "delivery__store_order", "captured_by")
    date_hierarchy = "created_at"
    fields = ("delivery", "kind", "attempt_number", "captured_by", "within_tolerance", "distance_from_target_m", "accuracy_m",
              "recipient_name", "notes", "store_confirmed_by", "store_confirmed_at", "photo_count", "created_at")
    readonly_fields = fields

    @admin.display(description="Photos (private)")
    def photo_count(self, obj):
        return f"{obj.photos.count()} (view through the app, not here)"


@admin.register(DeliveryAssignment)
class DeliveryAssignmentAdmin(ReadOnlyAdmin):
    list_display = ("id", "delivery", "partner", "status", "automatic", "attempt_number", "offered_at", "responded_at")
    list_filter = ("status", "automatic", "offered_at")
    search_fields = ("delivery__store_order__store_order_number", "partner__user__username")
    list_select_related = ("delivery", "delivery__store_order", "partner", "partner__user")
    date_hierarchy = "offered_at"


@admin.register(LocationPing)
class LocationPingAdmin(ReadOnlyAdmin):
    """Raw GPS trail: view-only, bounded, and hidden unless the account holds view permission."""

    list_display = ("id", "delivery", "partner", "accuracy_m", "recorded_at")
    list_filter = ("recorded_at",)
    search_fields = ("delivery__store_order__store_order_number", "partner__user__username")
    list_select_related = ("delivery", "delivery__store_order", "partner", "partner__user")
    date_hierarchy = "recorded_at"
    list_per_page = 25
    fields = ("delivery", "partner", "accuracy_m", "device_time", "recorded_at")  # coordinates stay in the app
    readonly_fields = fields


@admin.register(DeliveryAttempt)
class DeliveryAttemptAdmin(ReadOnlyAdmin):
    list_display = ("id", "delivery", "number", "partner", "outcome", "failure_reason", "started_at", "ended_at")
    list_filter = ("outcome", "failure_reason", "started_at")
    search_fields = ("delivery__store_order__store_order_number", "partner__user__username", "failure_note")
    list_select_related = ("delivery", "delivery__store_order", "partner", "partner__user")
    date_hierarchy = "started_at"
