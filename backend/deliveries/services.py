"""Delivery business logic. Views call these functions and nothing else.

State machine (Delivery.status)::

    PENDING_ASSIGNMENT -> OFFERED -> ACCEPTED -> AT_STORE -> IN_TRANSIT -> ARRIVED -> DELIVERED
          ^                 |  \\                                \\            |
          |  reject/expire  v   \\-> (back to PENDING_ASSIGNMENT)  \\---------> FAILED -> (retry) PENDING_ASSIGNMENT
          +-----------------+                      any non-terminal -> CANCELLED

A delivery can only become DELIVERED through ``complete_delivery``, which
requires stored evidence, so no order is completed without proof.
"""
from __future__ import annotations

import secrets
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count, F, Q
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac

from core.geo import haversine_m, valid_coordinates
from core.uploads import clean_image
from notifications.models import Kind
from notifications.services import notify, notify_many
from orders.models import (
    FulfillmentType,
    Order,
    StoreOrder,
    StoreOrderStatus,
    StoreOrderStatusHistory,
)
from orders.order_status_sync import sync_order_status_from_store_orders

from . import policy
from .models import (
    AssignmentStatus,
    Delivery,
    DeliveryAssignment,
    DeliveryAttempt,
    DeliveryEvidence,
    DeliveryPartner,
    DeliveryStatus,
    DeliveryStatusHistory,
    EvidenceKind,
    EvidencePhoto,
    LocationPing,
    PartnerStatus,
)

D = DeliveryStatus

# action -> (allowed source statuses, target status)
TRANSITIONS = {
    "offer": ({D.PENDING_ASSIGNMENT}, D.OFFERED),
    "accept": ({D.OFFERED}, D.ACCEPTED),
    "release": ({D.OFFERED, D.ACCEPTED, D.AT_STORE}, D.PENDING_ASSIGNMENT),
    "arrive_store": ({D.ACCEPTED}, D.AT_STORE),
    "pickup": ({D.ACCEPTED, D.AT_STORE}, D.IN_TRANSIT),
    "arrive_customer": ({D.IN_TRANSIT}, D.ARRIVED),
    "deliver": ({D.IN_TRANSIT, D.ARRIVED}, D.DELIVERED),
    "fail": ({D.IN_TRANSIT, D.ARRIVED}, D.FAILED),
    "retry": ({D.FAILED}, D.PENDING_ASSIGNMENT),
    "cancel": (
        {D.PENDING_ASSIGNMENT, D.OFFERED, D.ACCEPTED, D.AT_STORE, D.IN_TRANSIT, D.ARRIVED, D.FAILED},
        D.CANCELLED,
    ),
}


# ---------------------------------------------------------------- helpers

def _lock(delivery_id) -> Delivery:
    return (
        Delivery.objects.select_for_update(of=("self",))
        .select_related("store_order__order__customer__user", "store_order__store", "partner__user")
        .get(pk=delivery_id)
    )


def _move(delivery: Delivery, action: str, *, actor=None, note="") -> Delivery:
    sources, target = TRANSITIONS[action]
    if delivery.status not in sources:
        raise ValidationError({"status": f"Cannot {action.replace('_', ' ')} a delivery that is {delivery.get_status_display().lower()}."})
    old = delivery.status
    delivery.status = target
    delivery.save(update_fields=["status", "updated_at"])
    DeliveryStatusHistory.objects.create(
        delivery=delivery, old_status=old, new_status=target, changed_by=actor, note=note[:500]
    )
    return delivery


def _set_store_order_status(store_order: StoreOrder, new_status, *, actor, reason):
    """Move a StoreOrder and keep the parent Order in sync (same pattern as the store portal)."""
    old = store_order.status
    if old == new_status:
        return
    store_order.status = new_status
    store_order.save(update_fields=["status", "updated_at"])
    StoreOrderStatusHistory.objects.create(
        store_order=store_order, old_status=old, new_status=new_status, changed_by=actor, reason=reason[:500]
    )
    sync_order_status_from_store_orders(order=store_order.order, actor=actor, reason=reason)


