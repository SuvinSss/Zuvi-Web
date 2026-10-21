"""Support tickets and complaints: workflow rules live here, views stay thin."""
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.html import strip_tags

from accounts.models import Role, User
from core.audit import audit
from core.permissions import get_customer, get_delivery_partner, get_store_membership, is_management, is_support_staff, is_support_supervisor
from core.uploads import clean_document
from notifications.models import Kind
from notifications.services import notify, notify_many

from . import sla
from .models import (
    AgainstType, Complaint, ComplaintAttachment, ComplaintCategory, ComplaintEvent, ComplaintStatus, Priority,
    Ticket, TicketAttachment, TicketEvent, TicketMessage, TicketStatus,
)

MAX_ATTACHMENTS = 5
REOPEN_WINDOW = timedelta(days=7)


def clean(text, limit=5000):
    value = "".join(ch for ch in strip_tags(text or "") if ch == "\n" or ch >= " ").strip()
    return value[:limit]


def staff_users():
    return list(User.objects.filter(is_active=True, role__in=[Role.SUPPORT_AGENT, Role.SUPPORT_SUPERVISOR]))


def supervisors():
    return list(User.objects.filter(is_active=True).filter(Q(role=Role.SUPPORT_SUPERVISOR) | Q(role__in=[Role.ADMIN, Role.SUPER_ADMIN])))


def is_staff_user(user) -> bool:
    return is_support_staff(user) or is_management(user)


def can_work(user, obj) -> bool:
    """Support agents work what is assigned to them or still unassigned; supervisors/admins everything."""
    if is_support_supervisor(user):
        return True
    return is_support_staff(user) and obj.assigned_to_id in (None, user.pk)


def _data(ref_key, obj):
    return {ref_key: obj.pk, "reference": obj.reference}


# ------------------------------------------------------------------ attachments

def _store_attachments(model, uploads, *, owner_field, owner, uploaded_by, internal=False, **extra):
    uploads = list(uploads or [])
    if len(uploads) > MAX_ATTACHMENTS:
        raise ValidationError({"attachments": f"At most {MAX_ATTACHMENTS} files can be attached at once."})
    cleaned = [(upload, clean_document(upload)) for upload in uploads]  # validate all before storing any
    saved = []
    for upload, item in cleaned:
        attachment = model(uploaded_by=uploaded_by, content_type=item.content_type, size=item.size, sha256=item.sha256,
                           original_name=(getattr(upload, "name", "") or "")[-150:], is_internal=internal,
                           **{owner_field: owner}, **extra)
        ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "application/pdf": ".pdf"}.get(item.content_type, ".bin")
        attachment.file.save(f"{item.sha256[:24]}{ext}", item.file, save=False)
        attachment.save()
        saved.append(attachment)
    return saved


# ------------------------------------------------------------------ order references

def _may_reference_order(user, order) -> bool:
    customer = get_customer(user)
    if customer:
        return order.customer_id == customer.pk
    membership = get_store_membership(user)
    if membership:
        return order.store_orders.filter(store_id=membership.store_id).exists()
    partner = get_delivery_partner(user, approved_only=False)
    if partner:
        return order.store_orders.filter(delivery__partner=partner).exists()
    return is_management(user)


def _resolve_order(user, order_id):
    if not order_id:
        return None
    from orders.models import Order

    order = Order.objects.filter(pk=order_id).first()
    if order is None or not _may_reference_order(user, order):
        raise ValidationError({"order": "Choose one of your own orders."})
    return order


# ------------------------------------------------------------------ tickets

TICKET_STAFF_TRANSITIONS = {
    TicketStatus.OPEN: {TicketStatus.IN_PROGRESS, TicketStatus.WAITING_CUSTOMER, TicketStatus.RESOLVED},
    TicketStatus.IN_PROGRESS: {TicketStatus.WAITING_CUSTOMER, TicketStatus.RESOLVED},
    TicketStatus.WAITING_CUSTOMER: {TicketStatus.IN_PROGRESS, TicketStatus.RESOLVED},
    TicketStatus.RESOLVED: {TicketStatus.OPEN, TicketStatus.CLOSED},
    TicketStatus.CLOSED: set(),
}


