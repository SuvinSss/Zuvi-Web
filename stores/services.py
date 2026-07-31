import secrets
import string

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Q

from accounts.audit_ip import get_client_ip
from accounts.models import AdminAuditLog, Role
from locations.models import Address

from .models import Store, StoreStatus, StoreStatusHistory, StoreUser

User = get_user_model()

STORE_CODE_PREFIX = "ST"
STORE_CODE_LENGTH = 8
STORE_CODE_ALPHABET = string.ascii_uppercase + string.digits
STORE_CODE_MAX_ATTEMPTS = 32


def get_store_dashboard_stats():
    """Return total / pending / active / suspended counts in one aggregate query."""
    return Store.objects.aggregate(
        total=Count("id"),
        pending=Count("id", filter=Q(status=StoreStatus.PENDING)),
        active=Count("id", filter=Q(status=StoreStatus.ACTIVE)),
        suspended=Count("id", filter=Q(status=StoreStatus.SUSPENDED)),
    )


def _candidate_store_code():
    token = "".join(
        secrets.choice(STORE_CODE_ALPHABET) for _ in range(STORE_CODE_LENGTH)
    )
    return f"{STORE_CODE_PREFIX}{token}"


def generate_store_code(*, exclude_pk=None):
    """
    Return a store code that is not currently used.

    Concurrent inserts are protected by the unique constraint on Store.store_code;
    Store.save() retries on IntegrityError when allocating a new code.
    """
    for _ in range(STORE_CODE_MAX_ATTEMPTS):
        code = _candidate_store_code()
        queryset = Store.objects.filter(store_code=code)
        if exclude_pk is not None:
            queryset = queryset.exclude(pk=exclude_pk)
        if not queryset.exists():
            return code
    raise RuntimeError("Unable to generate a unique store code after multiple attempts.")


def log_store_audit(
    *,
    actor,
    action,
    description,
    request=None,
    target_user=None,
    metadata=None,
    ip_address=None,
):
    resolved_ip = ip_address
    if resolved_ip is None and request is not None:
        resolved_ip = get_client_ip(request)
    # Never persist credentials in audit metadata.
    safe_metadata = {
        key: value
        for key, value in (metadata or {}).items()
        if key.lower() not in {"password", "confirm_password", "temporary_password"}
    }
    return AdminAuditLog.objects.create(
        actor=actor,
        action=action,
        target_user=target_user,
        description=description,
        metadata=safe_metadata,
        ip_address=resolved_ip,
    )


@transaction.atomic
def record_status_change(
    *,
    store,
    new_status,
    changed_by,
    reason="",
    ip_address=None,
    request=None,
):
    from .status import validate_status_transition

    old_status = store.status
    validate_status_transition(
        current_status=old_status,
        new_status=new_status,
        reason=reason,
    )
    store.status = new_status
    store.save(update_fields=["status", "updated_at"])
    history = StoreStatusHistory.objects.create(
        store=store,
        old_status=old_status,
        new_status=new_status,
        changed_by=changed_by,
        reason=(reason or "").strip(),
        ip_address=ip_address if ip_address is not None else (
            get_client_ip(request) if request is not None else None
        ),
    )
    log_store_audit(
        actor=changed_by,
        action=AdminAuditLog.Action.STORE_STATUS_CHANGED,
        description=(
            f"Changed store '{store.store_code}' status "
            f"from {old_status or '—'} to {new_status}."
        ),
        request=request,
        ip_address=history.ip_address,
        metadata={
            "store_id": store.pk,
            "store_code": store.store_code,
            "old_status": old_status,
            "new_status": new_status,
            "reason": history.reason,
        },
    )
    return store


def get_active_store_membership(user):
    """Return the user's active StoreUser membership, if any."""
    if not user or not user.is_authenticated:
        return None
    return (
        StoreUser.objects.select_related("store", "store__address", "store__category")
        .filter(user=user, is_active=True)
        .first()
    )

