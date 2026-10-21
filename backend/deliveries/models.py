"""Delivery domain: partners, deliveries, assignments, GPS pings and evidence.

One ``Delivery`` exists per delivery-type ``StoreOrder`` (a multi-store order has
one delivery per store, because each store hands over separately). Retries create
new ``DeliveryAttempt`` rows; history is append-only.
"""
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Q

from core.storage import private_storage


class PartnerStatus(models.TextChoices):
    PENDING = "PENDING", "Pending approval"
    APPROVED = "APPROVED", "Approved"
    SUSPENDED = "SUSPENDED", "Suspended"
    REJECTED = "REJECTED", "Rejected"


class VehicleType(models.TextChoices):
    BICYCLE = "BICYCLE", "Bicycle"
    SCOOTER = "SCOOTER", "Scooter"
    MOTORCYCLE = "MOTORCYCLE", "Motorcycle"
    CAR = "CAR", "Car"
    VAN = "VAN", "Van"
    OTHER = "OTHER", "Other"


class DeliveryPartner(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="delivery_partner")
    status = models.CharField(max_length=16, choices=PartnerStatus.choices, default=PartnerStatus.PENDING, db_index=True)
    vehicle_type = models.CharField(max_length=16, choices=VehicleType.choices, default=VehicleType.MOTORCYCLE)
    vehicle_number = models.CharField(max_length=30, blank=True)
    is_online = models.BooleanField(default=False, db_index=True)
    last_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    last_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    last_accuracy_m = models.FloatField(null=True, blank=True)
    last_location_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    approved_at = models.DateTimeField(null=True, blank=True)
    status_reason = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def is_approved(self) -> bool:
        return self.status == PartnerStatus.APPROVED and self.user.is_active

    def __str__(self):
        return f"{self.user.get_username()} ({self.status})"


class DeliveryStatus(models.TextChoices):
    PENDING_ASSIGNMENT = "PENDING_ASSIGNMENT", "Waiting for a delivery partner"
    OFFERED = "OFFERED", "Offered to a partner"
    ACCEPTED = "ACCEPTED", "Partner heading to store"
    AT_STORE = "AT_STORE", "Partner at store"
    IN_TRANSIT = "IN_TRANSIT", "On the way"
    ARRIVED = "ARRIVED", "Arrived at customer"
    DELIVERED = "DELIVERED", "Delivered"
    FAILED = "FAILED", "Delivery attempt failed"
    CANCELLED = "CANCELLED", "Cancelled"


ACTIVE_PARTNER_STATUSES = (
    DeliveryStatus.OFFERED, DeliveryStatus.ACCEPTED, DeliveryStatus.AT_STORE,
    DeliveryStatus.IN_TRANSIT, DeliveryStatus.ARRIVED,
)
TERMINAL_STATUSES = (DeliveryStatus.DELIVERED, DeliveryStatus.CANCELLED)


class Delivery(models.Model):
    store_order = models.OneToOneField("orders.StoreOrder", on_delete=models.PROTECT, related_name="delivery")
    status = models.CharField(max_length=24, choices=DeliveryStatus.choices, default=DeliveryStatus.PENDING_ASSIGNMENT, db_index=True)
    partner = models.ForeignKey(DeliveryPartner, null=True, blank=True, on_delete=models.PROTECT, related_name="deliveries")
    attempt_number = models.PositiveSmallIntegerField(default=1)
    # Snapshot of the route so tracking never depends on later address edits.
    pickup_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    pickup_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    dropoff_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    dropoff_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    otp_nonce = models.CharField(max_length=32, blank=True)
    otp_failed_attempts = models.PositiveSmallIntegerField(default=0)
    otp_verified_at = models.DateTimeField(null=True, blank=True)
    # Set when automatic offers keep failing so an admin should step in.
    needs_attention = models.BooleanField(default=False, db_index=True)
    rejection_count = models.PositiveSmallIntegerField(default=0)
    eta_at = models.DateTimeField(null=True, blank=True)  # only filled if a routing provider is configured
    assigned_at = models.DateTimeField(null=True, blank=True)
    picked_up_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "deliveries"
        indexes = [
            models.Index(fields=["partner", "status"], name="delivery_partner_status_idx"),
            models.Index(fields=["status", "needs_attention"], name="delivery_attention_idx"),
        ]

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_PARTNER_STATUSES

    def __str__(self):
        return f"Delivery {self.pk} ({self.status})"


class DeliveryStatusHistory(models.Model):
    delivery = models.ForeignKey(Delivery, on_delete=models.CASCADE, related_name="status_history")
    old_status = models.CharField(max_length=24, blank=True)
    new_status = models.CharField(max_length=24)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    note = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]


class AssignmentStatus(models.TextChoices):
    OFFERED = "OFFERED", "Offered"
    ACCEPTED = "ACCEPTED", "Accepted"
    REJECTED = "REJECTED", "Rejected"
    EXPIRED = "EXPIRED", "Expired"
    REVOKED = "REVOKED", "Revoked"
    COMPLETED = "COMPLETED", "Completed"


