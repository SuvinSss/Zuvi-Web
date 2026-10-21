"""Management-side store workflows: create, edit, readiness and approval rules.

The browser never decides a store's status. ``create_managed_store`` computes it:

* Draft requested                      -> DRAFT
* mandatory details missing            -> NEEDS_INFO (the missing list is stored)
* complete, actor may approve stores   -> ACTIVE, with approved_by / approved_at
* complete, actor may not approve      -> PENDING

Verification (documents / GSTIN) is never set here: a store stays UNVERIFIED until
someone with approval rights verifies it explicitly. ``ordering_enabled`` is a
separate gate checked at checkout: an approved store without opening hours and
serviceability cannot take orders yet.
"""
import re
from datetime import time
from decimal import Decimal

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from accounts.audit_ip import get_client_ip
from accounts.models import AdminAuditLog
from locations.models import Address

from .decorators import user_has_store_permission
from .models import CreationSource, Store, StoreStatus, StoreStatusHistory, StoreUser, VerificationStatus
from .services import _create_store_user, create_additional_store_user, log_store_audit

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
GSTIN_RE = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
PHONE_RE = re.compile(r"^\+?\d[\d\s-]{6,18}$")

STORE_FIELDS = (
    "name", "store_type", "category", "contact_phone", "alternative_phone", "email", "description",
    "business_name", "gstin", "commission_percentage", "accepts_orders", "offers_delivery", "offers_pickup",
    "min_order_amount", "service_radius_km", "opening_hours", "closures", "image", "banner",
)
ADDRESS_FIELDS = ("line1", "line2", "landmark", "city", "district", "state", "postal_code", "country", "latitude", "longitude")
COMMERCIAL_FIELDS = {"commission_percentage"}


def unique_slug(name, *, exclude_pk=None):
    base = slugify(name)[:200] or "store"
    candidate, n = base, 2
    qs = Store.objects.all()
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    while qs.filter(slug=candidate).exists():
        candidate = f"{base}-{n}"
        n += 1
    return candidate


def validate_hours(hours):
    """Validate ``{"mon": [{"open": "09:00", "close": "21:00"}], ...}``; closed days are omitted or empty."""
    if hours in (None, {}):
        return {}
    if not isinstance(hours, dict):
        raise ValidationError({"opening_hours": "Opening hours must be an object keyed by day."})
    clean = {}
    for day, slots in hours.items():
        if day not in DAYS:
            raise ValidationError({"opening_hours": f"Unknown day '{day}'."})
        if not isinstance(slots, list) or len(slots) > 4:
            raise ValidationError({"opening_hours": f"{day}: use a list of at most 4 time slots."})
        parsed = []
        for slot in slots:
            try:
                opens = time.fromisoformat(str(slot["open"]))
                closes = time.fromisoformat(str(slot["close"]))
            except (KeyError, TypeError, ValueError):
                raise ValidationError({"opening_hours": f"{day}: times must look like 09:00."}) from None
            if closes <= opens:
                raise ValidationError({"opening_hours": f"{day}: closing time must be after opening time."})
            parsed.append((opens, closes))
        parsed.sort()
        for (_, end), (start, _) in zip(parsed, parsed[1:]):
            if start < end:
                raise ValidationError({"opening_hours": f"{day}: time slots overlap."})
        clean[day] = [{"open": o.strftime("%H:%M"), "close": c.strftime("%H:%M")} for o, c in parsed]
    return clean


def validate_closures(closures):
    if closures in (None, []):
        return []
    if not isinstance(closures, list) or len(closures) > 100:
        raise ValidationError({"closures": "Closures must be a list of up to 100 dates."})
    clean = []
    for item in closures:
        try:
            date_value = timezone.datetime.fromisoformat(str(item.get("date"))).date()
        except (AttributeError, ValueError):
            raise ValidationError({"closures": "Each closure needs a date like 2026-12-25."}) from None
        clean.append({"date": date_value.isoformat(), "reason": str(item.get("reason", ""))[:120]})
    return clean