def _ticket_event(ticket, actor, kind, detail="", internal=False):
    TicketEvent.objects.create(ticket=ticket, actor=actor, kind=kind, detail=detail[:255], is_internal=internal)


@transaction.atomic
def create_ticket(*, user, category, subject, description, order_id=None, attachments=None) -> Ticket:
    subject, description = clean(subject, 200), clean(description)
    if not subject or not description:
        raise ValidationError({"subject": "Please describe your problem."})
    order = _resolve_order(user, order_id)
    ticket = Ticket.objects.create(requester=user, category=category, subject=subject, description=description, order=order)
    # SLA clocks start at the stored creation time, so the targets are exact.
    ticket.first_response_due, ticket.resolution_due = sla.ticket_due(ticket.priority, ticket.created_at)
    ticket.save(update_fields=["first_response_due", "resolution_due"])
    _ticket_event(ticket, user, "CREATED")
    _store_attachments(TicketAttachment, attachments, owner_field="ticket", owner=ticket, uploaded_by=user)
    notify_many(supervisors(), Kind.TICKET_CREATED, f"New ticket {ticket.reference}", subject, _data("ticket_id", ticket), email=False)
    notify(user, Kind.TICKET_CREATED, f"We received your ticket {ticket.reference}", subject, _data("ticket_id", ticket))
    return ticket


def _locked_ticket(ticket_id):
    return Ticket.objects.select_for_update().select_related("requester", "assigned_to").get(pk=ticket_id)


@transaction.atomic
def add_ticket_message(ticket_id, *, author, body, internal=False, attachments=None) -> TicketMessage:
    ticket = _locked_ticket(ticket_id)
    body = clean(body)
    if not body:
        raise ValidationError({"body": "A message cannot be empty."})
    staff = is_staff_user(author)
    if not staff and ticket.requester_id != author.pk:
        raise PermissionDenied("You cannot reply to this ticket.")
    if internal and not staff:
        raise PermissionDenied("Only support staff can add private notes.")
    if ticket.status == TicketStatus.CLOSED:
        raise ValidationError({"status": "This ticket is closed. Open a new one if you still need help."})
    if staff and not can_work(author, ticket):
        raise PermissionDenied("This ticket is assigned to another agent.")
    message = TicketMessage.objects.create(ticket=ticket, author=author, body=body, is_internal=internal)
    _store_attachments(TicketAttachment, attachments, owner_field="ticket", owner=ticket, uploaded_by=author,
                       internal=internal, message=message)
    now = timezone.now()
    if staff and not internal:
        fields = []
        if ticket.first_responded_at is None:
            ticket.first_responded_at = now
            fields.append("first_responded_at")
        if ticket.assigned_to_id is None and is_support_staff(author):
            ticket.assigned_to = author
            fields.append("assigned_to")
        if ticket.status == TicketStatus.OPEN:
            ticket.status = TicketStatus.IN_PROGRESS
            fields.append("status")
        if fields:
            ticket.save(update_fields=fields + ["updated_at"])
        notify(ticket.requester, Kind.TICKET_REPLY, f"Reply on {ticket.reference}", body[:200], _data("ticket_id", ticket))
    elif not staff:
        if ticket.status in (TicketStatus.WAITING_CUSTOMER, TicketStatus.RESOLVED):
            old = ticket.status
            ticket.status = TicketStatus.IN_PROGRESS if old == TicketStatus.WAITING_CUSTOMER else TicketStatus.OPEN
            ticket.resolved_at = None
            ticket.save(update_fields=["status", "resolved_at", "updated_at"])
            _ticket_event(ticket, author, "STATUS", f"{old} -> {ticket.status} (requester replied)")
        notify_many([ticket.assigned_to] if ticket.assigned_to else supervisors(), Kind.TICKET_REPLY,
                    f"Reply on {ticket.reference}", body[:200], _data("ticket_id", ticket), email=False)
    return message