def _customer_user(delivery):
    return delivery.store_order.order.customer.user


def _store_users(store_order):
    from stores.models import StoreUser

    return [
        m.user
        for m in StoreUser.objects.filter(store_id=store_order.store_id, is_active=True, can_manage_orders=True).select_related("user")
        if m.user.is_active
    ]


def _admin_users():
    from accounts.models import Role, User

    return list(User.objects.filter(is_active=True, role__in=[Role.ADMIN, Role.SUPER_ADMIN]))


def _data(delivery):
    return {"delivery_id": delivery.pk, "order_number": delivery.store_order.order.order_number,
            "store_order_number": delivery.store_order.store_order_number}


def _decimal(value) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:
        raise ValidationError({"location": "Latitude and longitude must be numbers."}) from None


def _coords(latitude, longitude):
    lat, lon = _decimal(latitude), _decimal(longitude)
    if not valid_coordinates(lat, lon):
        raise ValidationError({"location": "Latitude must be -90..90 and longitude -180..180."})
    return round(lat, 6), round(lon, 6)


def _accuracy(value):
    if value in (None, ""):
        return None
    try:
        accuracy = float(value)
    except (TypeError, ValueError):
        raise ValidationError({"accuracy_m": "Accuracy must be a number of metres."}) from None
    if accuracy < 0:
        raise ValidationError({"accuracy_m": "Accuracy cannot be negative."})
    return accuracy


# ---------------------------------------------------------------- creation

@transaction.atomic
def ensure_delivery(store_order: StoreOrder) -> Delivery | None:
    """Create (idempotently) the delivery for a delivery-type StoreOrder."""
    order = store_order.order
    if order.fulfillment_type != FulfillmentType.DELIVERY:
        return None
    existing = Delivery.objects.filter(store_order=store_order).first()
    if existing:
        return existing
    # Delivery orders normally have no pickup counter: the route starts at the store itself.
    pickup = store_order.pickup_location.address if store_order.pickup_location_id else store_order.store.address
    delivery = Delivery.objects.create(
        store_order=store_order,
        pickup_latitude=pickup.latitude if pickup else None,
        pickup_longitude=pickup.longitude if pickup else None,
        dropoff_latitude=order.delivery_latitude,
        dropoff_longitude=order.delivery_longitude,
        otp_nonce=secrets.token_hex(8),
    )
    DeliveryAttempt.objects.create(delivery=delivery, number=1)
    DeliveryStatusHistory.objects.create(delivery=delivery, old_status="", new_status=delivery.status, note="Created when the store marked the order ready.")
    return delivery


def on_store_order_ready(store_order: StoreOrder, *, actor=None):
    """Hook called by the store workflow when a StoreOrder becomes READY."""
    delivery = ensure_delivery(store_order)
    if delivery is not None:
        transaction.on_commit(lambda: _auto_assign_after_commit(delivery.pk))
    return delivery


def _auto_assign_after_commit(delivery_id):
    try:
        with transaction.atomic():
            auto_assign(delivery_id)
    except Exception:  # never let assignment problems break the store's request
        import logging

        logging.getLogger(__name__).exception("Automatic assignment failed for delivery %s", delivery_id)


# ---------------------------------------------------------------- assignment

def _eligible_partners(delivery: Delivery):
    excluded = DeliveryAssignment.objects.filter(
        delivery=delivery, status__in=[AssignmentStatus.REJECTED, AssignmentStatus.EXPIRED, AssignmentStatus.REVOKED]
    ).values_list("partner_id", flat=True)
    busy = (
        DeliveryPartner.objects.annotate(
            active=Count("deliveries", filter=Q(deliveries__status__in=[D.OFFERED, D.ACCEPTED, D.AT_STORE, D.IN_TRANSIT, D.ARRIVED]))
        )
        .filter(active__gte=policy.max_active_per_partner())
        .values_list("pk", flat=True)
    )
    return (
        DeliveryPartner.objects.filter(status=PartnerStatus.APPROVED, is_online=True, user__is_active=True)
        .exclude(pk__in=excluded)
        .exclude(pk__in=busy)
    )


