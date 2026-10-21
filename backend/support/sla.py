"""Service-level targets. Hours are configurable (settings.SUPPORT_SLA_HOURS) and timezone-aware."""
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

DEFAULT_TICKET_SLA = {  # priority -> (first response hours, resolution hours)
    "URGENT": (1, 8), "HIGH": (4, 24), "NORMAL": (8, 48), "LOW": (24, 120),
}
DEFAULT_COMPLAINT_SLA = {  # severity -> (acknowledge hours, resolution hours)
    "URGENT": (2, 24), "HIGH": (4, 48), "NORMAL": (8, 96), "LOW": (24, 168),
}
DUE_SOON_FRACTION = 0.25  # "due soon" = last quarter of the allowed time


def _table(name, default):
    return getattr(settings, name, None) or default


def ticket_due(priority, start):
    first, resolve = _table("SUPPORT_TICKET_SLA_HOURS", DEFAULT_TICKET_SLA)[priority]
    return start + timedelta(hours=first), start + timedelta(hours=resolve)


def complaint_due(severity, start):
    ack, resolve = _table("SUPPORT_COMPLAINT_SLA_HOURS", DEFAULT_COMPLAINT_SLA)[severity]
    return start + timedelta(hours=ack), start + timedelta(hours=resolve)


def state(due, done_at, *, start, now=None):
    """'met' / 'missed' once done, otherwise 'ok' / 'due_soon' / 'breached'."""
    now = now or timezone.now()
    if due is None:
        return "none"
    if done_at is not None:
        return "met" if done_at <= due else "missed"
    if now > due:
        return "breached"
    window = (due - start).total_seconds()
    return "due_soon" if window > 0 and (due - now).total_seconds() <= window * DUE_SOON_FRACTION else "ok"
