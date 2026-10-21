from datetime import timedelta

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Avg, Count
from django.utils import timezone
from django.utils.html import strip_tags

from core.audit import audit
from notifications.models import Kind
from notifications.services import notify, notify_many
from orders.models import StoreOrderStatus

from .models import RatingAggregate, Review, ReviewReply, ReviewReport, ReviewStatus, TargetType


def edit_window() -> timedelta:
    return timedelta(days=getattr(settings, "REVIEW_EDIT_WINDOW_DAYS", 7))


def clean_text(value: str, limit: int) -> str:
    # Reviews are rendered by clients; strip markup and control characters at the door too.
    text = strip_tags(value or "")
    text = "".join(ch for ch in text if ch == "\n" or ch >= " ")
    return text.strip()[:limit]


def _validate_rating(rating):
    try:
        rating = int(rating)
    except (TypeError, ValueError):
        raise ValidationError({"rating": "Rating must be a whole number from 1 to 5."}) from None
    if not 1 <= rating <= 5:
        raise ValidationError({"rating": "Rating must be a whole number from 1 to 5."})
    return rating


def recompute_aggregate(target_type, target_id):
    field = {TargetType.STORE: "store_id", TargetType.PRODUCT: "product_id", TargetType.DELIVERY_PARTNER: "partner_id"}[target_type]
    published = Review.objects.filter(status=ReviewStatus.PUBLISHED, target_type=target_type, **{field: target_id})
    stats = published.aggregate(count=Count("pk"), average=Avg("rating"))
    buckets = {str(i): 0 for i in range(1, 6)}
    for row in published.values("rating").annotate(n=Count("pk")):
        buckets[str(row["rating"])] = row["n"]
    count = stats["count"] or 0
    total = sum(int(k) * v for k, v in buckets.items())
    average = round(total / count, 2) if count else 0
    RatingAggregate.objects.update_or_create(
        target_type=target_type, target_id=target_id,
        defaults={"count": count, "total": total, "average": average, "distribution": buckets})


def aggregate_for(target_type, target_id) -> dict:
    row = RatingAggregate.objects.filter(target_type=target_type, target_id=target_id).first()
    if not row:
        return {"count": 0, "average": 0.0, "distribution": {str(i): 0 for i in range(1, 6)}}
    return {"count": row.count, "average": float(row.average), "distribution": row.distribution}


def _target_field(review):
    return {TargetType.STORE: ("store_id", review.store_id), TargetType.PRODUCT: ("product_id", review.product_id),
            TargetType.DELIVERY_PARTNER: ("partner_id", review.partner_id)}[review.target_type]


def _target_id(review):
    return _target_field(review)[1]


@transaction.atomic
def create_review(*, customer, store_order, target_type, rating, title="", comment="", product=None) -> Review:
    if store_order.order.customer_id != customer.pk:
        raise PermissionDenied("You can only review your own orders.")
    if store_order.status != StoreOrderStatus.COMPLETED:
        raise ValidationError({"store_order": "You can review an order after it has been delivered."})
    rating = _validate_rating(rating)
    kwargs = {}
    if target_type == TargetType.STORE:
        kwargs["store"] = store_order.store
    elif target_type == TargetType.PRODUCT:
        if product is None or not store_order.items.filter(product_id=product.pk).exists():
            raise ValidationError({"product": "Choose a product from this order."})
        kwargs["product"] = product
    elif target_type == TargetType.DELIVERY_PARTNER:
        delivery = getattr(store_order, "delivery", None)
        if delivery is None or delivery.status != "DELIVERED" or delivery.partner_id is None:
            raise ValidationError({"target_type": "This order was not delivered by a delivery partner."})
        kwargs["partner"] = delivery.partner
    else:
        raise ValidationError({"target_type": "Choose store, product or delivery partner."})
    try:
        with transaction.atomic():
            review = Review.objects.create(
                customer=customer, store_order=store_order, target_type=target_type, rating=rating,
                title=clean_text(title, 120), comment=clean_text(comment, 2000), **kwargs)
    except IntegrityError:
        raise ValidationError({"detail": "You have already reviewed this part of the order."}) from None
    recompute_aggregate(target_type, _target_id(review))
    if target_type == TargetType.STORE:
        from deliveries.services import _store_users  # same store-recipient rule as order events

        notify_many(_store_users(store_order), Kind.REVIEW_RECEIVED, f"New {rating}-star review", review.title,
                    {"review_id": review.pk}, email=False)
    elif target_type == TargetType.DELIVERY_PARTNER:
        notify(review.partner.user, Kind.REVIEW_RECEIVED, f"New {rating}-star rating", "", {"review_id": review.pk}, email=False)
    return review