def _nearest(delivery: Delivery, partners):
    if delivery.pickup_latitude is None or delivery.pickup_longitude is None:
        return None
    radius = policy.max_assignment_radius_m()
    now = timezone.now()
    best, best_distance = None, None
    for partner in partners:
        if partner.last_latitude is None or partner.last_location_at is None:
            continue
        if now - partner.last_location_at > policy.stale_after() * 10:
            continue  # location far too old to rank by
        distance = haversine_m(partner.last_latitude, partner.last_longitude, delivery.pickup_latitude, delivery.pickup_longitude)
        if radius and distance > radius:
            continue
        if best is None or distance < best_distance:
            best, best_distance = partner, distance
    return best


def _create_offer(delivery: Delivery, partner, *, actor=None, automatic=False, reason="") -> DeliveryAssignment:
    _move(delivery, "offer", actor=actor, note=reason or ("Automatic assignment" if automatic else "Assigned by admin"))
    delivery.partner = partner
    delivery.save(update_fields=["partner", "updated_at"])
    assignment = DeliveryAssignment.objects.create(
        delivery=delivery, partner=partner, attempt_number=delivery.attempt_number, assigned_by=actor,
        automatic=automatic, reason=reason[:255], expires_at=timezone.now() + policy.offer_ttl(),
    )
    notify(partner.user, Kind.DELIVERY_OFFERED, "New delivery offer",
           f"Pickup from {delivery.store_order.store_name}.", _data(delivery))
    return assignment


@transaction.atomic
def auto_assign(delivery_id) -> DeliveryAssignment | None:
    """Offer the delivery to the nearest eligible online partner, if any."""
    delivery = _lock(delivery_id)
    if delivery.status != D.PENDING_ASSIGNMENT or delivery.needs_attention:
        return None
    if delivery.rejection_count >= policy.max_rejections():
        return _flag_attention(delivery, "Automatic assignment gave up after repeated rejections or time-outs.")
    partner = _nearest(delivery, _eligible_partners(delivery))
    if partner is None:
        return None  # stays queued; picked up by the next sweep or an admin
    return _create_offer(delivery, partner, automatic=True)


def _flag_attention(delivery, message):
    if not delivery.needs_attention:
        delivery.needs_attention = True
        delivery.save(update_fields=["needs_attention", "updated_at"])
        notify_many(_admin_users(), Kind.DELIVERY_REJECTED, "Delivery needs manual assignment", message, _data(delivery))
    return None


@transaction.atomic
def admin_assign(delivery_id, partner_id, *, actor, reason="") -> DeliveryAssignment:
    delivery = _lock(delivery_id)
    partner = DeliveryPartner.objects.select_related("user").filter(pk=partner_id).first()
    if partner is None or not partner.is_approved:
        raise ValidationError({"partner": "Choose an approved delivery partner."})
    if delivery.status in (D.OFFERED, D.ACCEPTED, D.AT_STORE):
        _revoke_active(delivery, actor=actor, reason=reason or "Reassigned by admin")
        delivery.status = D.PENDING_ASSIGNMENT
        delivery.save(update_fields=["status", "updated_at"])
    elif delivery.status != D.PENDING_ASSIGNMENT:
        raise ValidationError({"status": "Only deliveries that are waiting or not yet picked up can be assigned."})
    if _active_count(partner) >= policy.max_active_per_partner():
        raise ValidationError({"partner": "That partner already has the maximum number of active deliveries."})
    delivery.needs_attention = False
    delivery.save(update_fields=["needs_attention", "updated_at"])
    return _create_offer(delivery, partner, actor=actor, reason=reason or "Assigned by admin")


def _active_count(partner) -> int:
    return Delivery.objects.filter(partner=partner, status__in=[D.OFFERED, D.ACCEPTED, D.AT_STORE, D.IN_TRANSIT, D.ARRIVED]).count()