@transaction.atomic
def assign_ticket(ticket_id, *, actor, assignee) -> Ticket:
    ticket = _locked_ticket(ticket_id)
    if not is_staff_user(actor):
        raise PermissionDenied("Only support staff can assign tickets.")
    if assignee.role not in (Role.SUPPORT_AGENT, Role.SUPPORT_SUPERVISOR) or not assignee.is_active:
        raise ValidationError({"assignee": "Choose an active support agent."})
    if not is_support_supervisor(actor):
        # Agents may only claim an unassigned ticket for themselves.
        if assignee.pk != actor.pk or ticket.assigned_to_id not in (None, actor.pk):
            raise PermissionDenied("Only supervisors can assign tickets to other agents.")
    if ticket.status == TicketStatus.CLOSED:
        raise ValidationError({"status": "Closed tickets cannot be assigned."})
    ticket.assigned_to = assignee
    ticket.save(update_fields=["assigned_to", "updated_at"])
    _ticket_event(ticket, actor, "ASSIGNED", f"Assigned to {assignee.get_username()}", internal=True)
    audit(actor, "ticket.assign", ticket, summary=assignee.get_username())
    if assignee.pk != actor.pk:
        notify(assignee, Kind.TICKET_ASSIGNED, f"Ticket {ticket.reference} assigned to you", ticket.subject, _data("ticket_id", ticket))
    return ticket


@transaction.atomic
def change_ticket_status(ticket_id, *, actor, new_status, note="") -> Ticket:
    ticket = _locked_ticket(ticket_id)
    old = ticket.status
    if new_status not in TicketStatus.values:
        raise ValidationError({"status": "Unknown status."})
    if is_staff_user(actor):
        if not can_work(actor, ticket):
            raise PermissionDenied("This ticket is assigned to another agent.")
        allowed = set(TICKET_STAFF_TRANSITIONS[old])
        if is_support_supervisor(actor):
            allowed |= {TicketStatus.CLOSED} if old != TicketStatus.CLOSED else {TicketStatus.OPEN}
    elif ticket.requester_id == actor.pk:
        allowed = {TicketStatus.CLOSED} if old != TicketStatus.CLOSED else set()  # requester may close their own ticket
        if old == TicketStatus.RESOLVED and ticket.resolved_at and timezone.now() - ticket.resolved_at <= REOPEN_WINDOW:
            allowed.add(TicketStatus.OPEN)
    else:
        raise PermissionDenied("You cannot change this ticket.")
    if new_status not in allowed:
        raise ValidationError({"status": f"A {old.lower().replace('_', ' ')} ticket cannot move to {new_status.lower().replace('_', ' ')}."})
    now = timezone.now()
    ticket.status = new_status
    fields = ["status", "updated_at"]
    if new_status == TicketStatus.RESOLVED:
        ticket.resolved_at = now
        fields.append("resolved_at")
    elif new_status == TicketStatus.CLOSED:
        ticket.closed_at = now
        fields.append("closed_at")
    elif new_status == TicketStatus.OPEN:
        ticket.resolved_at = ticket.closed_at = None
        fields += ["resolved_at", "closed_at"]
    ticket.save(update_fields=fields)
    _ticket_event(ticket, actor, "STATUS", f"{old} -> {new_status}. {clean(note, 150)}".strip())
    if is_staff_user(actor):
        audit(actor, "ticket.status", ticket, summary=f"{old} -> {new_status}")
        notify(ticket.requester, Kind.TICKET_STATUS, f"{ticket.reference} is now {new_status.lower().replace('_', ' ')}", clean(note, 200), _data("ticket_id", ticket))
    return ticket


@transaction.atomic
def change_ticket_priority(ticket_id, *, actor, priority) -> Ticket:
    ticket = _locked_ticket(ticket_id)
    if not is_staff_user(actor) or not can_work(actor, ticket):
        raise PermissionDenied("Only the assigned support staff can change priority.")
    if priority not in Priority.values:
        raise ValidationError({"priority": "Unknown priority."})
    first, resolve = sla.ticket_due(priority, ticket.created_at)
    old = ticket.priority
    ticket.priority, ticket.first_response_due, ticket.resolution_due = priority, first, resolve
    ticket.sla_notices = []
    ticket.save(update_fields=["priority", "first_response_due", "resolution_due", "sla_notices", "updated_at"])
    _ticket_event(ticket, actor, "PRIORITY", f"{old} -> {priority}", internal=True)
    audit(actor, "ticket.priority", ticket, summary=f"{old} -> {priority}")
    return ticket


