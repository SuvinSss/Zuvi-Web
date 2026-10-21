"""Support tickets (everyday help) and formal complaints (tracked, escalatable disputes)."""
from django.conf import settings
from django.db import models

from core.references import new_reference
from core.storage import private_storage


def _ticket_ref():
    return new_reference("TKT")


def _complaint_ref():
    return new_reference("CMP")


class TicketCategory(models.TextChoices):
    ORDER = "ORDER", "Order"
    DELIVERY = "DELIVERY", "Delivery"
    PAYMENT = "PAYMENT", "Payment or refund"
    PRODUCT = "PRODUCT", "Product quality"
    ACCOUNT = "ACCOUNT", "Account"
    TECHNICAL = "TECHNICAL", "App or technical"
    OTHER = "OTHER", "Other"


class Priority(models.TextChoices):
    LOW = "LOW", "Low"
    NORMAL = "NORMAL", "Normal"
    HIGH = "HIGH", "High"
    URGENT = "URGENT", "Urgent"


class TicketStatus(models.TextChoices):
    OPEN = "OPEN", "Open"
    IN_PROGRESS = "IN_PROGRESS", "In progress"
    WAITING_CUSTOMER = "WAITING_CUSTOMER", "Waiting for requester"
    RESOLVED = "RESOLVED", "Resolved"
    CLOSED = "CLOSED", "Closed"


class Ticket(models.Model):
    reference = models.CharField(max_length=20, unique=True, default=_ticket_ref, editable=False)
    requester = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="support_tickets")
    category = models.CharField(max_length=12, choices=TicketCategory.choices, default=TicketCategory.OTHER)
    priority = models.CharField(max_length=8, choices=Priority.choices, default=Priority.NORMAL, db_index=True)
    status = models.CharField(max_length=18, choices=TicketStatus.choices, default=TicketStatus.OPEN, db_index=True)
    subject = models.CharField(max_length=200)
    description = models.TextField(max_length=5000)
    order = models.ForeignKey("orders.Order", null=True, blank=True, on_delete=models.PROTECT, related_name="support_tickets")
    delivery = models.ForeignKey("deliveries.Delivery", null=True, blank=True, on_delete=models.PROTECT, related_name="support_tickets")
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="assigned_tickets")
    escalated = models.BooleanField(default=False, db_index=True)
    escalated_at = models.DateTimeField(null=True, blank=True)
    first_response_due = models.DateTimeField(null=True, blank=True)
    resolution_due = models.DateTimeField(null=True, blank=True)
    first_responded_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    sla_notices = models.JSONField(default=list, blank=True)  # reminders already sent, so none repeats
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        indexes = [
            models.Index(fields=["status", "priority", "-created_at"], name="ticket_queue_idx"),
            models.Index(fields=["assigned_to", "status"], name="ticket_assignee_idx"),
            models.Index(fields=["requester", "-created_at"], name="ticket_requester_idx"),
        ]

    def __str__(self):
        return self.reference


class TicketMessage(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="messages")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    body = models.TextField(max_length=5000)
    is_internal = models.BooleanField(default=False)  # private staff note
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]


class TicketEvent(models.Model):
    """System timeline entry (status change, assignment, escalation)."""

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="events")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    kind = models.CharField(max_length=24)
    detail = models.CharField(max_length=255, blank=True)
    is_internal = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]


class TicketAttachment(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="attachments")
    message = models.ForeignKey(TicketMessage, null=True, blank=True, on_delete=models.CASCADE, related_name="attachments")
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    file = models.FileField(upload_to="support/tickets/%Y/%m/", storage=private_storage)
    original_name = models.CharField(max_length=150, blank=True)
    content_type = models.CharField(max_length=50)
    size = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)
    is_internal = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)


class AgainstType(models.TextChoices):
    STORE = "STORE", "A store"
    DELIVERY_PARTNER = "DELIVERY_PARTNER", "A delivery partner"
    PRODUCT = "PRODUCT", "A product"
    PLATFORM = "PLATFORM", "The platform"