def _revoke_active(delivery, *, actor, reason):
    previous = DeliveryAssignment.objects.filter(delivery=delivery, status__in=[AssignmentStatus.OFFERED, AssignmentStatus.ACCEPTED])
    for assignment in previous:
        assignment.status = AssignmentStatus.REVOKED
        assignment.responded_at = timezone.now()
        assignment.reason = reason[:255]
        assignment.save(update_fields=["status", "responded_at", "reason"])
        notify(assignment.partner.user, Kind.DELIVERY_REJECTED, "Delivery reassigned", "This delivery was assigned elsewhere.", _data(delivery))
    delivery.partner = None
    delivery.save(update_fields=["partner", "updated_at"])


def _current_assignment(delivery, partner, statuses):
    return DeliveryAssignment.objects.filter(delivery=delivery, partner=partner, status__in=statuses).first()


def _require_partner(delivery: Delivery, partner: DeliveryPartner):
    if delivery.partner_id != partner.pk:
        raise PermissionDenied("This delivery is not assigned to you.")


@transaction.atomic
def accept_assignment(delivery_id, partner: DeliveryPartner) -> Delivery:
    delivery = _lock(delivery_id)
    _require_partner(delivery, partner)
    assignment = _current_assignment(delivery, partner, [AssignmentStatus.OFFERED])
    if assignment is None or delivery.status != D.OFFERED:
        raise ValidationError({"status": "This offer is no longer available."})
    if assignment.expires_at and assignment.expires_at < timezone.now():
        _expire(delivery, assignment)
        raise ValidationError({"status": "This offer has expired."})
    assignment.status = AssignmentStatus.ACCEPTED
    assignment.responded_at = timezone.now()
    assignment.save(update_fields=["status", "responded_at"])
    _move(delivery, "accept", actor=partner.user)
    delivery.assigned_at = timezone.now()
    delivery.save(update_fields=["assigned_at", "updated_at"])
    notify(_customer_user(delivery), Kind.DELIVERY_ASSIGNED, "A delivery partner is on the way to the store", "", _data(delivery))
    return delivery


@transaction.atomic
def reject_assignment(delivery_id, partner: DeliveryPartner, *, reason="") -> Delivery:
    delivery = _lock(delivery_id)
    _require_partner(delivery, partner)
    assignment = _current_assignment(delivery, partner, [AssignmentStatus.OFFERED, AssignmentStatus.ACCEPTED])
    if assignment is None or delivery.status not in (D.OFFERED, D.ACCEPTED, D.AT_STORE):
        raise ValidationError({"status": "There is no assignment to reject."})
    assignment.status = AssignmentStatus.REJECTED
    assignment.responded_at = timezone.now()
    assignment.reason = (reason or "")[:255]
    assignment.save(update_fields=["status", "responded_at", "reason"])
    _release(delivery, actor=partner.user, note=f"Rejected by partner. {reason}".strip())
    notify_many(_admin_users(), Kind.DELIVERY_REJECTED, "Delivery assignment rejected", reason or "", _data(delivery), email=False)
    transaction.on_commit(lambda: _auto_assign_after_commit(delivery.pk))
    return delivery


def _release(delivery, *, actor, note):
    delivery.partner = None
    delivery.rejection_count += 1
    delivery.save(update_fields=["partner", "rejection_count", "updated_at"])
    _move(delivery, "release", actor=actor, note=note)


def _expire(delivery, assignment):
    assignment.status = AssignmentStatus.EXPIRED
    assignment.responded_at = timezone.now()
    assignment.save(update_fields=["status", "responded_at"])
    _release(delivery, actor=None, note="Offer expired without a response")


