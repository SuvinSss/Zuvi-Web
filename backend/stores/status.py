from django.core.exceptions import ValidationError

from .models import StoreStatus

# Explicit allow-list of status transitions.
ALLOWED_STATUS_TRANSITIONS = {
    StoreStatus.PENDING: frozenset({StoreStatus.ACTIVE, StoreStatus.REJECTED}),
    StoreStatus.REJECTED: frozenset({StoreStatus.PENDING}),
    StoreStatus.ACTIVE: frozenset({StoreStatus.SUSPENDED}),
    StoreStatus.SUSPENDED: frozenset({StoreStatus.ACTIVE}),
}

# Rejection and suspension always require a non-empty reason.
STATUSES_REQUIRING_REASON = frozenset(
    {
        StoreStatus.REJECTED,
        StoreStatus.SUSPENDED,
    }
)


def allowed_next_statuses(current_status):
    return ALLOWED_STATUS_TRANSITIONS.get(current_status, frozenset())


def is_transition_allowed(current_status, new_status):
    if current_status == new_status:
        return False
    return new_status in allowed_next_statuses(current_status)


def permission_for_transition(current_status, new_status):
    """
    Map a transition to the Django permission that authorizes it.

    - Approvals / reopen / reactivation → stores.approve_store
    - Suspension → stores.suspend_store
    """
    if not is_transition_allowed(current_status, new_status):
        return None
    if new_status == StoreStatus.SUSPENDED:
        return "stores.suspend_store"
    return "stores.approve_store"


def reason_required_for(new_status):
    return new_status in STATUSES_REQUIRING_REASON


def validate_status_transition(*, current_status, new_status, reason=""):
    """Raise ValidationError when the transition or reason is invalid."""
    if current_status == new_status:
        raise ValidationError("Store already has that status.")
    if not is_transition_allowed(current_status, new_status):
        raise ValidationError(
            f"Cannot change store status from {current_status} to {new_status}."
        )
    if reason_required_for(new_status) and not (reason or "").strip():
        raise ValidationError(
            "A reason is required when rejecting or suspending a store."
        )


def store_allows_portal_access(store):
    """
    Suspended or inactive stores cannot use the store portal.
    Store Users and future Product/Order rows are left intact.
    """
    return bool(store) and store.is_active and store.status == StoreStatus.ACTIVE
