from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models


class LocationSource(models.TextChoices):
    MANUAL = "MANUAL", "Entered manually"
    PLACE_SEARCH = "PLACE_SEARCH", "Chosen from search"
    CURRENT_LOCATION = "CURRENT_LOCATION", "Device location"
    MAP_PIN = "MAP_PIN", "Adjusted on the map"


class Address(models.Model):
    line1 = models.CharField(max_length=255)
    line2 = models.CharField(max_length=255, blank=True)
    landmark = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100)
    district = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100)
    postal_code = models.CharField(max_length=20)
    country = models.CharField(max_length=100, default="India")
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    # Google Place IDs may be stored indefinitely under Google's terms; other Place
    # content (names, photos, reviews) is deliberately not stored.
    google_place_id = models.CharField(max_length=255, blank=True)
    location_source = models.CharField(
        max_length=20, choices=LocationSource.choices, default=LocationSource.MANUAL
    )
    # Set when the user confirmed the pin position on the map.
    location_confirmed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "addresses"
        ordering = ["country", "state", "city", "line1"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(latitude__gte=Decimal("-90"))
                & models.Q(latitude__lte=Decimal("90")),
                name="address_latitude_range",
            ),
            models.CheckConstraint(
                condition=models.Q(longitude__gte=Decimal("-180"))
                & models.Q(longitude__lte=Decimal("180")),
                name="address_longitude_range",
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.latitude is not None and not (
            Decimal("-90") <= self.latitude <= Decimal("90")
        ):
            errors["latitude"] = "Latitude must be between -90 and 90."
        if self.longitude is not None and not (
            Decimal("-180") <= self.longitude <= Decimal("180")
        ):
            errors["longitude"] = "Longitude must be between -180 and 180."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        parts = [self.line1]
        if self.line2:
            parts.append(self.line2)
        if self.landmark:
            parts.append(self.landmark)
        parts.append(self.city)
        if self.district:
            parts.append(self.district)
        parts.extend([self.state, self.postal_code, self.country])
        return ", ".join(parts)