def expire_stale_offers(now=None) -> int:
    """Time out unanswered offers and try the next partner. Run from a scheduler."""
    now = now or timezone.now()
    ids = list(DeliveryAssignment.objects.filter(status=AssignmentStatus.OFFERED, expires_at__lt=now).values_list("delivery_id", flat=True))
    count = 0
    for delivery_id in ids:
        with transaction.atomic():
            delivery = _lock(delivery_id)
            assignment = DeliveryAssignment.objects.filter(delivery=delivery, status=AssignmentStatus.OFFERED, expires_at__lt=now).first()
            if assignment is None or delivery.status != D.OFFERED:
                continue
            _expire(delivery, assignment)
            count += 1
        _auto_assign_after_commit(delivery_id)
    return count


def sweep_unassigned() -> int:
    """Re-run automatic assignment for queued deliveries (a partner may have come online)."""
    count = 0
    for delivery_id in Delivery.objects.filter(status=D.PENDING_ASSIGNMENT, needs_attention=False).values_list("pk", flat=True):
        with transaction.atomic():
            if auto_assign(delivery_id):
                count += 1
    return count


# ---------------------------------------------------------------- partner status updates

@transaction.atomic
def arrive_at_store(delivery_id, partner: DeliveryPartner) -> Delivery:
    delivery = _lock(delivery_id)
    _require_partner(delivery, partner)
    return _move(delivery, "arrive_store", actor=partner.user)


def _save_photos(evidence: DeliveryEvidence, uploads):
    uploads = list(uploads or [])
    if len(uploads) < policy.min_photos():
        raise ValidationError({"photos": f"At least {policy.min_photos()} photo is required as evidence."})
    if len(uploads) > policy.max_photos():
        raise ValidationError({"photos": f"At most {policy.max_photos()} photos can be uploaded."})
    cleaned = [clean_image(upload) for upload in uploads]  # validate every file before storing any
    for item in cleaned:
        photo = EvidencePhoto(evidence=evidence, content_type=item.content_type, size=item.size,
                              sha256=item.sha256, width=item.width, height=item.height)
        photo.file.save(f"{item.sha256[:24]}{_ext(item.content_type)}", item.file, save=False)
        photo.save()


def _ext(content_type):
    return {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}.get(content_type, ".bin")


def _evidence(delivery, kind, actor, lat, lon, accuracy, target, notes, **extra) -> DeliveryEvidence:
    distance = None
    if target and target[0] is not None:
        distance = haversine_m(lat, lon, target[0], target[1])
    within = None if distance is None else distance <= policy.location_tolerance_m()
    return DeliveryEvidence.objects.create(
        delivery=delivery, attempt_number=delivery.attempt_number, kind=kind, captured_by=actor,
        latitude=lat, longitude=lon, accuracy_m=accuracy, distance_from_target_m=distance,
        within_tolerance=within, notes=(notes or "")[:2000], **extra,
    )


@transaction.atomic
def confirm_pickup(delivery_id, partner: DeliveryPartner, *, photos, latitude, longitude, accuracy_m=None, notes="") -> Delivery:
    delivery = _lock(delivery_id)
    _require_partner(delivery, partner)
    if delivery.status not in (D.ACCEPTED, D.AT_STORE):
        raise ValidationError({"status": "Pickup can only be confirmed after you accept the delivery."})
    if delivery.store_order.status != StoreOrderStatus.READY:
        raise ValidationError({"status": "The store has not marked this order ready."})
    lat, lon = _coords(latitude, longitude)
    evidence = _evidence(delivery, EvidenceKind.PICKUP, partner.user, lat, lon, _accuracy(accuracy_m),
                         (delivery.pickup_latitude, delivery.pickup_longitude), notes)
    if policy.enforce_tolerance() and evidence.within_tolerance is False:
        raise ValidationError({"location": "You are too far from the store to confirm pickup."})
    _save_photos(evidence, photos)
    _move(delivery, "pickup", actor=partner.user)
    delivery.picked_up_at = timezone.now()
    delivery.save(update_fields=["picked_up_at", "updated_at"])
    DeliveryAssignment.objects.filter(delivery=delivery, partner=partner, status=AssignmentStatus.ACCEPTED).update(responded_at=timezone.now())
    _set_store_order_status(delivery.store_order, StoreOrderStatus.OUT_FOR_DELIVERY, actor=partner.user, reason="Picked up by delivery partner")
    customer = _customer_user(delivery)
    notify(customer, Kind.PICKUP_CONFIRMED, "Your order was picked up", "", _data(delivery))
    otp_note = f" Share code {delivery_otp(delivery)} with the partner on arrival." if policy.require_otp() else ""
    notify(customer, Kind.IN_TRANSIT, "Your order is on the way", f"{otp_note}".strip(), _data(delivery))
    return delivery


