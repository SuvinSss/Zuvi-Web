import secrets
import string

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Prefetch, Q

from accounts.audit_ip import get_client_ip
from accounts.models import AdminAuditLog, Role
from locations.models import Address

from .models import Customer, CustomerAddress, RegistrationSource, VerificationStatus

User = get_user_model()

CUSTOMER_CODE_PREFIX = "CU"
CUSTOMER_CODE_LENGTH = 8
CUSTOMER_CODE_ALPHABET = string.ascii_uppercase + string.digits
CUSTOMER_CODE_MAX_ATTEMPTS = 32


def get_customer_dashboard_stats():
    """Return customer management card counts in one aggregate query."""
    return Customer.objects.aggregate(
        total=Count("id"),
        active=Count("id", filter=Q(user__is_active=True)),
        inactive=Count("id", filter=Q(user__is_active=False)),
        verified=Count(
            "id",
            filter=Q(verification_status=VerificationStatus.VERIFIED),
        ),
        unverified=Count(
            "id",
            filter=Q(verification_status=VerificationStatus.UNVERIFIED),
        ),
        website=Count(
            "id",
            filter=Q(registration_source=RegistrationSource.WEBSITE),
        ),
        management=Count(
            "id",
            filter=Q(registration_source=RegistrationSource.MANAGEMENT_PORTAL),
        ),
    )


def _candidate_customer_code():
    token = "".join(
        secrets.choice(CUSTOMER_CODE_ALPHABET) for _ in range(CUSTOMER_CODE_LENGTH)
    )
    return f"{CUSTOMER_CODE_PREFIX}{token}"


def generate_customer_code(*, exclude_pk=None):
    """
    Return a customer code that is not currently used.

    Concurrent inserts are protected by the unique constraint on Customer.customer_code;
    Customer.save() retries on IntegrityError when allocating a new code.
    """
    for _ in range(CUSTOMER_CODE_MAX_ATTEMPTS):
        code = _candidate_customer_code()
        queryset = Customer.objects.filter(customer_code=code)
        if exclude_pk is not None:
            queryset = queryset.exclude(pk=exclude_pk)
        if not queryset.exists():
            return code
    raise RuntimeError(
        "Unable to generate a unique customer code after multiple attempts."
    )


def _sanitize_metadata(metadata):
    if not metadata:
        return {}
    blocked = {"password", "password1", "password2", "confirm_password"}
    return {
        key: value
        for key, value in metadata.items()
        if key not in blocked and "password" not in key.lower()
    }


def log_customer_audit(
    *,
    actor,
    action,
    description,
    request=None,
    target_user=None,
    metadata=None,
    ip_address=None,
):
    return AdminAuditLog.objects.create(
        actor=actor,
        action=action,
        target_user=target_user,
        description=description,
        metadata=_sanitize_metadata(metadata),
        ip_address=ip_address
        if ip_address is not None
        else get_client_ip(request),
    )


@transaction.atomic
def create_customer_with_user(
    *,
    user_data,
    registration_source,
    created_by=None,
    date_of_birth=None,
    notes="",
    initial_address_data=None,
    request=None,
):
    data = dict(user_data)
    password = data.pop("password")
    # Never trust caller-supplied privilege or identity-control fields.
    for key in (
        "role",
        "is_staff",
        "is_superuser",
        "is_active",
        "groups",
        "user_permissions",
    ):
        data.pop(key, None)

    validate_password(password)

    user = User(**data)
    user.role = Role.CUSTOMER
    user.is_staff = False
    user.is_superuser = False
    user.set_password(password)
    user.full_clean()
    user.save()

    customer = Customer(
        user=user,
        registration_source=registration_source,
        verification_status=VerificationStatus.UNVERIFIED,
        date_of_birth=date_of_birth,
        notes=notes or "",
        created_by=created_by,
    )
    customer.full_clean()
    customer.save()

    if initial_address_data:
        create_customer_delivery_address(
            customer=customer,
            data=initial_address_data,
        )

    if created_by is not None:
        log_customer_audit(
            actor=created_by,
            action=AdminAuditLog.Action.CUSTOMER_CREATED,
            description=(
                f"Created customer '{user.username}' "
                f"({customer.customer_code}) via {registration_source}."
            ),
            request=request,
            target_user=user,
            metadata={
                "customer_id": customer.pk,
                "customer_code": customer.customer_code,
                "registration_source": registration_source,
                "has_initial_address": bool(initial_address_data),
            },
        )
    return customer, user


