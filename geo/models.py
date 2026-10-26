from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


def _money(**kwargs):
    return models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0"))], **kwargs
    )


class DeliveryPricingConfig(models.Model):
    """Versioned delivery pricing assumptions. Rows are never edited in place.

    Changing pricing means creating a new row and activating it. Quotes and orders
    keep a reference to the version they were priced with.
    """

    version = models.PositiveIntegerField(unique=True)
    name = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=False)

    # --- Operational cost model (internal; never shown to customers)
    fuel_price_per_litre = _money()
    vehicle_mileage_km_per_litre = models.DecimalField(
        max_digits=6, decimal_places=2, validators=[MinValueValidator(Decimal("0.1"))]
    )
    maintenance_cost_per_km = _money(default=Decimal("0.00"))
    operational_distance_multiplier = models.DecimalField(
        max_digits=4, decimal_places=2, default=Decimal("1.00"),
        validators=[MinValueValidator(Decimal("1")), MaxValueValidator(Decimal("5"))],
        help_text="Operational km = road km x this factor (e.g. 2.00 for a return trip).",
    )
    minimum_operational_distance_km = models.DecimalField(
        max_digits=6, decimal_places=2, default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    rider_base_payout = _money(default=Decimal("0.00"))
    rider_payout_per_km = _money(default=Decimal("0.00"))
    other_cost_per_delivery = _money(default=Decimal("0.00"))

    # --- Customer tariff
    customer_base_fee = _money(default=Decimal("0.00"))
    customer_free_distance_km = models.DecimalField(
        max_digits=6, decimal_places=2, default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    customer_fee_per_km = _money(default=Decimal("0.00"))
    customer_minimum_fee = _money(default=Decimal("0.00"))
    customer_maximum_fee = _money(null=True, blank=True)
    fee_rounding_step = models.DecimalField(
        max_digits=6, decimal_places=2, default=Decimal("1.00"),
        validators=[MinValueValidator(Decimal("0.01"))],
    )

    # --- Offers and serviceability
    free_delivery_threshold = _money(null=True, blank=True)
    store_funded_discount_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))],
    )
    max_road_distance_km = models.DecimalField(
        max_digits=6, decimal_places=2, default=Decimal("15.00"),
        validators=[MinValueValidator(Decimal("0.1"))],
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-version"]
        permissions = (
            ("manage_maps_operations", "Can view maps diagnostics and manage store locations"),
            ("manage_delivery_pricing", "Can create delivery pricing versions and run the simulator"),
            ("manage_delivery_assignments", "Can assign delivery partners to store orders"),
        )
        constraints = [
            models.UniqueConstraint(
                fields=["is_active"], condition=models.Q(is_active=True),
                name="geo_single_active_pricing_config",
            ),
        ]

    def __str__(self):
        return f"Delivery pricing v{self.version}{' (active)' if self.is_active else ''}"


class QuoteStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    CONSUMED = "CONSUMED", "Used by an order"
    SUPERSEDED = "SUPERSEDED", "Replaced by a newer quote"


class DeliveryQuote(models.Model):
    """Server-calculated delivery fee for one customer, address and basket."""

    customer = models.ForeignKey("customers.Customer", on_delete=models.CASCADE, related_name="delivery_quotes")
    customer_address = models.ForeignKey(
        "customers.CustomerAddress", null=True, on_delete=models.SET_NULL, related_name="delivery_quotes"
    )
    destination_latitude = models.DecimalField(max_digits=9, decimal_places=6)
    destination_longitude = models.DecimalField(max_digits=9, decimal_places=6)
    pricing_config = models.ForeignKey(DeliveryPricingConfig, on_delete=models.PROTECT, related_name="quotes")
    fingerprint = models.CharField(max_length=64)
    status = models.CharField(max_length=16, choices=QuoteStatus.choices, default=QuoteStatus.ACTIVE)
    delivery_fee_before_discount = _money()
    delivery_discount = _money()
    delivery_fee = _money()
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["customer", "status", "-created_at"])]

    def __str__(self):
        return f"Quote #{self.pk} ({self.status})"


class DeliveryQuoteLeg(models.Model):
    """Per-store delivery calculation. Internal cost fields are admin-only."""

    quote = models.ForeignKey(DeliveryQuote, on_delete=models.CASCADE, related_name="legs")
    store = models.ForeignKey("stores.Store", on_delete=models.PROTECT, related_name="+")
    store_code = models.CharField(max_length=32)
    items_subtotal = _money()

    # Route (actual Google result)
    route_distance_meters = models.PositiveIntegerField()
    route_duration_seconds = models.PositiveIntegerField()
    route_source = models.CharField(max_length=16)
    route_provider = models.CharField(max_length=32)
    route_travel_mode = models.CharField(max_length=16)
    route_calculated_at = models.DateTimeField()

    # Estimated operational model (internal)
    operational_distance_km = models.DecimalField(max_digits=8, decimal_places=3)
    operational_cost = _money()
    rider_payout = _money()

    # Customer-facing amounts
    fee_before_discount = _money()
    discount = _money()
    fee_after_discount = _money()

    # Who funds what (internal)
    platform_subsidy = _money()
    store_funded_discount = _money()
    unrecovered_cost = _money()

    class Meta:
        ordering = ["store_id"]
        constraints = [
            models.UniqueConstraint(fields=["quote", "store"], name="geo_one_leg_per_store_in_quote"),
        ]


class MapsHealthCheck(models.Model):
    """Result of a controlled backend check against Google. Contains no secrets."""

    class Service(models.TextChoices):
        GEOCODING = "GEOCODING", "Geocoding API"
        ROUTES = "ROUTES", "Routes API"

    service = models.CharField(max_length=16, choices=Service.choices)
    ok = models.BooleanField()
    error_code = models.CharField(max_length=40, blank=True)
    message = models.CharField(max_length=200, blank=True)
    latency_ms = models.PositiveIntegerField(null=True, blank=True)
    checked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    checked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-checked_at"]
        indexes = [models.Index(fields=["service", "-checked_at"])]
