"""Delivery pricing configuration (versioned), service zones and checkout quotes."""
import uuid
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q

from .engine import Funder, Mode, Rounding

M = dict(max_digits=10, decimal_places=2)
R = dict(max_digits=6, decimal_places=4)  # ratios: 0.1000 = 10%
NONNEG = [MinValueValidator(Decimal("0"))]


class FuelType(models.TextChoices):
    PETROL = "PETROL", "Petrol (₹/litre, km/litre)"
    DIESEL = "DIESEL", "Diesel (₹/litre, km/litre)"
    ELECTRIC = "ELECTRIC", "Electric (₹/kWh, km/kWh)"
    CNG = "CNG", "CNG (₹/kg, km/kg)"


ENERGY_UNIT = {FuelType.PETROL: "litre", FuelType.DIESEL: "litre", FuelType.ELECTRIC: "kWh", FuelType.CNG: "kg"}


class PricingZone(models.Model):
    """A named service area. Optional polygon (list of [lat, lon]) for polygon-based serviceability."""

    name = models.CharField(max_length=120, unique=True)
    state = models.CharField(max_length=100, default="Kerala")
    district = models.CharField(max_length=100, blank=True)
    locality = models.CharField(max_length=120, blank=True)
    polygon = models.JSONField(default=list, blank=True, help_text="[[lat, lon], ...] at least 3 points; empty = no polygon.")
    service_area_surcharge = models.DecimalField(default=Decimal("0"), validators=NONNEG, help_text="Added to customer fee for addresses in this zone (e.g. hilly or hard-to-reach).", **M)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class DeliveryPricingVersion(models.Model):
    """One immutable set of delivery assumptions. Changing settings creates a new version.

    The active version for a zone is the newest one whose ``effective_from`` has passed;
    zone-less versions are the default. Orders keep a snapshot, so new versions never
    change placed orders.
    """

    zone = models.ForeignKey(PricingZone, null=True, blank=True, on_delete=models.PROTECT, related_name="pricing_versions",
                             help_text="Empty = default for every address not in a zone with its own pricing.")
    version = models.PositiveIntegerField(editable=False)
    effective_from = models.DateTimeField()
    currency = models.CharField(max_length=3, default="INR", editable=False)
    is_illustrative = models.BooleanField(default=True, help_text="True while the numbers are planning examples, not verified business costs.")

    # Energy
    fuel_type = models.CharField(max_length=16, choices=FuelType.choices, default=FuelType.PETROL)
    energy_price = models.DecimalField(validators=NONNEG, help_text="₹ per litre / kWh / kg.", **M)
    energy_price_source = models.CharField(max_length=255, blank=True)
    energy_price_verified_at = models.DateTimeField(null=True, blank=True)
    efficiency_km_per_unit = models.DecimalField(help_text="km per litre / kWh / kg. Must be above zero.", **M)
    maintenance_per_km = models.DecimalField(validators=NONNEG, help_text="Maintenance and tyre wear, ₹/km.", **M)

    # Rider pay
    rider_pay_per_order = models.DecimalField(default=Decimal("0"), validators=NONNEG, **M)
    rider_pay_per_km = models.DecimalField(default=Decimal("0"), validators=NONNEG, help_text="Incentive per km of store-to-customer distance.", **M)
    rider_fixed_daily_pay = models.DecimalField(default=Decimal("0"), validators=NONNEG, **M)
    rider_expected_orders_per_day = models.DecimalField(default=Decimal("20"), validators=NONNEG, help_text="Spreads fixed daily pay across orders.", **M)
    rider_pay_per_failed_attempt = models.DecimalField(default=Decimal("0"), validators=NONNEG, help_text="Paid for an attempt that failed through no fault of the rider.", **M)

    # Operations
    operational_multiplier = models.DecimalField(default=Decimal("1.6"), help_text="Operational km = road distance × this. 1.6 typical, 2.0 isolated return trip.", **R)
    overhead_per_order = models.DecimalField(default=Decimal("0"), validators=NONNEG, **M)
    overhead_per_km = models.DecimalField(default=Decimal("0"), validators=NONNEG, **M)
    failure_cost_rate = models.DecimalField(default=Decimal("0.10"), help_text="Failed-delivery allowance as a share of direct cost (0.10 = 10%).", **R)
    special_handling_cost = models.DecimalField(default=Decimal("0"), validators=NONNEG, help_text="Extra cost for heavy/bulky orders.", **M)
    road_fallback_factor = models.DecimalField(default=Decimal("1.35"), help_text="When no road route is available: estimated road km = straight-line km × this.", **R)
    allow_estimated_distance = models.BooleanField(default=True, help_text="If off, checkout refuses delivery when no road route is available.")

    # Customer tariff
    pricing_mode = models.CharField(max_length=24, choices=Mode.CHOICES, default=Mode.BASE_PLUS_DISTANCE)
    base_fee = models.DecimalField(default=Decimal("0"), validators=NONNEG, **M)
    included_km = models.DecimalField(default=Decimal("0"), validators=NONNEG, **M)
    per_km_rate = models.DecimalField(default=Decimal("0"), validators=NONNEG, **M)
    distance_bands = models.JSONField(default=list, blank=True, help_text='[{"up_to_km": 2, "fee": 20}, ...]')
    customer_recovery_ratio = models.DecimalField(default=Decimal("0.65"), help_text="Cost-aware mode: share of estimated cost the customer fee should recover.", **R)
    max_platform_subsidy_per_order = models.DecimalField(default=Decimal("30"), validators=NONNEG, help_text="Hybrid mode: most Zuuvi subsidises one delivery.", **M)
    min_fee = models.DecimalField(default=Decimal("0"), validators=NONNEG, **M)
    max_fee = models.DecimalField(default=Decimal("99"), validators=NONNEG, **M)
    allow_above_max_fee = models.BooleanField(default=False)
    rounding = models.CharField(max_length=16, choices=Rounding.CHOICES, default=Rounding.NEAREST_RUPEE)
    max_service_km = models.DecimalField(null=True, blank=True, validators=NONNEG, **M)

    # Surcharges
    peak_surcharge = models.DecimalField(default=Decimal("0"), validators=NONNEG, **M)
    peak_windows = models.JSONField(default=list, blank=True, help_text='[{"days": [0,1,2,3,4,5,6], "start": "18:00", "end": "21:00"}] in India time; 0 = Monday.')
    heavy_surcharge = models.DecimalField(default=Decimal("0"), validators=NONNEG, **M)

    # Offers
    free_delivery_threshold = models.DecimalField(null=True, blank=True, validators=NONNEG, help_text="Items subtotal per store at or above which delivery is free. Empty = off.", **M)
    free_delivery_funded_by = models.CharField(max_length=16, choices=Funder.CHOICES, default=Funder.PLATFORM)
    delivery_discount_amount = models.DecimalField(default=Decimal("0"), validators=NONNEG, **M)
    delivery_discount_min_order = models.DecimalField(default=Decimal("0"), validators=NONNEG, **M)
    delivery_discount_funded_by = models.CharField(max_length=16, choices=Funder.CHOICES, default=Funder.PLATFORM)

    # Tax
    delivery_tax_rate = models.DecimalField(default=Decimal("0"), help_text="Tax on the delivery fee (0.18 = 18%). Leave 0 until the tax treatment is confirmed.", **R)
    tax_treatment_confirmed = models.BooleanField(default=False)

    notes = models.TextField(blank=True)
    reason = models.CharField(max_length=255, help_text="Why this version was created (audit).")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-effective_from", "-version"]
        constraints = [
            models.UniqueConstraint(fields=["zone", "version"], name="unique_pricing_version_per_zone"),
            models.UniqueConstraint(fields=["version"], condition=Q(zone__isnull=True), name="unique_default_pricing_version"),
            models.CheckConstraint(condition=Q(efficiency_km_per_unit__gt=0), name="pricing_efficiency_positive"),
            models.CheckConstraint(condition=Q(operational_multiplier__gte=1), name="pricing_multiplier_at_least_one"),
            models.CheckConstraint(condition=Q(max_fee__gte=models.F("min_fee")), name="pricing_max_fee_gte_min"),
            models.CheckConstraint(condition=Q(failure_cost_rate__gte=0) & Q(failure_cost_rate__lte=1), name="pricing_failure_rate_range"),
        ]

    def __str__(self):
        return f"{self.zone or 'Default'} v{self.version}"