def approval_requirements(store):
    """Mandatory details before management may approve a store. Returns a list of plain messages."""
    missing = []
    if not (store.name or "").strip():
        missing.append("Store name")
    if not store.category_id:
        missing.append("Store category")
    if not (store.contact_phone or "").strip():
        missing.append("Contact phone")
    address = store.address
    for label, value in (("Address line 1", address.line1), ("City", address.city), ("State", address.state), ("Postal code", address.postal_code)):
        if not (value or "").strip():
            missing.append(label)
    if address.latitude is None or address.longitude is None or (not address.latitude and not address.longitude):
        missing.append("Map location (latitude and longitude)")
    if not (store.offers_delivery or store.offers_pickup):
        missing.append("At least one of delivery or pickup")
    if store.pk and not store.store_users.filter(is_active=True, is_primary=True).exists():
        missing.append("Store owner account")
    return missing


def operational_gaps(store):
    """What still blocks the store from taking orders even when it is approved."""
    gaps = []
    if not any(store.opening_hours.get(day) for day in DAYS):
        gaps.append("Opening hours")
    if store.offers_delivery and not store.service_radius_km:
        gaps.append("Delivery service radius")
    if not store.accepts_orders:
        gaps.append("Order acceptance is switched off")
    return gaps


def _clean_fields(data, *, partial):
    errors = {}
    data = dict(data)
    if "gstin" in data:
        gstin = (data["gstin"] or "").strip().upper()
        if gstin and not GSTIN_RE.match(gstin):
            errors["gstin"] = "Enter a valid 15-character GSTIN."
        data["gstin"] = gstin
    for key in ("contact_phone", "alternative_phone"):
        if data.get(key) and not PHONE_RE.match(data[key]):
            errors[key] = "Enter a valid phone number."
    if "opening_hours" in data:
        try:
            data["opening_hours"] = validate_hours(data["opening_hours"])
        except ValidationError as exc:
            errors.update(exc.message_dict)
    if "closures" in data:
        try:
            data["closures"] = validate_closures(data["closures"])
        except ValidationError as exc:
            errors.update(exc.message_dict)
    if errors:
        raise ValidationError(errors)
    return data


def _refresh_gates(store):
    """Recompute stored requirement/readiness flags. Never changes verification."""
    store.missing_requirements = approval_requirements(store)
    if store.creation_source == CreationSource.ADMIN:
        store.ordering_enabled = store.status == StoreStatus.ACTIVE and not operational_gaps(store)


def _record(store, old, new, actor, reason, request):
    StoreStatusHistory.objects.create(store=store, old_status=old, new_status=new, changed_by=actor, reason=reason, ip_address=get_client_ip(request) if request is not None else None)


@transaction.atomic
def create_managed_store(*, actor, data, address, owner=None, save_draft=False, request=None):
    """Create a store from the management wizard. Returns ``(store, outcome)``."""
    data = _clean_fields(data, partial=False)
    password = None
    if owner:
        owner = dict(owner)
        password = owner.get("password")
        try:
            validate_password(password)
        except ValidationError as exc:
            raise ValidationError({"owner_password": exc.messages}) from exc
    addr = Address(**{k: address[k] for k in ADDRESS_FIELDS if k in address})
    addr.full_clean()
    addr.save()
    fields = {k: data[k] for k in STORE_FIELDS if k in data}
    store = Store(address=addr, created_by=actor, creation_source=CreationSource.ADMIN, status=StoreStatus.DRAFT, **fields)
    store.slug = unique_slug(store.name)
    can_approve = user_has_store_permission(actor, "stores.approve_store")
    if not can_approve:
        store.commission_percentage = Decimal("0.00")  # commercial terms need approval rights
    store.full_clean(exclude=["slug", "store_code"])
    store.save()
    if owner:
        _create_store_user(store=store, user_data=owner, created_by=actor, is_primary=True)
    store = Store.objects.select_related("address").get(pk=store.pk)

    missing = approval_requirements(store)
    if save_draft:
        target = StoreStatus.DRAFT
    elif missing:
        target = StoreStatus.NEEDS_INFO
    elif can_approve:
        target = StoreStatus.ACTIVE
    else:
        target = StoreStatus.PENDING
    store.status = target
    if target == StoreStatus.ACTIVE:
        store.approved_by, store.approved_at = actor, timezone.now()
    _refresh_gates(store)
    store.save()
    _record(store, "", target, actor, "Created by management", request)
    log_store_audit(
        actor=actor, action=AdminAuditLog.Action.STORE_CREATED, request=request,
        description=f"Created store '{store.store_code}' as {target}.",
        metadata={"store_id": store.pk, "status": target, "source": CreationSource.ADMIN, "missing": store.missing_requirements,
                  "auto_approved": target == StoreStatus.ACTIVE, "ordering_enabled": store.ordering_enabled},
    )
    return store, {"status": target, "missing": store.missing_requirements, "operational_gaps": operational_gaps(store)}


