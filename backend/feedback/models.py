from django.conf import settings
from django.db import models

from core.references import new_reference


def _ref():
    return new_reference("FDB")


class FeedbackKind(models.TextChoices):
    SUGGESTION = "SUGGESTION", "Suggestion"
    PRAISE = "PRAISE", "Praise"
    ISSUE = "ISSUE", "Problem"
    QUESTION = "QUESTION", "Question"


class FeedbackSubject(models.TextChoices):
    PLATFORM = "PLATFORM", "The platform"
    APP = "APP", "The app"
    STORE = "STORE", "A store"
    DELIVERY = "DELIVERY", "Delivery service"


class FeedbackStatus(models.TextChoices):
    NEW = "NEW", "New"
    IN_REVIEW = "IN_REVIEW", "In review"
    REPLIED = "REPLIED", "Replied"
    ESCALATED = "ESCALATED", "Escalated to support"
    CLOSED = "CLOSED", "Closed"


class Feedback(models.Model):
    reference = models.CharField(max_length=20, unique=True, default=_ref, editable=False)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="feedback")
    kind = models.CharField(max_length=12, choices=FeedbackKind.choices)
    subject_type = models.CharField(max_length=10, choices=FeedbackSubject.choices, default=FeedbackSubject.PLATFORM)
    store = models.ForeignKey("stores.Store", null=True, blank=True, on_delete=models.PROTECT, related_name="feedback")
    order = models.ForeignKey("orders.Order", null=True, blank=True, on_delete=models.PROTECT, related_name="feedback")
    message = models.TextField(max_length=3000)
    status = models.CharField(max_length=10, choices=FeedbackStatus.choices, default=FeedbackStatus.NEW, db_index=True)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    ticket = models.OneToOneField("support.Ticket", null=True, blank=True, on_delete=models.SET_NULL, related_name="source_feedback")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        verbose_name_plural = "feedback"
        indexes = [models.Index(fields=["status", "-created_at"], name="feedback_queue_idx"),
                   models.Index(fields=["store", "-created_at"], name="feedback_store_idx")]


class FeedbackReply(models.Model):
    feedback = models.ForeignKey(Feedback, on_delete=models.CASCADE, related_name="replies")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    body = models.TextField(max_length=3000)
    is_internal = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]
