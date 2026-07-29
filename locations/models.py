from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models


class Address(models.Model):
    line1 = models.CharField(max_length=255)
    line2 = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    postal_code = models.CharField(max_length=20)
    country = models.CharField(max_length=100, default="India")
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
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
        parts.extend([self.city, self.state, self.postal_code, self.country])
        return ", ".join(parts)
