from .models import AuditEvent


def _ip(request):
    if request is None:
        return None
    try:
        from accounts.audit_ip import get_client_ip

        return get_client_ip(request)
    except Exception:
        return None


def audit(actor, action, obj=None, *, summary="", request=None, object_type=None, object_id=None, **metadata):
    return AuditEvent.objects.create(
        actor=actor if getattr(actor, "pk", None) else None,
        action=action,
        object_type=object_type or (obj.__class__.__name__ if obj is not None else ""),
        object_id=str(object_id if object_id is not None else getattr(obj, "pk", "")),
        summary=summary[:255],
        metadata=metadata,
        ip_address=_ip(request),
    )
