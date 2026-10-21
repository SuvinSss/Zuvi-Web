from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, TransactionTestCase

from accounts.models import Role
from locations.models import Address

from .models import (
    AddressLabel,
    Customer,
    CustomerAddress,
    RegistrationSource,
    VerificationStatus,
)
from .services import generate_customer_code

User = get_user_model()


class CustomerModelTestMixin:
    def create_customer_user(self, username="customer", **overrides):
        defaults = {
            "username": username,
            "email": f"{username}@example.com",
            "password": "secure-password-123",
            "role": Role.CUSTOMER,
            "is_staff": False,
            "is_superuser": False,
        }
        defaults.update(overrides)
        password = defaults.pop("password")
        user = User(**defaults)
        user.set_password(password)
        user.save()
        return user

    def create_customer(self, *, username="customer", **overrides):
        user = overrides.pop("user", None) or self.create_customer_user(username=username)
        defaults = {
            "user": user,
            "registration_source": RegistrationSource.WEBSITE,
        }
        defaults.update(overrides)
        customer = Customer(**defaults)
        customer.full_clean()
        customer.save()
        return customer

    def create_address(self, **overrides):
        defaults = {
            "line1": "12 MG Road",
            "city": "Bengaluru",
            "state": "Karnataka",
            "postal_code": "560001",
            "latitude": Decimal("12.971600"),
            "longitude": Decimal("77.594600"),
        }
        defaults.update(overrides)
        address = Address(**defaults)
        address.full_clean()
        address.save()
        return address

    def create_customer_address(self, customer, **overrides):
        defaults = {
            "customer": customer,
            "address": overrides.pop("address", None) or self.create_address(),
            "label": AddressLabel.HOME,
            "recipient_name": "Ada Customer",
            "phone_number": "9876543210",
            "is_default": False,
            "is_active": True,
        }
        defaults.update(overrides)
        customer_address = CustomerAddress(**defaults)
        customer_address.full_clean()
        customer_address.save()
        return customer_address


class CustomerModelTests(CustomerModelTestMixin, TestCase):
    def test_create_customer_profile(self):
        customer = self.create_customer(username="ada")
        self.assertTrue(customer.customer_code.startswith("CU"))
        self.assertEqual(len(customer.customer_code), 10)
        self.assertEqual(customer.registration_source, RegistrationSource.WEBSITE)
        self.assertEqual(customer.verification_status, VerificationStatus.UNVERIFIED)
        self.assertEqual(customer.user.customer_profile, customer)
        self.assertIn("ada", str(customer))
        self.assertIn(customer.customer_code, str(customer))

    def test_customer_code_is_unique(self):
        first = self.create_customer(username="one")
        second = self.create_customer(username="two")
        self.assertNotEqual(first.customer_code, second.customer_code)

    def test_customer_rejects_non_customer_role(self):
        admin_user = User.objects.create_user(
            username="admin-role",
            email="admin-role@example.com",
            password="secure-password-123",
            role=Role.ADMIN,
            is_staff=True,
        )
        profile = Customer(
            user=admin_user,
            registration_source=RegistrationSource.MANAGEMENT_PORTAL,
        )
        with self.assertRaises(ValidationError) as ctx:
            profile.full_clean()
        self.assertIn("user", ctx.exception.message_dict)

    def test_customer_rejects_staff_or_superuser_flags(self):
        staff_customer = self.create_customer_user(
            username="staffish",
            is_staff=True,
        )
        profile = Customer(
            user=staff_customer,
            registration_source=RegistrationSource.WEBSITE,
        )
        with self.assertRaises(ValidationError) as ctx:
            profile.full_clean()
        self.assertIn("user", ctx.exception.message_dict)

        super_customer = self.create_customer_user(
            username="superish",
            is_superuser=True,
        )
        profile = Customer(
            user=super_customer,
            registration_source=RegistrationSource.WEBSITE,
        )
        with self.assertRaises(ValidationError) as ctx:
            profile.full_clean()
        self.assertIn("user", ctx.exception.message_dict)

    def test_one_to_one_user_relationship(self):
        customer = self.create_customer(username="unique-user")
        duplicate = Customer(
            user=customer.user,
            registration_source=RegistrationSource.MOBILE_APP,
        )
        with self.assertRaises(IntegrityError):
            duplicate.save()

    def test_registration_source_choices(self):
        for source in RegistrationSource.values:
            customer = self.create_customer(
                username=f"src-{source.lower()}",
                registration_source=source,
            )
            self.assertEqual(customer.registration_source, source)

    def test_created_by_related_name(self):
        creator = User.objects.create_user(
            username="creator",
            email="creator@example.com",
            password="secure-password-123",
            role=Role.ADMIN,
            is_staff=True,
        )
        customer = self.create_customer(
            username="managed",
            registration_source=RegistrationSource.MANAGEMENT_PORTAL,
            created_by=creator,
        )
        self.assertEqual(list(creator.created_customers.all()), [customer])

    def test_customer_does_not_store_credentials(self):
        field_names = {field.name for field in Customer._meta.get_fields()}
        self.assertNotIn("password", field_names)
        self.assertNotIn("username", field_names)
        self.assertNotIn("email", field_names)