class CheckoutQuote(models.Model):
    """Server-calculated price shown to the customer before ordering. Expires; used once."""

    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    customer = models.ForeignKey("customers.Customer", on_delete=models.CASCADE, related_name="checkout_quotes")
    address = models.ForeignKey("customers.CustomerAddress", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    fulfillment_type = models.CharField(max_length=32)
    fingerprint = models.CharField(max_length=64, help_text="Hash of cart lines + address + store set; a different cart needs a new quote.")
    data = models.JSONField(default=dict)
    delivery_total = models.DecimalField(**M)
    grand_total = models.DecimalField(**M)
    expires_at = models.DateTimeField()
    order = models.OneToOneField("orders.Order", null=True, blank=True, on_delete=models.SET_NULL, related_name="checkout_quote")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["customer", "-created_at"], name="quote_customer_recent_idx")]


class PartnerEarning(models.Model):
    """One payout line for a delivery partner: a completed delivery or a paid failed attempt."""

    class Kind(models.TextChoices):
        DELIVERY = "DELIVERY", "Delivery completed"
        FAILED_ATTEMPT = "FAILED_ATTEMPT", "Failed attempt (not rider's fault)"
        ADJUSTMENT = "ADJUSTMENT", "Adjustment"

    class Status(models.TextChoices):
        UNPAID = "UNPAID", "Unpaid"
        PAID = "PAID", "Paid"

    partner = models.ForeignKey("deliveries.DeliveryPartner", on_delete=models.PROTECT, related_name="earnings")
    delivery = models.ForeignKey("deliveries.Delivery", null=True, blank=True, on_delete=models.PROTECT, related_name="earnings")
    attempt_number = models.PositiveSmallIntegerField(default=1)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    amount = models.DecimalField(**M)
    breakdown = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.UNPAID, db_index=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    payout_reference = models.CharField(max_length=64, blank=True)
    note = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["delivery", "attempt_number", "kind"], condition=~Q(kind="ADJUSTMENT"), name="unique_earning_per_attempt"),
        ]


class LogisticsPermissions(models.Model):
    """Holder for permissions that are not tied to one model's add/change/delete."""

    class Meta:
        managed = False
        default_permissions = ()
        permissions = (
            ("manage_delivery_pricing", "Can change delivery pricing settings and zones"),
            ("view_delivery_operations", "Can view delivery costs, subsidies and operations reports"),
            ("manage_partner_payouts", "Can mark delivery partner earnings as paid"),
        )