@transaction.atomic
def mark_arrived(delivery_id, partner: DeliveryPartner) -> Delivery:
    delivery = _lock(delivery_id)
    _require_partner(delivery, partner)
    return _move(delivery, "arrive_customer", actor=partner.user)


def delivery_otp(delivery: Delivery) -> str:
    digest = salted_hmac("zuvi.delivery.otp", f"{delivery.pk}:{delivery.otp_nonce}").hexdigest()
    return f"{int(digest[:12], 16) % 1_000_000:06d}"


@transaction.atomic
def complete_delivery(delivery_id, partner: DeliveryPartner, *, photos, latitude, longitude, accuracy_m=None,
                      notes="", recipient_name="", otp="") -> Delivery:
    delivery = _lock(delivery_id)
    _require_partner(delivery, partner)
    if delivery.status not in (D.IN_TRANSIT, D.ARRIVED):
        raise ValidationError({"status": "The order must be picked up before it can be delivered."})
    if policy.require_otp():
        _check_otp(delivery, otp)
    lat, lon = _coords(latitude, longitude)
    evidence = _evidence(delivery, EvidenceKind.DELIVERY, partner.user, lat, lon, _accuracy(accuracy_m),
                         (delivery.dropoff_latitude, delivery.dropoff_longitude), notes,
                         recipient_name=(recipient_name or "")[:150])
    if policy.enforce_tolerance() and evidence.within_tolerance is False:
        raise ValidationError({"location": "You are too far from the delivery address to complete delivery."})
    _save_photos(evidence, photos)
    now = timezone.now()
    _move(delivery, "deliver", actor=partner.user)
    delivery.delivered_at = now
    if policy.require_otp():
        delivery.otp_verified_at = now
    delivery.save(update_fields=["delivered_at", "otp_verified_at", "updated_at"])
    DeliveryAttempt.objects.filter(delivery=delivery, number=delivery.attempt_number).update(outcome=DeliveryAttempt.Outcome.DELIVERED, ended_at=now)
    DeliveryAssignment.objects.filter(delivery=delivery, partner=partner, status=AssignmentStatus.ACCEPTED).update(status=AssignmentStatus.COMPLETED)
    _set_store_order_status(delivery.store_order, StoreOrderStatus.COMPLETED, actor=partner.user, reason="Delivered with photo evidence")
    notify(_customer_user(delivery), Kind.DELIVERED, "Your order was delivered", "", _data(delivery))
    notify_many(_store_users(delivery.store_order), Kind.DELIVERED, "Order delivered", delivery.store_order.store_order_number, _data(delivery))
    return delivery


def _check_otp(delivery, otp):
    if delivery.otp_failed_attempts >= policy.max_otp_failures():
        raise ValidationError({"otp": "Too many wrong codes. Ask support to assist."})
    if not constant_time_compare(str(otp or "").strip(), delivery_otp(delivery)):
        raise OtpRejected({"otp": "The delivery code is incorrect."})


class OtpRejected(ValidationError):
    """Raised for a wrong OTP. Handled outside the atomic block so the failure counter is kept."""


def complete_delivery_checked(*args, **kwargs):
    """``complete_delivery`` but a wrong OTP still counts: the counter is bumped outside the rolled-back transaction."""
    try:
        return complete_delivery(*args, **kwargs)
    except OtpRejected as exc:
        delivery_id = args[0]
        # The failed request rolled back, so count the wrong code here, outside that transaction.
        Delivery.objects.filter(pk=delivery_id).update(otp_failed_attempts=F("otp_failed_attempts") + 1)
        raise ValidationError(exc.message_dict) from None


