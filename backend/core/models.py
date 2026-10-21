from django.conf import settings
from django.db import models


class AuditEvent(models.Model):
    """Append-only record of a sensitive action (moderation, assignment, escalation, approvals...)."""

    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    action = models.CharField(max_length=64, db_index=True)
    object_type = models.CharField(max_length=40)
    object_id = models.CharField(max_length=40)
    summary = models.CharField(max_length=255, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        indexes = [models.Index(fields=["object_type", "object_id"], name="audit_object_idx")]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValueError("Audit events are append-only.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Audit events cannot be deleted.")