@transaction.atomic
def update_customer_profile(
    *,
    customer,
    user_fields=None,
    date_of_birth=None,
    notes=None,
    actor=None,
    request=None,
):
    user = customer.user
    user_fields = user_fields or {}
    protected = {
        "role",
        "is_staff",
        "is_superuser",
        "password",
        "is_active",
        "username",
        "groups",
        "user_permissions",
    }
    for key in protected:
        user_fields.pop(key, None)

    for field, value in user_fields.items():
        setattr(user, field, value)
    user.full_clean()
    user.save()

    if date_of_birth is not None:
        customer.date_of_birth = date_of_birth
    if notes is not None:
        customer.notes = notes
    customer.full_clean()
    customer.save()

    if actor is not None:
        log_customer_audit(
            actor=actor,
            action=AdminAuditLog.Action.CUSTOMER_UPDATED,
            description=(
                f"Updated customer '{user.username}' ({customer.customer_code})."
            ),
            request=request,
            target_user=user,
            metadata={
                "customer_id": customer.pk,
                "customer_code": customer.customer_code,
                "fields": sorted(set(user_fields) | {"date_of_birth", "notes"}),
            },
        )
    return customer


@transaction.atomic
def set_customer_active(*, customer, is_active, actor, request=None, reason=""):
    """
    Activate or deactivate a Customer account without deleting related data.

    Deactivation requires a non-empty reason and only flips user.is_active.
    """
    user = customer.user
    if user.is_active == is_active:
        return customer

    reason = (reason or "").strip()
    if not is_active and not reason:
        raise ValidationError({"reason": "A reason is required to deactivate a customer."})

    user.is_active = is_active
    user.save(update_fields=["is_active"])

    action = (
        AdminAuditLog.Action.CUSTOMER_ACTIVATED
        if is_active
        else AdminAuditLog.Action.CUSTOMER_DEACTIVATED
    )
    state = "activated" if is_active else "deactivated"
    description = (
        f"{state.capitalize()} customer '{user.username}' "
        f"({customer.customer_code})."
    )
    if reason:
        description = f"{description} Reason: {reason}"

    metadata = {
        "customer_id": customer.pk,
        "customer_code": customer.customer_code,
        "is_active": is_active,
    }
    if reason:
        metadata["reason"] = reason

    log_customer_audit(
        actor=actor,
        action=action,
        description=description,
        request=request,
        target_user=user,
        metadata=metadata,
    )
    return customer


@transaction.atomic
def set_customer_verification(*, customer, verification_status, actor, request=None):
    if verification_status not in VerificationStatus.values:
        raise ValidationError(
            {"verification_status": "Invalid verification status."}
        )
    if customer.verification_status == verification_status:
        return customer

    customer.verification_status = verification_status
    customer.full_clean()
    customer.save(update_fields=["verification_status", "updated_at"])

    action = (
        AdminAuditLog.Action.CUSTOMER_VERIFIED
        if verification_status == VerificationStatus.VERIFIED
        else AdminAuditLog.Action.CUSTOMER_UNVERIFIED
    )
    log_customer_audit(
        actor=actor,
        action=action,
        description=(
            f"Set verification for customer '{customer.user.username}' "
            f"({customer.customer_code}) to {verification_status}."
        ),
        request=request,
        target_user=customer.user,
        metadata={
            "customer_id": customer.pk,
            "customer_code": customer.customer_code,
            "verification_status": verification_status,
        },
    )
    return customer


def get_customer_profile_completion_message(*, user, has_default_address):
    """
    Build a profile-completion message from the authenticated user's fields.

    Does not expose another customer's data; callers must pass request.user.
    """
    missing = []
    if not (user.first_name or "").strip() or not (user.last_name or "").strip():
        missing.append("your full name")
    if not (user.phone_number or "").strip():
        missing.append("a phone number")
    if not has_default_address:
        missing.append("a default delivery address")

    if not missing:
        return "Your profile is complete."
    if len(missing) == 1:
        return f"Complete your profile by adding {missing[0]}."
    if len(missing) == 2:
        return f"Complete your profile by adding {missing[0]} and {missing[1]}."
    return (
        "Complete your profile by adding "
        + ", ".join(missing[:-1])
        + f", and {missing[-1]}."
    )


def get_customer_portal_dashboard_context(user):
    """
    Load dashboard data for the authenticated customer only.

    Always keyed by user.pk — never by a client-supplied customer_id.
    """
    from cart.services import get_cart_item_count
    from orders.portal import (
        get_customer_order_dashboard_stats,
        get_customer_recent_orders,
    )

    customer = (
        Customer.objects.select_related("user")
        .prefetch_related(
            Prefetch(
                "addresses",
                queryset=CustomerAddress.objects.filter(is_active=True)
                .select_related("address")
                .order_by("-is_default", "-created_at"),
            )
        )
        .get(user_id=user.pk)
    )
    addresses = list(customer.addresses.all())
    default_address = next(
        (address for address in addresses if address.is_default),
        None,
    )
    profile_completion_message = get_customer_profile_completion_message(
        user=customer.user,
        has_default_address=default_address is not None,
    )
    order_stats = get_customer_order_dashboard_stats(customer)
    return {
        "customer": customer,
        "default_address": default_address,
        "saved_address_count": len(addresses),
        "profile_completion_message": profile_completion_message,
        "profile_is_complete": profile_completion_message == "Your profile is complete.",
        "cart_item_count": get_cart_item_count(customer),
        "pending_order_count": order_stats["pending"],
        "recent_orders": get_customer_recent_orders(customer),
    }


