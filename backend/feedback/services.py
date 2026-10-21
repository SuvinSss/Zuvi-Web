from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from core.audit import audit
from core.permissions import get_customer, is_management, is_support_staff, is_support_supervisor
from notifications.models import Kind
from notifications.services import notify, notify_many
from support import services as support_services
from support.models import TicketCategory

from .models import Feedback, FeedbackKind, FeedbackReply, FeedbackStatus, FeedbackSubject


def _staff(user) -> bool:
    return is_support_staff(user) or is_management(user)


@transaction.atomic
def submit_feedback(*, user, kind, subject_type, message, store_id=None, order_id=None) -> Feedback:
    from orders.models import Order
    from stores.models import Store

    message = support_services.clean(message, 3000)
    if len(message) < 5:
        raise ValidationError({"message": "Please write a little more."})
    if kind not in FeedbackKind.values or subject_type not in FeedbackSubject.values:
        raise ValidationError({"detail": "Choose a valid feedback type and subject."})
    store = order = None
    if order_id:
        customer = get_customer(user)
        order = Order.objects.filter(pk=order_id, customer=customer).first() if customer else None
        if order is None:
            raise ValidationError({"order": "Choose one of your own orders."})
    if subject_type == FeedbackSubject.STORE:
        store = Store.objects.filter(pk=store_id, is_active=True).first()
        if store is None:
            raise ValidationError({"store": "Choose a store."})
        if order is not None and not order.store_orders.filter(store=store).exists():
            raise ValidationError({"store": "That store is not part of this order."})
    feedback = Feedback.objects.create(author=user, kind=kind, subject_type=subject_type, message=message, store=store, order=order)
    notify_many(support_services.supervisors(), Kind.FEEDBACK_RECEIVED, f"New feedback {feedback.reference}", message[:150], {"feedback_id": feedback.pk}, email=False)
    if store is not None:
        from stores.models import StoreUser

        owners = [m.user for m in StoreUser.objects.filter(store=store, is_active=True).select_related("user")]
        notify_many(owners, Kind.FEEDBACK_RECEIVED, "New customer feedback", message[:150], {"feedback_id": feedback.pk}, email=False)
    return feedback


@transaction.atomic
def reply(feedback_id, *, author, body, internal=False) -> FeedbackReply:
    feedback = Feedback.objects.select_for_update(of=("self",)).select_related("author").get(pk=feedback_id)
    body = support_services.clean(body, 3000)
    if not body:
        raise ValidationError({"body": "A reply cannot be empty."})
    staff = _staff(author)
    if not staff and feedback.author_id != author.pk:
        raise PermissionDenied("You cannot reply to this feedback.")
    if internal and not staff:
        raise PermissionDenied("Only support staff can add private notes.")
    if feedback.status == FeedbackStatus.CLOSED:
        raise ValidationError({"status": "This feedback is closed."})
    row = FeedbackReply.objects.create(feedback=feedback, author=author, body=body, is_internal=internal)
    if staff and not internal:
        if feedback.status in (FeedbackStatus.NEW, FeedbackStatus.IN_REVIEW):
            feedback.status = FeedbackStatus.REPLIED
            feedback.save(update_fields=["status", "updated_at"])
        notify(feedback.author, Kind.FEEDBACK_REPLY, f"Reply to your feedback {feedback.reference}", body[:200], {"feedback_id": feedback.pk})
    elif not staff:
        if feedback.status == FeedbackStatus.REPLIED:
            feedback.status = FeedbackStatus.IN_REVIEW
            feedback.save(update_fields=["status", "updated_at"])
        notify_many([feedback.assigned_to] if feedback.assigned_to else support_services.supervisors(), Kind.FEEDBACK_RECEIVED,
                    f"Follow-up on {feedback.reference}", body[:150], {"feedback_id": feedback.pk}, email=False)
    return row


@transaction.atomic
def set_status(feedback_id, *, actor, status) -> Feedback:
    if not _staff(actor):
        raise PermissionDenied("Only support staff can change feedback status.")
    if status not in (FeedbackStatus.IN_REVIEW, FeedbackStatus.CLOSED, FeedbackStatus.REPLIED):
        raise ValidationError({"status": "Choose in review, replied or closed."})
    feedback = Feedback.objects.select_for_update().get(pk=feedback_id)
    if feedback.status == FeedbackStatus.ESCALATED:
        raise ValidationError({"status": "Escalated feedback is handled through its support ticket."})
    feedback.status = status
    if feedback.assigned_to_id is None and is_support_staff(actor):
        feedback.assigned_to = actor
    feedback.save()
    audit(actor, "feedback.status", feedback, summary=status)
    return feedback


@transaction.atomic
def escalate_to_ticket(feedback_id, *, actor) -> Feedback:
    """Turn feedback that needs real follow-up into a support ticket for its author."""
    if not _staff(actor):
        raise PermissionDenied("Only support staff can escalate feedback.")
    feedback = Feedback.objects.select_for_update(of=("self",)).select_related("author").get(pk=feedback_id)
    if feedback.ticket_id:
        raise ValidationError({"detail": "This feedback has already been escalated."})
    from support.models import Ticket, TicketEvent

    ticket = support_services.create_ticket(user=feedback.author, category=TicketCategory.OTHER,
                                           subject=f"Feedback {feedback.reference}: {feedback.get_kind_display()}",
                                           description=feedback.message, order_id=feedback.order_id)
    if is_support_staff(actor) or is_support_supervisor(actor):
        Ticket.objects.filter(pk=ticket.pk).update(assigned_to=actor)
    TicketEvent.objects.create(ticket=ticket, actor=actor, kind="ESCALATED_FROM_FEEDBACK", detail=feedback.reference, is_internal=True)
    feedback.ticket, feedback.status = ticket, FeedbackStatus.ESCALATED
    feedback.save(update_fields=["ticket", "status", "updated_at"])
    audit(actor, "feedback.escalate", feedback, summary=ticket.reference)
    return feedback