@transaction.atomic
def escalate_ticket(ticket_id, *, actor, reason) -> Ticket:
    ticket = _locked_ticket(ticket_id)
    if not is_staff_user(actor) or not can_work(actor, ticket):
        raise PermissionDenied("Only the assigned support staff can escalate.")
    reason = clean(reason, 255)
    if not reason:
        raise ValidationError({"reason": "Say why this ticket is being escalated."})
    if ticket.escalated:
        raise ValidationError({"detail": "This ticket is already escalated."})
    ticket.escalated, ticket.escalated_at = True, timezone.now()
    fields = ["escalated", "escalated_at", "updated_at"]
    if ticket.priority in (Priority.LOW, Priority.NORMAL):
        ticket.priority = Priority.HIGH
        ticket.first_response_due, ticket.resolution_due = sla.ticket_due(Priority.HIGH, ticket.created_at)
        fields += ["priority", "first_response_due", "resolution_due"]
    ticket.save(update_fields=fields)
    _ticket_event(ticket, actor, "ESCALATED", reason, internal=True)
    audit(actor, "ticket.escalate", ticket, summary=reason)
    notify_many(supervisors(), Kind.TICKET_ASSIGNED, f"Ticket {ticket.reference} escalated", reason, _data("ticket_id", ticket))
    return ticket


def ticket_sla(ticket, now=None):
    return {
        "first_response": sla.state(ticket.first_response_due, ticket.first_responded_at, start=ticket.created_at, now=now),
        "resolution": sla.state(ticket.resolution_due, ticket.resolved_at or ticket.closed_at, start=ticket.created_at, now=now),
    }


# ------------------------------------------------------------------ complaints

HIGH_SEVERITY = {ComplaintCategory.QUALITY, ComplaintCategory.NOT_DELIVERED, ComplaintCategory.BEHAVIOUR}


def _cevent(complaint, actor, kind, body="", *, internal=False, from_status="", to_status=""):
    return ComplaintEvent.objects.create(complaint=complaint, actor=actor, kind=kind, body=clean(body), is_internal=internal,
                                         from_status=from_status, to_status=to_status)


def _locked_complaint(complaint_id):
    return Complaint.objects.select_for_update().select_related("complainant", "assigned_to").get(pk=complaint_id)


@transaction.atomic
def submit_complaint(*, user, against_type, category, description, order_id=None, store_id=None, partner_id=None,
                     product_id=None, desired_resolution="", attachments=None) -> Complaint:
    from catalog.models import Product
    from deliveries.models import DeliveryPartner
    from stores.models import Store

    description = clean(description)
    if len(description) < 10:
        raise ValidationError({"description": "Please describe what happened (at least 10 characters)."})
    if against_type not in AgainstType.values or category not in ComplaintCategory.values:
        raise ValidationError({"detail": "Choose a valid complaint type and category."})
    order = _resolve_order(user, order_id)
    kwargs = {}
    if against_type != AgainstType.PLATFORM:
        if order is None or get_customer(user) is None:
            raise ValidationError({"order": "Complaints about a store, product or delivery partner must refer to one of your orders."})
        if against_type == AgainstType.STORE:
            store = Store.objects.filter(pk=store_id).first()
            if store is None or not order.store_orders.filter(store=store).exists():
                raise ValidationError({"store": "That store is not part of this order."})
            kwargs["store"] = store
        elif against_type == AgainstType.DELIVERY_PARTNER:
            partner = DeliveryPartner.objects.filter(pk=partner_id).first()
            if partner is None or not order.store_orders.filter(delivery__partner=partner).exists():
                raise ValidationError({"partner": "That delivery partner did not handle this order."})
            kwargs["partner"] = partner
        else:
            product = Product.objects.filter(pk=product_id).first()
            if product is None or not order.store_orders.filter(items__product=product).exists():
                raise ValidationError({"product": "That product is not part of this order."})
            kwargs["product"] = product
    severity = Priority.HIGH if category in HIGH_SEVERITY else Priority.NORMAL
    complaint = Complaint.objects.create(
        complainant=user, against_type=against_type, category=category, severity=severity, description=description,
        desired_resolution=clean(desired_resolution, 255), order=order, **kwargs)
    complaint.acknowledge_due, complaint.resolution_due = sla.complaint_due(severity, complaint.created_at)
    complaint.save(update_fields=["acknowledge_due", "resolution_due"])
    event = _cevent(complaint, user, ComplaintEvent.Kind.SUBMITTED, description, to_status=complaint.status)
    _store_attachments(ComplaintAttachment, attachments, owner_field="complaint", owner=complaint, uploaded_by=user, event=event)
    notify(user, Kind.COMPLAINT_SUBMITTED, f"Complaint {complaint.reference} received", "We will review it and keep you updated.", _data("complaint_id", complaint))
    notify_many(supervisors(), Kind.COMPLAINT_SUBMITTED, f"New complaint {complaint.reference}", category, _data("complaint_id", complaint), email=False)
    return complaint


