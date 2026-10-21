"""Notification generation, separated from delivery channels.

``notify`` always stores an in-app notification. Extra channels (email today)
are dispatched after the surrounding transaction commits and can never break
or roll back the business operation that triggered them. Email is only sent
when an email backend is configured (``NOTIFICATION_EMAIL_ENABLED``); nothing
claims delivery otherwise - ``email_status`` records what actually happened.
"""
import logging

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction

from .models import EmailStatus, Notification, NotificationPreference

logger = logging.getLogger(__name__)


def email_channel_enabled() -> bool:
    explicit = getattr(settings, "NOTIFICATION_EMAIL_ENABLED", None)
    if explicit is not None:
        return bool(explicit)
    return bool(getattr(settings, "EMAIL_HOST", ""))


def _send_email(notification_id: int) -> None:
    notification = Notification.objects.select_related("recipient").get(pk=notification_id)
    address = notification.recipient.email
    if not address:
        Notification.objects.filter(pk=notification_id).update(email_status=EmailStatus.SKIPPED)
        return
    try:
        send_mail(notification.title, notification.body or notification.title,
                  getattr(settings, "DEFAULT_FROM_EMAIL", None), [address], fail_silently=False)
        status, error = EmailStatus.SENT, ""
    except Exception as exc:  # delivery problems must never surface to the caller
        logger.warning("Notification email failed for %s: %s", notification_id, exc)
        status, error = EmailStatus.FAILED, str(exc)[:255]
    Notification.objects.filter(pk=notification_id).update(email_status=status, email_error=error)


def notify(user, kind, title, body="", data=None, *, email=True):
    """Create one notification for ``user`` (a no-op for ``None``)."""
    if user is None:
        return None
    wants_email = email and email_channel_enabled()
    if wants_email:
        pref = NotificationPreference.objects.filter(user=user).first()
        wants_email = pref.email_enabled if pref else True
    notification = Notification.objects.create(
        recipient=user, kind=kind, title=title[:200], body=body, data=data or {},
        email_status=EmailStatus.SKIPPED if (email and not wants_email) else EmailStatus.NOT_REQUESTED,
    )
    if wants_email:
        transaction.on_commit(lambda: _send_email(notification.pk))
    return notification


def notify_many(users, kind, title, body="", data=None, *, email=True):
    seen = set()
    created = []
    for user in users:
        if user is None or user.pk in seen:
            continue
        seen.add(user.pk)
        created.append(notify(user, kind, title, body, data, email=email))
    return created


def mark_read(user, notification_id):
    updated = Notification.objects.filter(pk=notification_id, recipient=user, is_read=False).update(is_read=True, read_at=_now())
    return updated


def mark_all_read(user):
    return Notification.objects.filter(recipient=user, is_read=False).update(is_read=True, read_at=_now())


def _now():
    from django.utils import timezone

    return timezone.now()
