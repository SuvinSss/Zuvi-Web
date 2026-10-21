"""Ratings and reviews for stores, products and delivery partners.

Only the customer who received the order can review, only after the relevant
StoreOrder is COMPLETED, and only once per target per order. Only PUBLISHED
reviews count towards aggregates.
"""
from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q


class TargetType(models.TextChoices):
    STORE = "STORE", "Store"
    PRODUCT = "PRODUCT", "Product"
    DELIVERY_PARTNER = "DELIVERY_PARTNER", "Delivery partner"


class ReviewStatus(models.TextChoices):
    PUBLISHED = "PUBLISHED", "Published"
    HIDDEN = "HIDDEN", "Hidden by moderator"
    REJECTED = "REJECTED", "Rejected"
    WITHDRAWN = "WITHDRAWN", "Withdrawn by customer"


class Review(models.Model):
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="reviews")
    store_order = models.ForeignKey("orders.StoreOrder", on_delete=models.PROTECT, related_name="reviews")
    target_type = models.CharField(max_length=20, choices=TargetType.choices)
    store = models.ForeignKey("stores.Store", null=True, blank=True, on_delete=models.PROTECT, related_name="reviews")
    product = models.ForeignKey("catalog.Product", null=True, blank=True, on_delete=models.PROTECT, related_name="reviews")
    partner = models.ForeignKey("deliveries.DeliveryPartner", null=True, blank=True, on_delete=models.PROTECT, related_name="reviews")
    rating = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    title = models.CharField(max_length=120, blank=True)
    comment = models.TextField(blank=True, max_length=2000)
    status = models.CharField(max_length=12, choices=ReviewStatus.choices, default=ReviewStatus.PUBLISHED, db_index=True)
    moderation_reason = models.CharField(max_length=255, blank=True)
    moderated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    moderated_at = models.DateTimeField(null=True, blank=True)
    edited_at = models.DateTimeField(null=True, blank=True)
    report_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        indexes = [
            models.Index(fields=["store", "status", "-created_at"], name="review_store_idx"),
            models.Index(fields=["product", "status", "-created_at"], name="review_product_idx"),
            models.Index(fields=["partner", "status"], name="review_partner_idx"),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(rating__gte=1) & Q(rating__lte=5), name="review_rating_1_5"),
            # Exactly one target, matching target_type.
            models.CheckConstraint(
                condition=(Q(target_type="STORE", store__isnull=False, product__isnull=True, partner__isnull=True)
                           | Q(target_type="PRODUCT", product__isnull=False, store__isnull=True, partner__isnull=True)
                           | Q(target_type="DELIVERY_PARTNER", partner__isnull=False, store__isnull=True, product__isnull=True)),
                name="review_single_target"),
            models.UniqueConstraint(fields=["store_order", "store"], condition=Q(target_type="STORE"), name="one_store_review_per_store_order"),
            models.UniqueConstraint(fields=["store_order", "product"], condition=Q(target_type="PRODUCT"), name="one_product_review_per_store_order"),
            models.UniqueConstraint(fields=["store_order", "partner"], condition=Q(target_type="DELIVERY_PARTNER"), name="one_partner_review_per_store_order"),
        ]


class ReviewReply(models.Model):
    """Public reply from the reviewed store (one per review)."""

    review = models.OneToOneField(Review, on_delete=models.CASCADE, related_name="reply")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    body = models.TextField(max_length=1000)
    created_at = models.DateTimeField(auto_now_add=True)


class ReviewReport(models.Model):
    class Reason(models.TextChoices):
        ABUSIVE = "ABUSIVE", "Abusive or offensive"
        SPAM = "SPAM", "Spam or advertising"
        FAKE = "FAKE", "Fake or irrelevant"
        PRIVATE = "PRIVATE", "Contains private information"
        OTHER = "OTHER", "Other"

    review = models.ForeignKey(Review, on_delete=models.CASCADE, related_name="reports")
    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    reason = models.CharField(max_length=10, choices=Reason.choices)
    note = models.CharField(max_length=500, blank=True)
    resolved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["review", "reporter"], name="one_report_per_user_per_review")]


class RatingAggregate(models.Model):
    """Denormalised published-review totals, recomputed (never incremented) on every change."""

    target_type = models.CharField(max_length=20, choices=TargetType.choices)
    target_id = models.PositiveBigIntegerField()
    count = models.PositiveIntegerField(default=0)
    total = models.PositiveIntegerField(default=0)
    average = models.DecimalField(max_digits=3, decimal_places=2, default=0)
    distribution = models.JSONField(default=dict)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["target_type", "target_id"], name="one_aggregate_per_target")]