def _require_staff_on(actor, complaint):
    if not is_staff_user(actor):
        raise PermissionDenied("Only support staff can do this.")
    if not can_work(actor, complaint):
        raise PermissionDenied("This complaint is assigned to another agent.")


def _acknowledge(complaint):
    if complaint.acknowledged_at is None:
        complaint.acknowledged_at = timezone.now()
        return ["acknowledged_at"]
    return []


@transaction.atomic
def assign_complaint(complaint_id, *, actor, assignee) -> Complaint:
    complaint = _locked_complaint(complaint_id)
    if not is_staff_user(actor):
        raise PermissionDenied("Only support staff can assign complaints.")
    if assignee.role not in (Role.SUPPORT_AGENT, Role.SUPPORT_SUPERVISOR) or not assignee.is_active:
        raise ValidationError({"assignee": "Choose an active support agent."})
    if not is_support_supervisor(actor) and (assignee.pk != actor.pk or complaint.assigned_to_id not in (None, actor.pk)):
        raise PermissionDenied("Only supervisors can assign complaints to other agents.")
    if complaint.status in (ComplaintStatus.CLOSED, ComplaintStatus.REJECTED, ComplaintStatus.RESOLVED):
        raise ValidationError({"status": "This complaint is already finished."})
    old = complaint.status
    complaint.assigned_to = assignee
    fields = ["assigned_to", "updated_at"] + _acknowledge(complaint)
    if old == ComplaintStatus.SUBMITTED:
        complaint.status = ComplaintStatus.UNDER_REVIEW
        fields.append("status")
    complaint.save(update_fields=fields)
    _cevent(complaint, actor, ComplaintEvent.Kind.ASSIGNED, f"Assigned to {assignee.get_username()}", internal=True)
    if old != complaint.status:
        _cevent(complaint, actor, ComplaintEvent.Kind.STATUS, from_status=old, to_status=complaint.status)
        notify(complaint.complainant, Kind.COMPLAINT_ASSIGNED, f"{complaint.reference} is being reviewed", "", _data("complaint_id", complaint))
    audit(actor, "complaint.assign", complaint, summary=assignee.get_username())
    if assignee.pk != actor.pk:
        notify(assignee, Kind.COMPLAINT_ASSIGNED, f"Complaint {complaint.reference} assigned to you", "", _data("complaint_id", complaint))
    return complaint