@transaction.atomic
def fail_delivery(delivery_id, partner: DeliveryPartner, *, reason, note="", latitude=None, longitude=None) -> Delivery:
    delivery = _lock(delivery_id)
    _require_partner(delivery, partner)
    if reason not in DeliveryAttempt.FailureReason.values:
        raise ValidationError({"reason": "Choose a valid failure reason."})
    if reason == DeliveryAttempt.FailureReason.OTHER and not (note or "").strip():
        raise ValidationError({"note": "Please describe what happened."})
    lat = lon = None
    if latitude not in (None, "") and longitude not in (None, ""):
        lat, lon = _coords(latitude, longitude)
    _move(delivery, "fail", actor=partner.user, note=reason)
    now = timezone.now()
    DeliveryAttempt.objects.filter(delivery=delivery, number=delivery.attempt_number).update(
        outcome=DeliveryAttempt.Outcome.FAILED, failure_reason=reason, failure_note=(note or "")[:2000],
        failure_latitude=lat, failure_longitude=lon, ended_at=now)
    DeliveryAssignment.objects.filter(delivery=delivery, partner=partner, status=AssignmentStatus.ACCEPTED).update(status=AssignmentStatus.COMPLETED)
    notify(_customer_user(delivery), Kind.DELIVERY_FAILED, "We could not deliver your order",
           dict(DeliveryAttempt.FailureReason.choices).get(reason, ""), _data(delivery))
    notify_many(_admin_users(), Kind.DELIVERY_FAILED, "Delivery attempt failed", delivery.store_order.store_order_number, _data(delivery), email=False)
    return delivery


@transaction.atomic
def retry_delivery(delivery_id, *, actor) -> Delivery:
    """Admin decision to try again after a failed attempt (a new attempt, new proof)."""
    delivery = _lock(delivery_id)
    if delivery.attempt_number >= policy.max_attempts():
        raise ValidationError({"status": f"The maximum of {policy.max_attempts()} delivery attempts has been reached."})
    _move(delivery, "retry", actor=actor, note="Retry approved")
    delivery.attempt_number += 1
    delivery.partner = None
    delivery.rejection_count = 0
    delivery.needs_attention = False
    delivery.otp_nonce = secrets.token_hex(8)
    delivery.otp_failed_attempts = 0
    delivery.save(update_fields=["attempt_number", "partner", "rejection_count", "needs_attention", "otp_nonce", "otp_failed_attempts", "updated_at"])
    DeliveryAttempt.objects.create(delivery=delivery, number=delivery.attempt_number)
    transaction.on_commit(lambda: _auto_assign_after_commit(delivery.pk))
    return delivery


@transaction.atomic
def cancel_delivery(delivery_id, *, actor=None, reason="") -> Delivery:
    delivery = _lock(delivery_id)
    _revoke_active(delivery, actor=actor, reason=reason or "Delivery cancelled")
    _move(delivery, "cancel", actor=actor, note=reason)
    DeliveryAttempt.objects.filter(delivery=delivery, outcome=DeliveryAttempt.Outcome.IN_PROGRESS).update(
        outcome=DeliveryAttempt.Outcome.CANCELLED, ended_at=timezone.now())
    return delivery


def cancel_for_store_order(store_order: StoreOrder, *, actor=None, reason=""):
    """Hook for order cancellation: stop a live delivery for a cancelled StoreOrder."""
    delivery = Delivery.objects.filter(store_order=store_order).exclude(status__in=[D.DELIVERED, D.CANCELLED]).first()
    if delivery:
        cancel_delivery(delivery.pk, actor=actor, reason=reason or "Order cancelled")


# ---------------------------------------------------------------- GPS tracking

TRACKABLE = (D.ACCEPTED, D.AT_STORE, D.IN_TRANSIT, D.ARRIVED)


class PingRejected(ValidationError):
    pass