class CustomerAddressModelTests(CustomerModelTestMixin, TestCase):
    def setUp(self):
        self.customer = self.create_customer(username="addr-owner")

    def test_create_address_linked_to_locations_address(self):
        address = self.create_address(line1="45 Residency Road")
        customer_address = self.create_customer_address(
            self.customer,
            address=address,
            label=AddressLabel.WORK,
            is_default=True,
        )
        self.assertEqual(customer_address.address, address)
        self.assertEqual(address.customer_address, customer_address)
        self.assertEqual(customer_address.label, AddressLabel.WORK)
        self.assertTrue(customer_address.is_default)
        self.assertIn(self.customer.customer_code, str(customer_address))

    def test_multiple_addresses_allowed(self):
        first = self.create_customer_address(
            self.customer,
            address=self.create_address(line1="Home 1"),
            label=AddressLabel.HOME,
            is_default=True,
        )
        second = self.create_customer_address(
            self.customer,
            address=self.create_address(line1="Work 1"),
            label=AddressLabel.WORK,
            is_default=False,
        )
        self.assertEqual(self.customer.addresses.count(), 2)
        self.assertTrue(first.is_default)
        self.assertFalse(second.is_default)

    def test_setting_new_default_clears_previous_active_default(self):
        first = self.create_customer_address(
            self.customer,
            address=self.create_address(line1="Default A"),
            is_default=True,
        )
        second = self.create_customer_address(
            self.customer,
            address=self.create_address(line1="Default B"),
            is_default=True,
        )
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertFalse(first.is_default)
        self.assertTrue(second.is_default)

    def test_inactive_default_does_not_block_new_active_default(self):
        inactive_default = self.create_customer_address(
            self.customer,
            address=self.create_address(line1="Old Default"),
            is_default=True,
            is_active=False,
        )
        active_default = self.create_customer_address(
            self.customer,
            address=self.create_address(line1="New Default"),
            is_default=True,
            is_active=True,
        )
        inactive_default.refresh_from_db()
        self.assertTrue(inactive_default.is_default)
        self.assertFalse(inactive_default.is_active)
        self.assertTrue(active_default.is_default)
        self.assertTrue(active_default.is_active)

    def test_unique_active_default_constraint(self):
        first = self.create_customer_address(
            self.customer,
            address=self.create_address(line1="Default 1"),
            is_default=False,
        )
        second = self.create_customer_address(
            self.customer,
            address=self.create_address(line1="Default 2"),
            is_default=False,
        )
        CustomerAddress.objects.filter(pk=first.pk).update(
            is_default=True,
            is_active=True,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CustomerAddress.objects.filter(pk=second.pk).update(
                    is_default=True,
                    is_active=True,
                )

    def test_address_one_to_one_cannot_be_shared(self):
        shared = self.create_address(line1="Shared Line")
        self.create_customer_address(self.customer, address=shared)
        other_customer = self.create_customer(username="other-owner")
        with self.assertRaises(IntegrityError):
            CustomerAddress(
                customer=other_customer,
                address=shared,
                label=AddressLabel.HOME,
                recipient_name="Other",
                phone_number="9111111111",
            ).save()

    def test_invalid_latitude_rejected_via_address_validation(self):
        bad_address = Address(
            line1="Bad Lat",
            city="Bengaluru",
            state="Karnataka",
            postal_code="560001",
            latitude=Decimal("95.000000"),
            longitude=Decimal("77.594600"),
        )
        with self.assertRaises(ValidationError) as ctx:
            bad_address.full_clean()
        self.assertIn("latitude", ctx.exception.message_dict)

        customer_address = CustomerAddress(
            customer=self.customer,
            address=bad_address,
            label=AddressLabel.HOME,
            recipient_name="Bad Lat User",
            phone_number="9222222222",
        )
        with self.assertRaises(ValidationError) as ctx:
            customer_address.clean()
        self.assertIn("latitude", ctx.exception.message_dict)

    def test_invalid_longitude_rejected(self):
        bad_address = Address(
            line1="Bad Lng",
            city="Bengaluru",
            state="Karnataka",
            postal_code="560001",
            latitude=Decimal("12.971600"),
            longitude=Decimal("-181.000000"),
        )
        with self.assertRaises(ValidationError) as ctx:
            bad_address.full_clean()
        self.assertIn("longitude", ctx.exception.message_dict)

        customer_address = CustomerAddress(
            customer=self.customer,
            address=bad_address,
            label=AddressLabel.OTHER,
            recipient_name="Bad Lng User",
            phone_number="9333333333",
        )
        with self.assertRaises(ValidationError) as ctx:
            customer_address.clean()
        self.assertIn("longitude", ctx.exception.message_dict)

    def test_address_label_choices(self):
        for label in AddressLabel.values:
            customer = self.create_customer(username=f"label-{label.lower()}")
            customer_address = self.create_customer_address(
                customer,
                address=self.create_address(line1=f"Line {label}"),
                label=label,
            )
            self.assertEqual(customer_address.label, label)

    def test_related_name_addresses(self):
        created = self.create_customer_address(self.customer)
        self.assertEqual(list(self.customer.addresses.all()), [created])


class CustomerCodeConcurrencyTests(CustomerModelTestMixin, TransactionTestCase):
    def test_save_retries_when_generated_code_collides(self):
        existing = self.create_customer(username="code-existing")
        colliding_code = existing.customer_code
        unique_code = "CUUNIQUE01"

        user = self.create_customer_user(username="code-retry")
        customer = Customer(
            user=user,
            registration_source=RegistrationSource.WEBSITE,
        )

        with mock.patch(
            "customers.services.generate_customer_code",
            side_effect=[colliding_code, unique_code],
        ):
            customer.save()

        customer.refresh_from_db()
        self.assertEqual(customer.customer_code, unique_code)

    def test_generate_customer_code_skips_existing_codes(self):
        existing = self.create_customer(username="code-skip")
        with mock.patch(
            "customers.services._candidate_customer_code",
            side_effect=[existing.customer_code, "CUNEVERUSED"],
        ):
            code = generate_customer_code()
        self.assertEqual(code, "CUNEVERUSED")
