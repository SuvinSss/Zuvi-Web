from django.conf import settings
from django.db import models


class Kind(models.TextChoices):
    ORDER_PLACED = "ORDER_PLACED", "Order confirmed"
    ORDER_NEW_FOR_STORE = "ORDER_NEW_FOR_STORE", "New order for store"
    STORE_ACCEPTED = "STORE_ACCEPTED", "Store accepted order"
    STORE_REJECTED = "STORE_REJECTED", "Store rejected order"
    ORDER_PREPARING = "ORDER_PREPARING", "Order being prepared"
    ORDER_READY = "ORDER_READY", "Order ready"
    ORDER_CANCELLED = "ORDER_CANCELLED", "Order cancelled"
    DELIVERY_OFFERED = "DELIVERY_OFFERED", "Delivery assignment offered"
    DELIVERY_ASSIGNED = "DELIVERY_ASSIGNED", "Delivery partner assigned"
    DELIVERY_REJECTED = "DELIVERY_REJECTED", "Delivery assignment rejected"
    PICKUP_CONFIRMED = "PICKUP_CONFIRMED", "Order picked up"
    IN_TRANSIT = "IN_TRANSIT", "Order on the way"
    DELIVERED = "DELIVERED", "Order delivered"
    DELIVERY_FAILED = "DELIVERY_FAILED", "Delivery attempt failed"
    REFUND = "REFUND", "Refund update"
    REVIEW_RECEIVED = "REVIEW_RECEIVED", "New review"
    REVIEW_MODERATED = "REVIEW_MODERATED", "Review moderated"
    FEEDBACK_RECEIVED = "FEEDBACK_RECEIVED", "Feedback received"
    FEEDBACK_REPLY = "FEEDBACK_REPLY", "Feedback reply"
    TICKET_CREATED = "TICKET_CREATED", "Support ticket created"
    TICKET_ASSIGNED = "TICKET_ASSIGNED", "Support ticket assigned"
    TICKET_REPLY = "TICKET_REPLY", "Support ticket reply"
    TICKET_STATUS = "TICKET_STATUS", "Support ticket update"
    COMPLAINT_SUBMITTED = "COMPLAINT_SUBMITTED", "Complaint submitted"
    COMPLAINT_ASSIGNED = "COMPLAINT_ASSIGNED", "Complaint assigned"
    COMPLAINT_ESCALATED = "COMPLAINT_ESCALATED", "Complaint escalated"
    COMPLAINT_INFO_REQUESTED = "COMPLAINT_INFO_REQUESTED", "More information requested"
    COMPLAINT_REPLY = "COMPLAINT_REPLY", "Complaint reply"
    COMPLAINT_RESOLVED = "COMPLAINT_RESOLVED", "Complaint resolved"
    COMPLAINT_STATUS = "COMPLAINT_STATUS", "Complaint update"
    SLA_OVERDUE = "SLA_OVERDUE", "Case overdue"
    ACCOUNT = "ACCOUNT", "Account update"


class EmailStatus(models.TextChoices):
    NOT_REQUESTED = "NOT_REQUESTED", "Not requested"
    SENT = "SENT", "Sent"
    FAILED = "FAILED", "Failed"
    SKIPPED = "SKIPPED", "Skipped"


class Notification(models.Model):
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    kind = models.CharField(max_length=40, choices=Kind.choices)
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    # Identifiers for deep links (order_id, ticket reference...). Never secrets.
    data = models.JSONField(default=dict, blank=True)
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    email_status = models.CharField(max_length=16, choices=EmailStatus.choices, default=EmailStatus.NOT_REQUESTED)
    email_error = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        indexes = [models.Index(fields=["recipient", "is_read", "-created_at"], name="notif_recipient_read_idx")]

    def __str__(self):
        return f"{self.kind} -> {self.recipient_id}"


class NotificationPreference(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notification_preference")
    email_enabled = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)
