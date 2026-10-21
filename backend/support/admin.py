from django import forms
from django.contrib import admin
from django.utils.html import format_html

from accounts.models import Role, User
from core.admin_base import ActionAdmin, ReadOnlyAdmin, ReadOnlyInline, ReasonForm, run_confirmed

from . import services
from .models import (
    Complaint,
    ComplaintAttachment,
    ComplaintEvent,
    Ticket,
    TicketAttachment,
    TicketMessage,
)


class AssigneeForm(forms.Form):
    assignee = forms.ModelChoiceField(
        queryset=User.objects.filter(is_active=True, role__in=[Role.SUPPORT_AGENT, Role.SUPPORT_SUPERVISOR]).order_by("username"),
        label="Assign to support staff",
    )


class MessageInline(ReadOnlyInline):
    """Customer-visible replies and private staff notes, clearly separated by the Internal column."""

    model = TicketMessage
    fields = ("created_at", "author", "is_internal", "body")
    readonly_fields = fields
    show_change_link = False


class AttachmentMetaInline(ReadOnlyInline):
    """Attachments live in private storage: names and sizes only, files are opened through the app."""

    fields = ("original_name", "content_type", "size", "is_internal", "uploaded_by", "created_at")
    readonly_fields = fields
    show_change_link = False


class TicketAttachmentInline(AttachmentMetaInline):
    model = TicketAttachment


class ComplaintAttachmentInline(AttachmentMetaInline):
    model = ComplaintAttachment


class ComplaintEventInline(ReadOnlyInline):
    model = ComplaintEvent
    fields = ("created_at", "actor", "kind", "is_internal", "body", "from_status", "to_status")
    readonly_fields = fields
    show_change_link = False


def _overdue(due, done_at):
    from django.utils import timezone

    return bool(due and not done_at and due < timezone.now())


@admin.register(Ticket)
class TicketAdmin(ActionAdmin):
    list_display = ("reference", "subject", "requester", "category", "priority_badge", "status", "assigned_to", "order", "escalated", "sla", "created_at")
    list_display_links = ("reference", "subject")
    list_filter = ("status", "priority", "category", "escalated", "created_at")
    search_fields = ("reference", "subject", "description", "requester__username", "requester__email", "order__order_number")
    list_select_related = ("requester", "assigned_to", "order")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    actions = ("assign", "escalate")
    inlines = (MessageInline, TicketAttachmentInline)
    fieldsets = (
        ("Ticket", {"fields": ("reference", "subject", "description", "category", "priority", "status", "escalated")}),
        ("People and links", {"fields": ("requester", "assigned_to", "order", "delivery")}),
        ("Service levels", {"fields": ("first_response_due", "first_responded_at", "resolution_due", "resolved_at", "closed_at")}),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )

    def get_readonly_fields(self, request, obj=None):
        return [f for fs in self.fieldsets for f in fs[1]["fields"]]

    @admin.display(description="Priority", ordering="priority")
    def priority_badge(self, obj):
        return format_html('<span class="zv-badge zv-p-{}">{}</span>', obj.priority.lower(), obj.get_priority_display())

    @admin.display(description="SLA")
    def sla(self, obj):
        if _overdue(obj.first_response_due, obj.first_responded_at):
            return "First reply overdue"
        if _overdue(obj.resolution_due, obj.resolved_at or obj.closed_at):
            return "Resolution overdue"
        return "—"

    @admin.action(description="Assign selected tickets to a support agent…", permissions=["moderate"])
    def assign(self, request, queryset):
        return run_confirmed(self, request, queryset, title="Assign tickets", verb="Assigned", form_class=AssigneeForm,
                             apply=lambda obj, data: services.assign_ticket(obj.pk, actor=request.user, assignee=data["assignee"]))

    @admin.action(description="Escalate selected tickets…", permissions=["moderate"])
    def escalate(self, request, queryset):
        return run_confirmed(self, request, queryset, title="Escalate tickets", verb="Escalated", form_class=ReasonForm,
                             apply=lambda obj, data: services.escalate_ticket(obj.pk, actor=request.user, reason=data["reason"]))


@admin.register(Complaint)
class ComplaintAdmin(ActionAdmin):
    list_display = ("reference", "complainant", "against_type", "category", "severity", "status", "assigned_to", "order", "created_at")
    list_display_links = ("reference",)
    list_filter = ("status", "severity", "against_type", "category", "created_at")
    search_fields = ("reference", "description", "complainant__username", "complainant__email", "order__order_number", "store__name")
    list_select_related = ("complainant", "assigned_to", "order")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    actions = ("assign",)
    inlines = (ComplaintEventInline, ComplaintAttachmentInline)
    fieldsets = (
        ("Complaint", {"fields": ("reference", "category", "severity", "status", "description", "desired_resolution", "resolution")}),
        ("About", {"fields": ("complainant", "against_type", "store", "partner", "product", "order")}),
        ("Handling", {"fields": ("assigned_to", "escalated_to", "escalation_reason")}),
        ("Service levels", {"fields": ("acknowledge_due", "acknowledged_at", "resolution_due", "resolved_at", "closed_at")}),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )

    def get_readonly_fields(self, request, obj=None):
        return [f for fs in self.fieldsets for f in fs[1]["fields"]]

    @admin.action(description="Assign selected complaints to a support agent…", permissions=["moderate"])
    def assign(self, request, queryset):
        return run_confirmed(self, request, queryset, title="Assign complaints", verb="Assigned", form_class=AssigneeForm,
                             apply=lambda obj, data: services.assign_complaint(obj.pk, actor=request.user, assignee=data["assignee"]))


@admin.register(TicketMessage)
class TicketMessageAdmin(ReadOnlyAdmin):
    list_display = ("id", "ticket", "author", "is_internal", "created_at")
    list_filter = ("is_internal", "created_at")
    search_fields = ("ticket__reference", "author__username", "body")
    list_select_related = ("ticket", "author")
    date_hierarchy = "created_at"