def _apply_location_fields(address, data):
    address.line1 = data["line1"]
    address.line2 = data.get("line2") or ""
    address.landmark = data.get("landmark") or ""
    address.city = data["city"]
    address.district = data.get("district") or ""
    address.state = data["state"]
    address.postal_code = data["postal_code"]
    address.latitude = data["latitude"]
    address.longitude = data["longitude"]


def _resolve_is_default_for_customer(*, customer, want_default, exclude_pk=None):
    """
    First active address is always default.

    Otherwise honour the requested default flag.
    """
    active_qs = CustomerAddress.objects.filter(customer=customer, is_active=True)
    if exclude_pk is not None:
        active_qs = active_qs.exclude(pk=exclude_pk)
    if not active_qs.exists():
        return True
    return bool(want_default)


@transaction.atomic
def create_customer_delivery_address(*, customer, data):
    """
    Create a CustomerAddress + Address for the given Customer only.

    customer must already be resolved from request.user — never from form input.
    """
    is_default = _resolve_is_default_for_customer(
        customer=customer,
        want_default=data.get("is_default", False),
    )

    address = Address()
    _apply_location_fields(address, data)
    address.full_clean()
    address.save()

    customer_address = CustomerAddress(
        customer=customer,
        address=address,
        label=data["label"],
        recipient_name=data["recipient_name"],
        phone_number=data["phone_number"],
        delivery_instructions=data.get("delivery_instructions") or "",
        is_default=is_default,
        is_active=True,
    )
    customer_address.full_clean()
    customer_address.save()
    return customer_address


@transaction.atomic
def update_customer_delivery_address(*, customer_address, data):
    """Update an address already verified to belong to the caller."""
    customer_address = (
        CustomerAddress.objects.select_for_update()
        .select_related("address", "customer")
        .get(pk=customer_address.pk)
    )
    if not customer_address.is_active:
        raise ValidationError("Inactive addresses cannot be edited.")

    was_default = customer_address.is_default
    is_default = _resolve_is_default_for_customer(
        customer=customer_address.customer,
        want_default=data.get("is_default", False),
        exclude_pk=customer_address.pk,
    )

    address = customer_address.address
    _apply_location_fields(address, data)
    address.full_clean()
    address.save()

    customer_address.label = data["label"]
    customer_address.recipient_name = data["recipient_name"]
    customer_address.phone_number = data["phone_number"]
    customer_address.delivery_instructions = data.get("delivery_instructions") or ""
    customer_address.is_default = is_default
    customer_address.full_clean()
    customer_address.save()

    # Keep exactly one active default when other active addresses remain.
    if was_default and not customer_address.is_default:
        replacement = (
            CustomerAddress.objects.select_for_update()
            .filter(
                customer_id=customer_address.customer_id,
                is_active=True,
            )
            .exclude(pk=customer_address.pk)
            .order_by("-created_at")
            .first()
        )
        if replacement is not None:
            replacement.is_default = True
            replacement.save()

    return customer_address


@transaction.atomic
def set_customer_address_as_default(*, customer_address):
    customer_address = (
        CustomerAddress.objects.select_for_update()
        .select_related("customer")
        .get(pk=customer_address.pk)
    )
    if not customer_address.is_active:
        raise ValidationError("Inactive addresses cannot be set as default.")
    customer_address.is_default = True
    customer_address.save()
    return customer_address


@transaction.atomic
def deactivate_customer_address(*, customer_address):
    """
    Deactivate an address. If it was the active default, promote another active
    address for the same Customer when one exists.
    """
    customer_address = (
        CustomerAddress.objects.select_for_update()
        .select_related("customer")
        .get(pk=customer_address.pk)
    )
    if not customer_address.is_active:
        return customer_address

    was_default = customer_address.is_default
    customer_address.is_active = False
    customer_address.is_default = False
    customer_address.save(update_fields=["is_active", "is_default", "updated_at"])

    if was_default:
        replacement = (
            CustomerAddress.objects.select_for_update()
            .filter(
                customer_id=customer_address.customer_id,
                is_active=True,
            )
            .order_by("-created_at")
            .first()
        )
        if replacement is not None:
            replacement.is_default = True
            replacement.save()

    return customer_address