@transaction.atomic
def update_review(review, *, customer, rating=None, title=None, comment=None) -> Review:
    review = Review.objects.select_for_update().get(pk=review.pk)
    if review.customer_id != customer.pk:
        raise PermissionDenied("You can only edit your own reviews.")
    if review.status != ReviewStatus.PUBLISHED:
        raise ValidationError({"status": "This review can no longer be edited."})
    if timezone.now() - review.created_at > edit_window():
        raise ValidationError({"status": f"Reviews can be edited for {edit_window().days} days after they are written."})
    if rating is not None:
        review.rating = _validate_rating(rating)
    if title is not None:
        review.title = clean_text(title, 120)
    if comment is not None:
        review.comment = clean_text(comment, 2000)
    review.edited_at = timezone.now()
    review.save()
    recompute_aggregate(review.target_type, _target_id(review))
    return review


@transaction.atomic
def withdraw_review(review, *, customer) -> Review:
    review = Review.objects.select_for_update().get(pk=review.pk)
    if review.customer_id != customer.pk:
        raise PermissionDenied("You can only withdraw your own reviews.")
    if review.status in (ReviewStatus.WITHDRAWN, ReviewStatus.REJECTED):
        return review
    review.status = ReviewStatus.WITHDRAWN
    review.save(update_fields=["status", "updated_at"])
    recompute_aggregate(review.target_type, _target_id(review))
    return review


@transaction.atomic
def report_review(review, *, reporter, reason, note="") -> ReviewReport:
    if reason not in ReviewReport.Reason.values:
        raise ValidationError({"reason": "Choose a valid reason."})
    if review.status != ReviewStatus.PUBLISHED:
        raise ValidationError({"detail": "Only published reviews can be reported."})
    if getattr(getattr(review.customer, "user", None), "pk", None) == reporter.pk:
        raise ValidationError({"detail": "You cannot report your own review."})
    try:
        with transaction.atomic():
            report = ReviewReport.objects.create(review=review, reporter=reporter, reason=reason, note=clean_text(note, 500))
    except IntegrityError:
        raise ValidationError({"detail": "You have already reported this review."}) from None
    Review.objects.filter(pk=review.pk).update(report_count=review.reports.count())
    return report


MODERATION = {"hide": ReviewStatus.HIDDEN, "reject": ReviewStatus.REJECTED, "restore": ReviewStatus.PUBLISHED}


@transaction.atomic
def moderate_review(review, *, action, actor, reason="", request=None) -> Review:
    if action not in MODERATION:
        raise ValidationError({"action": "Unknown moderation action."})
    if action != "restore" and not (reason or "").strip():
        raise ValidationError({"reason": "A reason is required."})
    review = Review.objects.select_for_update().get(pk=review.pk)
    if review.status == ReviewStatus.WITHDRAWN:
        raise ValidationError({"status": "The customer withdrew this review."})
    target = MODERATION[action]
    if review.status == target:
        raise ValidationError({"status": f"The review is already {target.lower()}."})
    old = review.status
    review.status, review.moderation_reason = target, (reason or "")[:255]
    review.moderated_by, review.moderated_at = actor, timezone.now()
    review.save(update_fields=["status", "moderation_reason", "moderated_by", "moderated_at", "updated_at"])
    review.reports.update(resolved=True)
    recompute_aggregate(review.target_type, _target_id(review))
    audit(actor, f"review.{action}", review, summary=f"{old} -> {target}", request=request, reason=reason)
    notify(review.customer.user, Kind.REVIEW_MODERATED, "Your review was updated by our moderators", reason, {"review_id": review.pk}, email=False)
    return review


@transaction.atomic
def reply_to_review(review, *, user, store, body) -> ReviewReply:
    if review.target_type != TargetType.STORE or review.store_id != store.pk:
        raise PermissionDenied("You can only reply to reviews of your own store.")
    if review.status != ReviewStatus.PUBLISHED:
        raise ValidationError({"status": "Only published reviews can be answered."})
    body = clean_text(body, 1000)
    if not body:
        raise ValidationError({"body": "A reply cannot be empty."})
    if ReviewReply.objects.filter(review=review).exists():
        raise ValidationError({"detail": "This review has already been answered."})
    reply = ReviewReply.objects.create(review=review, author=user, body=body)
    notify(review.customer.user, Kind.REVIEW_RECEIVED, f"{review.store.name} replied to your review", body[:200], {"review_id": review.pk}, email=False)
    return reply