@transaction.atomic
def record_location(delivery_id, partner: DeliveryPartner, *, latitude, longitude, accuracy_m=None, device_time=None) -> LocationPing:
    delivery = Delivery.objects.select_for_update().get(pk=delivery_id)
    _require_partner(delivery, partner)
    if delivery.status not in TRACKABLE:
        raise ValidationError({"status": "Location is only recorded while a delivery is in progress."})
    lat, lon = _coords(latitude, longitude)
    accuracy = _accuracy(accuracy_m)
    if accuracy is not None and accuracy > policy.max_ping_accuracy_m():
        raise ValidationError({"accuracy_m": "Location accuracy is too low to use."})
    now = timezone.now()
    last = LocationPing.objects.filter(delivery=delivery).order_by("-recorded_at", "-pk").first()
    if last and now - last.recorded_at < policy.min_ping_interval():
        raise ValidationError({"detail": "Location updates are too frequent."})
    ping = LocationPing.objects.create(delivery=delivery, partner=partner, latitude=lat, longitude=lon,
                                       accuracy_m=accuracy, device_time=device_time)
    DeliveryPartner.objects.filter(pk=partner.pk).update(last_latitude=lat, last_longitude=lon, last_accuracy_m=accuracy, last_location_at=now)
    return ping


def last_ping(delivery):
    return LocationPing.objects.filter(delivery=delivery).order_by("-recorded_at", "-pk").first()


def tracking_snapshot(delivery: Delivery, *, for_customer=False) -> dict:
    """What a customer/admin sees: status, last position and an honest staleness flag."""
    ping = last_ping(delivery) if delivery.status in TRACKABLE else None
    now = timezone.now()
    partner = delivery.partner
    data = {
        "delivery_id": delivery.pk,
        "status": delivery.status,
        "status_label": delivery.get_status_display(),
        "attempt_number": delivery.attempt_number,
        "partner": None,
        "location": None,
        "eta": delivery.eta_at,  # null unless a routing provider is configured
        "dropoff": None,
        "timeline": [
            {"status": h.new_status, "at": h.created_at, "note": h.note if not for_customer else ""}
            for h in delivery.status_history.all()
        ],
    }
    if partner and delivery.status in (D.ACCEPTED, D.AT_STORE, D.IN_TRANSIT, D.ARRIVED, D.DELIVERED):
        data["partner"] = {"first_name": partner.user.first_name, "vehicle_type": partner.vehicle_type}
    if ping:
        age = (now - ping.recorded_at).total_seconds()
        data["location"] = {
            "latitude": float(ping.latitude), "longitude": float(ping.longitude),
            "accuracy_m": ping.accuracy_m, "recorded_at": ping.recorded_at,
            "age_seconds": int(age), "is_stale": age > policy.stale_after().total_seconds(),
        }
    elif delivery.status in TRACKABLE:
        data["location"] = {"is_stale": True, "recorded_at": None, "age_seconds": None}
    if delivery.dropoff_latitude is not None:
        data["dropoff"] = {"latitude": float(delivery.dropoff_latitude), "longitude": float(delivery.dropoff_longitude)}
    if for_customer and policy.require_otp() and delivery.status in (D.IN_TRANSIT, D.ARRIVED):
        data["otp"] = delivery_otp(delivery)
    return data


# ---------------------------------------------------------------- store handover confirmation

@transaction.atomic
def store_confirm_pickup(delivery_id, *, store, user) -> DeliveryEvidence:
    delivery = _lock(delivery_id)
    if delivery.store_order.store_id != store.pk:
        raise PermissionDenied("This delivery belongs to another store.")
    evidence = delivery.evidence.filter(kind=EvidenceKind.PICKUP, attempt_number=delivery.attempt_number).order_by("-pk").first()
    if evidence is None:
        raise ValidationError({"status": "The delivery partner has not submitted pickup evidence yet."})
    if evidence.store_confirmed_at is None:
        evidence.store_confirmed_by = user
        evidence.store_confirmed_at = timezone.now()
        evidence.save(update_fields=["store_confirmed_by", "store_confirmed_at"])
    return evidence