def _create_store_user(*, store, user_data, created_by, is_primary=False):
    designation = user_data.pop("designation", "")
    can_manage_inventory = user_data.pop("can_manage_inventory", True)
    password = user_data.pop("password")
    user = User(
        role=Role.STORE_USER,
        is_staff=False,
        is_superuser=False,
        **user_data,
    )
    user.set_password(password)
    user.full_clean()
    user.save()

    membership = StoreUser(
        store=store,
        user=user,
        is_primary=is_primary,
        is_active=True,
        can_manage_inventory=bool(can_manage_inventory),
        designation=designation,
        created_by=created_by,
    )
    membership.full_clean()
    membership.save()
    return membership, user


@transaction.atomic
def create_store(
    *,
    store_data,
    address_data,
    created_by,
    primary_user_data=None,
    initial_status=StoreStatus.PENDING,
    request=None,
):
    address = Address(**address_data)
    address.full_clean()
    address.save()

    cleaned_store_data = {
        key: value
        for key, value in store_data.items()
        if not (key == "image" and value in (False, None))
    }
    store = Store(
        address=address,
        created_by=created_by,
        status=initial_status,
        **cleaned_store_data,
    )
    store.full_clean()
    store.save()

    StoreStatusHistory.objects.create(
        store=store,
        old_status="",
        new_status=store.status,
        changed_by=created_by,
        reason="Store created",
        ip_address=get_client_ip(request) if request is not None else None,
    )

    primary_user = None
    if primary_user_data:
        _membership, primary_user = _create_store_user(
            store=store,
            user_data=primary_user_data,
            created_by=created_by,
            is_primary=True,
        )
        log_store_audit(
            actor=created_by,
            action=AdminAuditLog.Action.STORE_USER_CREATED,
            description=(
                f"Created primary store user '{primary_user.username}' "
                f"for store '{store.store_code}'."
            ),
            request=request,
            target_user=primary_user,
            metadata={
                "store_id": store.pk,
                "store_code": store.store_code,
                "is_primary": True,
            },
        )

    log_store_audit(
        actor=created_by,
        action=AdminAuditLog.Action.STORE_CREATED,
        description=f"Created store '{store.store_code}'.",
        request=request,
        metadata={
            "store_id": store.pk,
            "store_code": store.store_code,
            "status": store.status,
            "has_primary_user": primary_user is not None,
        },
    )
    return store, primary_user


@transaction.atomic
def create_additional_store_user(
    *,
    store,
    user_data,
    created_by,
    request=None,
    is_primary=False,
):
    # Serialize primary changes for this store to avoid unique-constraint races.
    list(StoreUser.objects.select_for_update().filter(store=store).order_by("pk"))
    if is_primary:
        StoreUser.objects.filter(store=store, is_primary=True).update(is_primary=False)

    membership, user = _create_store_user(
        store=store,
        user_data=user_data,
        created_by=created_by,
        is_primary=is_primary,
    )
    log_store_audit(
        actor=created_by,
        action=AdminAuditLog.Action.STORE_USER_CREATED,
        description=(
            f"Created store user '{user.username}' for store '{store.store_code}'."
        ),
        request=request,
        target_user=user,
        metadata={
            "store_id": store.pk,
            "store_code": store.store_code,
            "is_primary": is_primary,
        },
    )
    return membership, user


@transaction.atomic
def transfer_store_user_primary(*, store, membership):
    """Demote any current primary and mark membership as primary."""
    list(StoreUser.objects.select_for_update().filter(store=store).order_by("pk"))
    StoreUser.objects.filter(store=store, is_primary=True).exclude(
        pk=membership.pk
    ).update(is_primary=False)
    if not membership.is_primary:
        membership.is_primary = True
        membership.save(update_fields=["is_primary", "updated_at"])
    return membership


# Backwards-compatible alias used by older tests/callers.
def create_store_with_primary_user(
    *,
    store_data,
    address_data,
    primary_user_data,
    created_by,
    request=None,
    initial_status=StoreStatus.PENDING,
):
    store, user = create_store(
        store_data=store_data,
        address_data=address_data,
        created_by=created_by,
        primary_user_data=primary_user_data,
        initial_status=initial_status,
        request=request,
    )
    return store, user, None