@transaction.atomic
def comment_on_complaint(complaint_id, *, actor, body, internal=False, attachments=None) -> ComplaintEvent:
    complaint = _locked_complaint(complaint_id)
    body = clean(body)
    if not body:
        raise ValidationError({"body": "A comment cannot be empty."})
    staff = is_staff_user(actor)
    if not staff and complaint.complainant_id != actor.pk:
        raise PermissionDenied("You cannot comment on this complaint.")
    if internal and not staff:
        raise PermissionDenied("Only support staff can add private notes.")
    if complaint.status == ComplaintStatus.CLOSED:
        raise ValidationError({"status": "This complaint is closed."})
    if staff:
        _require_staff_on(actor, complaint)
    if internal:
        kind = ComplaintEvent.Kind.NOTE
    elif staff:
        kind = ComplaintEvent.Kind.COMMENT
    else:
        kind = ComplaintEvent.Kind.INFO_RESPONSE if complaint.status == ComplaintStatus.INFO_REQUESTED else ComplaintEvent.Kind.COMMENT
    event = _cevent(complaint, actor, kind, body, internal=internal)
    _store_attachments(ComplaintAttachment, attachments, owner_field="complaint", owner=complaint, uploaded_by=actor,
                       internal=internal, event=event)
    if staff and not internal:
        fields = _acknowledge(complaint)
        if fields:
            complaint.save(update_fields=fields + ["updated_at"])
        notify(complaint.complainant, Kind.COMPLAINT_REPLY, f"Update on {complaint.reference}", body[:200], _data("complaint_id", complaint))
    elif not staff:
        if complaint.status == ComplaintStatus.INFO_REQUESTED:
            complaint.status = ComplaintStatus.UNDER_REVIEW
            complaint.save(update_fields=["status", "updated_at"])
            _cevent(complaint, actor, ComplaintEvent.Kind.STATUS, from_status=ComplaintStatus.INFO_REQUESTED, to_status=ComplaintStatus.UNDER_REVIEW)
        notify_many([complaint.assigned_to] if complaint.assigned_to else supervisors(), Kind.COMPLAINT_REPLY,
                    f"Reply on {complaint.reference}", body[:200], _data("complaint_id", complaint), email=False)
    return event


@transaction.atomic
def request_complaint_info(complaint_id, *, actor, message) -> Complaint:
    complaint = _locked_complaint(complaint_id)
    _require_staff_on(actor, complaint)
    message = clean(message)
    if not message:
        raise ValidationError({"message": "Say what information you need."})
    if complaint.status not in (ComplaintStatus.UNDER_REVIEW, ComplaintStatus.SUBMITTED, ComplaintStatus.ESCALATED):
        raise ValidationError({"status": "Information can only be requested on an open complaint."})
    old = complaint.status
    complaint.status = ComplaintStatus.INFO_REQUESTED
    complaint.save(update_fields=["status", "updated_at"] + _acknowledge(complaint))
    _cevent(complaint, actor, ComplaintEvent.Kind.INFO_REQUEST, message, from_status=old, to_status=complaint.status)
    notify(complaint.complainant, Kind.COMPLAINT_INFO_REQUESTED, f"More information needed for {complaint.reference}", message[:200], _data("complaint_id", complaint))
    return complaint


@transaction.atomic
def escalate_complaint(complaint_id, *, actor, reason) -> Complaint:
    complaint = _locked_complaint(complaint_id)
    _require_staff_on(actor, complaint)
    reason = clean(reason, 255)
    if not reason:
        raise ValidationError({"reason": "Say why this complaint is being escalated."})
    if complaint.status in (ComplaintStatus.ESCALATED, ComplaintStatus.RESOLVED, ComplaintStatus.REJECTED, ComplaintStatus.CLOSED):
        raise ValidationError({"status": "This complaint cannot be escalated right now."})
    old = complaint.status
    complaint.status, complaint.escalation_reason = ComplaintStatus.ESCALATED, reason
    complaint.save(update_fields=["status", "escalation_reason", "updated_at"] + _acknowledge(complaint))
    _cevent(complaint, actor, ComplaintEvent.Kind.ESCALATED, reason, internal=True, from_status=old, to_status=complaint.status)
    audit(actor, "complaint.escalate", complaint, summary=reason)
    notify_many(supervisors(), Kind.COMPLAINT_ESCALATED, f"Complaint {complaint.reference} escalated", reason, _data("complaint_id", complaint))
    notify(complaint.complainant, Kind.COMPLAINT_STATUS, f"{complaint.reference} was escalated to a supervisor", "", _data("complaint_id", complaint))
    return complaint


@transaction.atomic
def take_over_complaint(complaint_id, *, actor) -> Complaint:
    """A supervisor picks up an escalated complaint."""
    complaint = _locked_complaint(complaint_id)
    if not is_support_supervisor(actor):
        raise PermissionDenied("Only supervisors can take over escalated complaints.")
    if complaint.status != ComplaintStatus.ESCALATED:
        raise ValidationError({"status": "Only escalated complaints can be taken over."})
    complaint.assigned_to, complaint.escalated_to = actor, actor
    complaint.status = ComplaintStatus.UNDER_REVIEW
    complaint.save(update_fields=["assigned_to", "escalated_to", "status", "updated_at"])
    _cevent(complaint, actor, ComplaintEvent.Kind.ASSIGNED, "Supervisor took over", internal=True)
    _cevent(complaint, actor, ComplaintEvent.Kind.STATUS, from_status=ComplaintStatus.ESCALATED, to_status=complaint.status)
    audit(actor, "complaint.take_over", complaint)
    return complaint