class ComplaintCategory(models.TextChoices):
    QUALITY = "QUALITY", "Product quality or safety"
    MISSING_ITEMS = "MISSING_ITEMS", "Missing or wrong items"
    LATE = "LATE", "Late delivery"
    BEHAVIOUR = "BEHAVIOUR", "Staff or rider behaviour"
    OVERCHARGE = "OVERCHARGE", "Overcharging or billing"
    NOT_DELIVERED = "NOT_DELIVERED", "Marked delivered but not received"
    OTHER = "OTHER", "Other"


class ComplaintStatus(models.TextChoices):
    SUBMITTED = "SUBMITTED", "Submitted"
    UNDER_REVIEW = "UNDER_REVIEW", "Under review"
    INFO_REQUESTED = "INFO_REQUESTED", "More information requested"
    ESCALATED = "ESCALATED", "Escalated to supervisor"
    RESOLVED = "RESOLVED", "Resolved"
    REJECTED = "REJECTED", "Rejected"
    CLOSED = "CLOSED", "Closed"


class Complaint(models.Model):
    reference = models.CharField(max_length=20, unique=True, default=_complaint_ref, editable=False)
    complainant = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="complaints")
    against_type = models.CharField(max_length=20, choices=AgainstType.choices)
    store = models.ForeignKey("stores.Store", null=True, blank=True, on_delete=models.PROTECT, related_name="complaints")
    partner = models.ForeignKey("deliveries.DeliveryPartner", null=True, blank=True, on_delete=models.PROTECT, related_name="complaints")
    product = models.ForeignKey("catalog.Product", null=True, blank=True, on_delete=models.PROTECT, related_name="complaints")
    order = models.ForeignKey("orders.Order", null=True, blank=True, on_delete=models.PROTECT, related_name="complaints")
    category = models.CharField(max_length=16, choices=ComplaintCategory.choices, default=ComplaintCategory.OTHER)
    severity = models.CharField(max_length=8, choices=Priority.choices, default=Priority.NORMAL)
    description = models.TextField(max_length=5000)
    desired_resolution = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=16, choices=ComplaintStatus.choices, default=ComplaintStatus.SUBMITTED, db_index=True)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="assigned_complaints")
    escalated_to = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="escalated_complaints")
    escalation_reason = models.CharField(max_length=255, blank=True)
    resolution = models.TextField(blank=True)
    acknowledge_due = models.DateTimeField(null=True, blank=True)
    resolution_due = models.DateTimeField(null=True, blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    sla_notices = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        indexes = [
            models.Index(fields=["status", "severity", "-created_at"], name="complaint_queue_idx"),
            models.Index(fields=["assigned_to", "status"], name="complaint_assignee_idx"),
            models.Index(fields=["complainant", "-created_at"], name="complaint_owner_idx"),
        ]

    def __str__(self):
        return self.reference


class ComplaintEvent(models.Model):
    """Timeline of a complaint. ``is_internal`` entries are staff-only private notes."""

    class Kind(models.TextChoices):
        SUBMITTED = "SUBMITTED", "Submitted"
        STATUS = "STATUS", "Status changed"
        ASSIGNED = "ASSIGNED", "Assigned"
        COMMENT = "COMMENT", "Comment"
        INFO_REQUEST = "INFO_REQUEST", "Information requested"
        INFO_RESPONSE = "INFO_RESPONSE", "Information provided"
        ESCALATED = "ESCALATED", "Escalated"
        NOTE = "NOTE", "Private note"
        RESOLUTION = "RESOLUTION", "Resolution"
        REOPENED = "REOPENED", "Reopened"

    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name="events")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    kind = models.CharField(max_length=16, choices=Kind.choices)
    body = models.TextField(blank=True, max_length=5000)
    from_status = models.CharField(max_length=16, blank=True)
    to_status = models.CharField(max_length=16, blank=True)
    is_internal = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]
        indexes = [models.Index(fields=["complaint", "is_internal"], name="cevent_visibility_idx")]


class ComplaintAttachment(models.Model):
    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name="attachments")
    event = models.ForeignKey(ComplaintEvent, null=True, blank=True, on_delete=models.CASCADE, related_name="attachments")
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    file = models.FileField(upload_to="support/complaints/%Y/%m/", storage=private_storage)
    original_name = models.CharField(max_length=150, blank=True)
    content_type = models.CharField(max_length=50)
    size = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)
    is_internal = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
