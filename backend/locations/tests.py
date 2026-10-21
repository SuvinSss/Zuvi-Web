from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase

from locations.models import Address


class AddressModelTests(TestCase):
    def test_create_valid_address(self):
        address = Address(
            line1="12 MG Road",
            city="Bengaluru",
            state="Karnataka",
            postal_code="560001",
            latitude=Decimal("12.971600"),
            longitude=Decimal("77.594600"),
        )
        address.full_clean()
        address.save()
        self.assertEqual(str(address), "12 MG Road, Bengaluru, Karnataka, 560001, India")
        self.assertEqual(address.country, "India")

    def test_latitude_out_of_range_rejected(self):
        address = Address(
            line1="12 MG Road",
            city="Bengaluru",
            state="Karnataka",
            postal_code="560001",
            latitude=Decimal("95.000000"),
            longitude=Decimal("77.594600"),
        )
        with self.assertRaises(ValidationError) as ctx:
            address.full_clean()
        self.assertIn("latitude", ctx.exception.message_dict)

    def test_longitude_out_of_range_rejected(self):
        address = Address(
            line1="12 MG Road",
            city="Bengaluru",
            state="Karnataka",
            postal_code="560001",
            latitude=Decimal("12.971600"),
            longitude=Decimal("-181.000000"),
        )
        with self.assertRaises(ValidationError) as ctx:
            address.full_clean()
        self.assertIn("longitude", ctx.exception.message_dict)

    def test_boundary_coordinates_are_valid(self):
        address = Address(
            line1="Edge",
            city="Test",
            state="Test",
            postal_code="000000",
            latitude=Decimal("-90.000000"),
            longitude=Decimal("180.000000"),
        )
        address.full_clean()
        address.save()
        self.assertEqual(address.latitude, Decimal("-90.000000"))