@transaction.atomic
def resolve_complaint(complaint_id, *, actor, resolution) -> Complaint:
    complaint = _locked_complaint(complaint_id)
    _require_staff_on(actor, complaint)
    resolution = clean(resolution)
    if not resolution:
        raise ValidationError({"resolution": "Explain how the complaint was resolved."})
    if complaint.status == ComplaintStatus.ESCALATED and not is_support_supervisor(actor):
        raise PermissionDenied("Escalated complaints can only be resolved by a supervisor.")
    if complaint.status not in (ComplaintStatus.UNDER_REVIEW, ComplaintStatus.ESCALATED, ComplaintStatus.INFO_REQUESTED):
        raise ValidationError({"status": "This complaint cannot be resolved from its current status."})
    old = complaint.status
    complaint.status, complaint.resolution, complaint.resolved_at = ComplaintStatus.RESOLVED, resolution, timezone.now()
    complaint.save(update_fields=["status", "resolution", "resolved_at", "updated_at"] + _acknowledge(complaint))
    _cevent(complaint, actor, ComplaintEvent.Kind.RESOLUTION, resolution, from_status=old, to_status=complaint.status)
    audit(actor, "complaint.resolve", complaint)
    notify(complaint.complainant, Kind.COMPLAINT_RESOLVED, f"{complaint.reference} was resolved", resolution[:200], _data("complaint_id", complaint))
    return complaint


@transaction.atomic
def reject_complaint(complaint_id, *, actor, reason) -> Complaint:
    complaint = _locked_complaint(complaint_id)
    if not is_support_supervisor(actor):
        raise PermissionDenied("Only supervisors can reject complaints.")
    reason = clean(reason)
    if not reason:
        raise ValidationError({"reason": "A reason is required to reject a complaint."})
    if complaint.status in (ComplaintStatus.RESOLVED, ComplaintStatus.REJECTED, ComplaintStatus.CLOSED):
        raise ValidationError({"status": "This complaint is already finished."})
    old = complaint.status
    complaint.status, complaint.resolution, complaint.resolved_at = ComplaintStatus.REJECTED, reason, timezone.now()
    complaint.save(update_fields=["status", "resolution", "resolved_at", "updated_at"] + _acknowledge(complaint))
    _cevent(complaint, actor, ComplaintEvent.Kind.RESOLUTION, reason, from_status=old, to_status=complaint.status)
    audit(actor, "complaint.reject", complaint, summary=reason[:200])
    notify(complaint.complainant, Kind.COMPLAINT_STATUS, f"{complaint.reference} was not upheld", reason[:200], _data("complaint_id", complaint))
    return complaint


@transaction.atomic
def close_complaint(complaint_id, *, actor) -> Complaint:
    complaint = _locked_complaint(complaint_id)
    if complaint.status == ComplaintStatus.CLOSED:
        raise ValidationError({"status": "This complaint is already closed."})
    owner = complaint.complainant_id == actor.pk
    if not (owner or is_support_supervisor(actor)):
        raise PermissionDenied("Only the complainant or a supervisor can close a complaint.")
    old = complaint.status
    complaint.status, complaint.closed_at = ComplaintStatus.CLOSED, timezone.now()
    complaint.save(update_fields=["status", "closed_at", "updated_at"])
    _cevent(complaint, actor, ComplaintEvent.Kind.STATUS, "Withdrawn by complainant" if owner and old not in (ComplaintStatus.RESOLVED, ComplaintStatus.REJECTED) else "", from_status=old, to_status=complaint.status)
    return complaint