class DeliveryAssignment(models.Model):
    delivery = models.ForeignKey(Delivery, on_delete=models.CASCADE, related_name="assignments")
    partner = models.ForeignKey(DeliveryPartner, on_delete=models.PROTECT, related_name="assignments")
    attempt_number = models.PositiveSmallIntegerField(default=1)
    status = models.CharField(max_length=16, choices=AssignmentStatus.choices, default=AssignmentStatus.OFFERED)
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    automatic = models.BooleanField(default=False)
    reason = models.CharField(max_length=255, blank=True)
    offered_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-offered_at", "-pk"]
        constraints = [
            # Never two live assignments for one delivery.
            models.UniqueConstraint(
                fields=["delivery"],
                condition=Q(status__in=["OFFERED", "ACCEPTED"]),
                name="one_active_assignment_per_delivery",
            ),
        ]


class LocationPing(models.Model):
    delivery = models.ForeignKey(Delivery, on_delete=models.CASCADE, related_name="pings")
    partner = models.ForeignKey(DeliveryPartner, on_delete=models.CASCADE, related_name="pings")
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    accuracy_m = models.FloatField(null=True, blank=True)
    device_time = models.DateTimeField(null=True, blank=True)  # client clock: informational only
    recorded_at = models.DateTimeField(auto_now_add=True)  # server clock: authoritative

    class Meta:
        ordering = ["-recorded_at", "-pk"]
        indexes = [models.Index(fields=["delivery", "-recorded_at"], name="ping_delivery_time_idx")]
        constraints = [
            models.CheckConstraint(condition=Q(latitude__gte=Decimal("-90")) & Q(latitude__lte=Decimal("90")), name="ping_lat_range"),
            models.CheckConstraint(condition=Q(longitude__gte=Decimal("-180")) & Q(longitude__lte=Decimal("180")), name="ping_lon_range"),
        ]


class EvidenceKind(models.TextChoices):
    PICKUP = "PICKUP", "Pickup"
    DELIVERY = "DELIVERY", "Delivery"


class DeliveryEvidence(models.Model):
    """Append-only proof record. Corrections are new records, never edits."""

    delivery = models.ForeignKey(Delivery, on_delete=models.PROTECT, related_name="evidence")
    attempt_number = models.PositiveSmallIntegerField(default=1)
    kind = models.CharField(max_length=10, choices=EvidenceKind.choices)
    captured_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    accuracy_m = models.FloatField(null=True, blank=True)
    distance_from_target_m = models.FloatField(null=True, blank=True)
    within_tolerance = models.BooleanField(null=True, blank=True)
    notes = models.TextField(blank=True)
    recipient_name = models.CharField(max_length=150, blank=True)
    store_confirmed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    store_confirmed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)  # server timestamp

    class Meta:
        ordering = ["created_at", "pk"]
        indexes = [models.Index(fields=["delivery", "kind", "attempt_number"], name="evidence_lookup_idx")]


class EvidencePhoto(models.Model):
    evidence = models.ForeignKey(DeliveryEvidence, on_delete=models.PROTECT, related_name="photos")
    file = models.FileField(upload_to="delivery-evidence/%Y/%m/", storage=private_storage)
    content_type = models.CharField(max_length=50)
    size = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["pk"]


class DeliveryAttempt(models.Model):
    class Outcome(models.TextChoices):
        IN_PROGRESS = "IN_PROGRESS", "In progress"
        DELIVERED = "DELIVERED", "Delivered"
        FAILED = "FAILED", "Failed"
        CANCELLED = "CANCELLED", "Cancelled"

    class FailureReason(models.TextChoices):
        CUSTOMER_UNAVAILABLE = "CUSTOMER_UNAVAILABLE", "Customer unavailable"
        WRONG_ADDRESS = "WRONG_ADDRESS", "Wrong or unreachable address"
        CUSTOMER_REFUSED = "CUSTOMER_REFUSED", "Customer refused the order"
        UNSAFE_LOCATION = "UNSAFE_LOCATION", "Unsafe location"
        VEHICLE_PROBLEM = "VEHICLE_PROBLEM", "Vehicle problem"
        OTHER = "OTHER", "Other"

    delivery = models.ForeignKey(Delivery, on_delete=models.CASCADE, related_name="attempts")
    number = models.PositiveSmallIntegerField()
    partner = models.ForeignKey(DeliveryPartner, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    outcome = models.CharField(max_length=16, choices=Outcome.choices, default=Outcome.IN_PROGRESS)
    failure_reason = models.CharField(max_length=24, choices=FailureReason.choices, blank=True)
    failure_note = models.TextField(blank=True)
    failure_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    failure_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["number"]
        constraints = [models.UniqueConstraint(fields=["delivery", "number"], name="unique_attempt_number")]