@transaction.atomic
def update_managed_store(*, actor, store, data=None, address=None, request=None):
    store = Store.objects.select_for_update().select_related("address").get(pk=store.pk)
    data = _clean_fields(data or {}, partial=True)
    changed = []
    can_approve = user_has_store_permission(actor, "stores.approve_store")
    for key in STORE_FIELDS:
        if key not in data:
            continue
        if key in COMMERCIAL_FIELDS and not can_approve:
            raise ValidationError({key: "You do not have permission to change commercial terms."})
        value = data[key]
        if key in ("image", "banner") and value in (None, "", False):
            continue
        if getattr(store, key) != value:
            setattr(store, key, value)
            changed.append(key)
    if "name" in changed and store.creation_source == CreationSource.ADMIN:
        store.slug = unique_slug(store.name, exclude_pk=store.pk)
    if address:
        addr = store.address
        for key in ADDRESS_FIELDS:
            if key in address and getattr(addr, key) != address[key]:
                setattr(addr, key, address[key])
                changed.append(f"address.{key}")
        addr.full_clean()
        addr.save()
    store.full_clean(exclude=["slug", "store_code"])
    old_status = store.status
    store.address.refresh_from_db()
    missing = approval_requirements(store)
    if store.status == StoreStatus.NEEDS_INFO and not missing:
        store.status = StoreStatus.PENDING
    elif store.status == StoreStatus.PENDING and missing:
        store.status = StoreStatus.NEEDS_INFO
    _refresh_gates(store)
    store.save()
    if store.status != old_status:
        _record(store, old_status, store.status, actor, "Updated by management", request)
    if changed:
        log_store_audit(
            actor=actor, action=AdminAuditLog.Action.STORE_UPDATED, request=request,
            description=f"Updated store '{store.store_code}'.",
            metadata={"store_id": store.pk, "fields": sorted(changed)},  # field names only, never values
        )
    return store


@transaction.atomic
def approve_managed_store(*, actor, store, reason="", request=None):
    """Approve (activate) a store, enforcing mandatory requirements and stamping the approver."""
    from .services import record_status_change

    store = Store.objects.select_for_update().select_related("address").get(pk=store.pk)
    missing = approval_requirements(store) if store.creation_source == CreationSource.ADMIN else []
    if missing:
        raise ValidationError({"detail": "Cannot approve yet. Missing: " + ", ".join(missing) + "."})
    record_status_change(store=store, new_status=StoreStatus.ACTIVE, changed_by=actor, reason=reason, request=request)
    store.refresh_from_db()
    store.approved_by, store.approved_at = actor, timezone.now()
    _refresh_gates(store)
    store.save(update_fields=["approved_by", "approved_at", "missing_requirements", "ordering_enabled", "updated_at"])
    return store


@transaction.atomic
def set_verification(*, actor, store, status, request=None):
    if status not in VerificationStatus.values or status == VerificationStatus.UNVERIFIED:
        raise ValidationError({"verification_status": "Choose Verified or Verification rejected."})
    store = Store.objects.select_for_update().get(pk=store.pk)
    store.verification_status, store.verified_by, store.verified_at = status, actor, timezone.now()
    store.save(update_fields=["verification_status", "verified_by", "verified_at", "updated_at"])
    log_store_audit(actor=actor, action=AdminAuditLog.Action.STORE_UPDATED, request=request,
                    description=f"Set verification of '{store.store_code}' to {status}.",
                    metadata={"store_id": store.pk, "verification_status": status})
    return store


@transaction.atomic
def add_managed_staff(*, actor, store, user_data, is_primary=False, request=None):
    try:
        validate_password(user_data.get("password"))
    except ValidationError as exc:
        raise ValidationError({"password": exc.messages}) from exc
    membership, user = create_additional_store_user(store=store, user_data=dict(user_data), created_by=actor, request=request, is_primary=is_primary)
    store = Store.objects.select_related("address").get(pk=store.pk)
    _refresh_gates(store)
    if store.status == StoreStatus.NEEDS_INFO and not store.missing_requirements:
        store.status = StoreStatus.PENDING
    store.save(update_fields=["missing_requirements", "ordering_enabled", "status", "updated_at"])
    return membership, user