@transaction.atomic
def reopen_complaint(complaint_id, *, actor, reason) -> Complaint:
    complaint = _locked_complaint(complaint_id)
    reason = clean(reason)
    if not reason:
        raise ValidationError({"reason": "Say why the complaint should be reopened."})
    owner = complaint.complainant_id == actor.pk
    if complaint.status not in (ComplaintStatus.RESOLVED, ComplaintStatus.REJECTED, ComplaintStatus.CLOSED):
        raise ValidationError({"status": "Only a finished complaint can be reopened."})
    if owner and not is_support_supervisor(actor):
        finished = complaint.closed_at or complaint.resolved_at
        if complaint.status == ComplaintStatus.CLOSED and complaint.resolved_at is None:
            raise PermissionDenied("A withdrawn complaint cannot be reopened. Please submit a new one.")
        if finished and timezone.now() - finished > REOPEN_WINDOW:
            raise ValidationError({"status": f"Complaints can be reopened for {REOPEN_WINDOW.days} days after they are resolved."})
    elif not is_support_supervisor(actor):
        raise PermissionDenied("You cannot reopen this complaint.")
    old = complaint.status
    complaint.status, complaint.resolved_at, complaint.closed_at = ComplaintStatus.UNDER_REVIEW, None, None
    complaint.save(update_fields=["status", "resolved_at", "closed_at", "updated_at"])
    _cevent(complaint, actor, ComplaintEvent.Kind.REOPENED, reason, from_status=old, to_status=complaint.status)
    audit(actor, "complaint.reopen", complaint, summary=reason[:200])
    notify_many([complaint.assigned_to] if complaint.assigned_to else supervisors(), Kind.COMPLAINT_STATUS,
                f"Complaint {complaint.reference} reopened", reason[:200], _data("complaint_id", complaint))
    return complaint


def complaint_sla(complaint, now=None):
    return {
        "acknowledgement": sla.state(complaint.acknowledge_due, complaint.acknowledged_at, start=complaint.created_at, now=now),
        "resolution": sla.state(complaint.resolution_due, complaint.resolved_at or complaint.closed_at, start=complaint.created_at, now=now),
    }


# ------------------------------------------------------------------ SLA reminders

def send_sla_reminders(now=None) -> dict:
    """Notify about due-soon and breached targets, once per target. Run from a scheduler (see docs)."""
    now = now or timezone.now()
    sent = {"due_soon": 0, "breached": 0}
    open_tickets = Ticket.objects.exclude(status__in=[TicketStatus.RESOLVED, TicketStatus.CLOSED]).select_related("assigned_to")
    for ticket in open_tickets:
        for key, label in (("first_response", "first response"), ("resolution", "resolution")):
            state = ticket_sla(ticket, now)[key]
            if state not in ("due_soon", "breached") or f"{key}:{state}" in ticket.sla_notices:
                continue
            recipients = [ticket.assigned_to] if ticket.assigned_to else supervisors()
            if state == "breached":
                recipients = list({u.pk: u for u in recipients + supervisors()}.values())
            notify_many(recipients, Kind.TICKET_STATUS, f"Ticket {ticket.reference}: {label} SLA {state.replace('_', ' ')}", ticket.subject,
                        _data("ticket_id", ticket), email=False)
            ticket.sla_notices = ticket.sla_notices + [f"{key}:{state}"]
            Ticket.objects.filter(pk=ticket.pk).update(sla_notices=ticket.sla_notices)
            sent[state] += 1
    open_complaints = Complaint.objects.exclude(status__in=[ComplaintStatus.RESOLVED, ComplaintStatus.REJECTED, ComplaintStatus.CLOSED]).select_related("assigned_to")
    for complaint in open_complaints:
        for key, label in (("acknowledgement", "acknowledgement"), ("resolution", "resolution")):
            state = complaint_sla(complaint, now)[key]
            if state not in ("due_soon", "breached") or f"{key}:{state}" in complaint.sla_notices:
                continue
            recipients = [complaint.assigned_to] if complaint.assigned_to else supervisors()
            if state == "breached":
                recipients = list({u.pk: u for u in recipients + supervisors()}.values())
            notify_many(recipients, Kind.COMPLAINT_STATUS, f"Complaint {complaint.reference}: {label} SLA {state.replace('_', ' ')}", "",
                        _data("complaint_id", complaint), email=False)
            complaint.sla_notices = complaint.sla_notices + [f"{key}:{state}"]
            Complaint.objects.filter(pk=complaint.pk).update(sla_notices=complaint.sla_notices)
            sent[state] += 1
    return sent
