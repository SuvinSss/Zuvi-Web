from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase, TransactionTestCase

from accounts.models import Role
from locations.models import Address

from .models import Store, StoreCategory, StoreStatus, StoreStatusHistory, StoreType, StoreUser
from .services import generate_store_code
from .validators import (
    MAX_STORE_IMAGE_SIZE_BYTES,
    store_image_upload_to,
    validate_store_image,
)

User = get_user_model()


class StoreModelTestMixin:
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
        return Address.objects.create(**defaults)

    def create_category(self, name="Grocery", **overrides):
        defaults = {"name": name}
        defaults.update(overrides)
        return StoreCategory.objects.create(**defaults)

    def create_store_user_account(self, username="store-user", **overrides):
        defaults = {
            "username": username,
            "email": f"{username}@example.com",
            "password": "secure-password-123",
            "role": Role.STORE_USER,
        }
        defaults.update(overrides)
        return User.objects.create_user(**defaults)

    def create_store(self, **overrides):
        category_name = overrides.pop(
            "category_name", f"Category-{Address.objects.count() + 1}"
        )
        if "address" not in overrides:
            overrides["address"] = self.create_address()
        if "category" not in overrides:
            overrides["category"] = self.create_category(name=category_name)
        defaults = {
            "name": "Zoop Mart",
            "store_type": StoreType.OWN_STORE,
            "status": StoreStatus.PENDING,
            "commission_percentage": Decimal("5.00"),
        }
        defaults.update(overrides)
        return Store.objects.create(**defaults)


class StoreCategoryModelTests(StoreModelTestMixin, TestCase):
    def test_slug_is_generated_from_name(self):
        category = self.create_category(name="Fresh Produce")
        self.assertEqual(category.slug, "fresh-produce")

    def test_name_must_be_unique(self):
        self.create_category(name="Grocery")
        with self.assertRaises(IntegrityError):
            StoreCategory.objects.create(name="Grocery")

    def test_str_returns_name(self):
        category = self.create_category(name="Pharmacy")
        self.assertEqual(str(category), "Pharmacy")


class StoreModelTests(StoreModelTestMixin, TestCase):
    def setUp(self):
        self.creator = User.objects.create_user(
            username="creator",
            email="creator@example.com",
            password="secure-password-123",
            role=Role.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )

    def test_store_code_is_generated_on_create(self):
        store = self.create_store(created_by=self.creator)
        self.assertTrue(store.store_code)
        self.assertTrue(store.store_code.startswith("ST"))
        self.assertEqual(len(store.store_code), 10)

    def test_store_code_is_unique(self):
        first = self.create_store(created_by=self.creator)
        second = self.create_store(
            name="Second Store",
            category_name="Second Category",
            created_by=self.creator,
        )
        self.assertNotEqual(first.store_code, second.store_code)

    def test_store_has_no_auth_credential_fields(self):
        field_names = {field.name for field in Store._meta.get_fields()}
        self.assertNotIn("username", field_names)
        self.assertNotIn("password", field_names)

    def test_commission_percentage_out_of_range_rejected(self):
        store = Store(
            name="Bad Commission",
            store_type=StoreType.PARTNER_STORE,
            category=self.create_category(name="Partner"),
            address=self.create_address(line1="1 Park Ave"),
            commission_percentage=Decimal("120.00"),
        )
        with self.assertRaises(ValidationError) as ctx:
            store.full_clean()
        self.assertIn("commission_percentage", ctx.exception.message_dict)

    def test_commission_percentage_boundaries_are_valid(self):
        zero = self.create_store(
            name="Zero Commission",
            category_name="Zero Cat",
            commission_percentage=Decimal("0.00"),
        )
        full = self.create_store(
            name="Full Commission",
            category_name="Full Cat",
            commission_percentage=Decimal("100.00"),
        )
        self.assertEqual(zero.commission_percentage, Decimal("0.00"))
        self.assertEqual(full.commission_percentage, Decimal("100.00"))

    def test_default_status_is_pending(self):
        store = self.create_store()
        self.assertEqual(store.status, StoreStatus.PENDING)

    def test_str_includes_name_and_code(self):
        store = self.create_store(name="Corner Shop")
        self.assertIn("Corner Shop", str(store))
        self.assertIn(store.store_code, str(store))


class StoreUserModelTests(StoreModelTestMixin, TestCase):
    def setUp(self):
        self.store = self.create_store(category_name="Main")
        self.store_user = self.create_store_user_account()
        self.customer = User.objects.create_user(
            username="customer",
            email="customer@example.com",
            password="secure-password-123",
            role=Role.CUSTOMER,
        )

    def test_store_user_requires_store_user_role(self):
        membership = StoreUser(store=self.store, user=self.customer, is_primary=True)
        with self.assertRaises(ValidationError) as ctx:
            membership.full_clean()
        self.assertIn("user", ctx.exception.message_dict)

    def test_valid_store_user_membership(self):
        membership = StoreUser(
            store=self.store,
            user=self.store_user,
            is_primary=True,
        )
        membership.full_clean()
        membership.save()
        self.assertTrue(membership.is_active)
        self.assertTrue(membership.is_primary)

    def test_user_can_belong_to_only_one_store(self):
        StoreUser.objects.create(store=self.store, user=self.store_user, is_primary=True)
        other_store = self.create_store(name="Other", category_name="Other Cat")
        with self.assertRaises(IntegrityError):
            StoreUser.objects.create(store=other_store, user=self.store_user)

    def test_only_one_primary_user_per_store(self):
        StoreUser.objects.create(store=self.store, user=self.store_user, is_primary=True)
        second_user = self.create_store_user_account(username="store-user-2")
        with self.assertRaises(IntegrityError):
            StoreUser.objects.create(store=self.store, user=second_user, is_primary=True)

    def test_multiple_non_primary_users_allowed(self):
        StoreUser.objects.create(store=self.store, user=self.store_user, is_primary=True)
        second_user = self.create_store_user_account(username="store-user-2")
        membership = StoreUser(store=self.store, user=second_user, is_primary=False)
        membership.full_clean()
        membership.save()
        self.assertEqual(self.store.store_users.count(), 2)


class StoreStatusHistoryModelTests(StoreModelTestMixin, TestCase):
    def setUp(self):
        self.store = self.create_store(category_name="History Cat")
        self.actor = User.objects.create_user(
            username="status-admin",
            email="status-admin@example.com",
            password="secure-password-123",
            role=Role.ADMIN,
            is_staff=True,
        )

    def test_status_history_records_transition(self):
        history = StoreStatusHistory.objects.create(
            store=self.store,
            old_status=StoreStatus.PENDING,
            new_status=StoreStatus.ACTIVE,
            changed_by=self.actor,
            reason="Approved after review",
            ip_address="127.0.0.1",
        )
        self.assertIn(self.store.store_code, str(history))
        self.assertIn(StoreStatus.ACTIVE, str(history))
        self.assertEqual(self.store.status_history.count(), 1)

    def test_old_status_may_be_blank_on_create(self):
        history = StoreStatusHistory(
            store=self.store,
            old_status="",
            new_status=StoreStatus.PENDING,
            changed_by=self.actor,
        )
        history.full_clean()
        history.save()
        self.assertEqual(history.old_status, "")


class StoreCodeConcurrencyTests(StoreModelTestMixin, TransactionTestCase):
    def test_save_retries_when_generated_code_collides(self):
        existing = self.create_store(category_name="Collision Cat")
        colliding_code = existing.store_code
        unique_code = "STUNIQUE01"

        address = self.create_address(line1="99 Collision St")
        category = self.create_category(name="Collision Retry")
        store = Store(
            name="Retry Store",
            store_type=StoreType.PARTNER_HOME,
            category=category,
            address=address,
            commission_percentage=Decimal("2.50"),
        )

        with mock.patch(
            "stores.services.generate_store_code",
            side_effect=[colliding_code, unique_code],
        ):
            store.save()

        store.refresh_from_db()
        self.assertEqual(store.store_code, unique_code)

    def test_generate_store_code_skips_existing_codes(self):
        existing = self.create_store(category_name="Skip Cat")
        with mock.patch(
            "stores.services._candidate_store_code",
            side_effect=[existing.store_code, "STNEVERUSED"],
        ):
            code = generate_store_code()
        self.assertEqual(code, "STNEVERUSED")


def _image_bytes(image_format="JPEG", size=(20, 20), color=(255, 0, 0)):
    from io import BytesIO

    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", size, color=color).save(buffer, format=image_format)
    return buffer.getvalue()


class StoreImageUploadTests(StoreModelTestMixin, TestCase):
    def setUp(self):
        self.store = self.create_store(category_name="Image Cat")

    def _uploaded(self, name, content, content_type=None):
        from django.core.files.uploadedfile import SimpleUploadedFile

        kwargs = {"name": name, "content": content}
        if content_type is not None:
            kwargs["content_type"] = content_type
        return SimpleUploadedFile(**kwargs)

    def test_valid_jpeg_png_and_webp_are_accepted(self):
        cases = (
            ("shop.jpg", "JPEG", "image/jpeg"),
            ("shop.jpeg", "JPEG", "image/jpeg"),
            ("shop.png", "PNG", "image/png"),
            ("shop.webp", "WEBP", "image/webp"),
        )
        for name, image_format, content_type in cases:
            with self.subTest(name=name):
                uploaded = self._uploaded(
                    name,
                    _image_bytes(image_format),
                    content_type=content_type,
                )
                validate_store_image(uploaded)

    def test_invalid_extension_is_rejected(self):
        uploaded = self._uploaded(
            "shop.gif",
            _image_bytes("GIF"),
            content_type="image/gif",
        )
        with self.assertRaises(ValidationError):
            validate_store_image(uploaded)

    def test_oversized_file_is_rejected(self):
        content = _image_bytes("JPEG") + (b"0" * (MAX_STORE_IMAGE_SIZE_BYTES + 1))
        uploaded = self._uploaded("huge.jpg", content, content_type="image/jpeg")
        with self.assertRaises(ValidationError) as ctx:
            validate_store_image(uploaded)
        self.assertIn("5 MB", str(ctx.exception))

    def test_extension_alone_is_not_trusted(self):
        uploaded = self._uploaded(
            "fake.jpg",
            b"not-an-image-at-all",
            content_type="image/jpeg",
        )
        with self.assertRaises(ValidationError):
            validate_store_image(uploaded)

    def test_mismatched_extension_and_content_is_rejected(self):
        uploaded = self._uploaded(
            "shop.png",
            _image_bytes("JPEG"),
            content_type="image/png",
        )
        with self.assertRaises(ValidationError):
            validate_store_image(uploaded)

    def test_path_traversal_filename_is_sanitized(self):
        path = store_image_upload_to(self.store, "../../evil.exe.jpg")
        self.assertTrue(path.startswith("stores/images/"))
        self.assertTrue(path.endswith(".jpg"))
        self.assertNotIn("..", path)
        self.assertNotIn("evil", path)

    def test_store_saves_image_under_safe_upload_path(self):
        uploaded = self._uploaded(
            "display.jpg",
            _image_bytes("JPEG"),
            content_type="image/jpeg",
        )
        self.store.image = uploaded
        self.store.full_clean()
        self.store.save()
        self.store.refresh_from_db()
        self.assertTrue(self.store.image.name.startswith("stores/images/"))
        self.assertTrue(self.store.image.name.endswith(".jpg"))


class StoreManagementPermissionTests(StoreModelTestMixin, TestCase):
    def setUp(self):
        from django.contrib.auth.models import Permission
        from django.urls import reverse

        self.Permission = Permission

        self.super_admin = User.objects.create_user(
            username="store-super",
            email="store-super@example.com",
            password="secure-password-123",
            role=Role.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        self.admin = User.objects.create_user(
            username="store-admin",
            email="store-admin@example.com",
            password="secure-password-123",
            role=Role.ADMIN,
            is_staff=True,
        )
        self.category = self.create_category(name="Perm Cat")
        self.store = self.create_store(category=self.category, name="Perm Store")
        self.membership = StoreUser.objects.create(
            store=self.store,
            user=self.create_store_user_account(username="perm-store-user"),
            is_primary=True,
        )


    def _perm(self, codename):
        return self.Permission.objects.get(
            codename=codename,
            content_type__app_label="stores",
        )

    def _login_admin_with(self, *codenames):
        for codename in codenames:
            self.admin.user_permissions.add(self._perm(codename))
        self.client.login(username="store-admin", password="secure-password-123")









    def test_custom_permissions_exist(self):
        self.assertTrue(
            self.Permission.objects.filter(
                codename="approve_store",
                content_type__app_label="stores",
            ).exists()
        )
        self.assertTrue(
            self.Permission.objects.filter(
                codename="suspend_store",
                content_type__app_label="stores",
            ).exists()
        )


class StoreManagementPortalTests(StoreModelTestMixin, TestCase):
    def setUp(self):
        from django.contrib.auth.models import Permission
        from django.urls import reverse

        from accounts.models import AdminAuditLog

        self.Permission = Permission
        self.reverse = reverse
        self.AdminAuditLog = AdminAuditLog

        self.super_admin = User.objects.create_user(
            username="portal-store-super",
            email="portal-store-super@example.com",
            password="secure-password-123",
            role=Role.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        self.admin = User.objects.create_user(
            username="portal-store-admin",
            email="portal-store-admin@example.com",
            password="secure-password-123",
            role=Role.ADMIN,
            is_staff=True,
        )
        self.category = self.create_category(name="Portal Cat")
        self.other_category = self.create_category(name="Other Cat")
        self.store = self.create_store(
            category=self.category,
            name="Alpha Mart",
            email="alpha@example.com",
            contact_phone="9000000001",
            store_type=StoreType.OWN_STORE,
        )
        self.primary = StoreUser.objects.create(
            store=self.store,
            user=self.create_store_user_account(
                username="alpha-primary",
                email="alpha-primary@example.com",
            ),
            is_primary=True,
            designation="Manager",
        )
        for codename in (
            "view_store",
            "add_store",
            "change_store",
            "approve_store",
            "suspend_store",
            "view_storeuser",
            "add_storeuser",
            "change_storeuser",
        ):
            self.admin.user_permissions.add(
                Permission.objects.get(
                    codename=codename,
                    content_type__app_label="stores",
                )
            )

    def _address_payload(self, prefix="address"):
        return {
            f"{prefix}-line1": "12 MG Road",
            f"{prefix}-line2": "",
            f"{prefix}-city": "Bengaluru",
            f"{prefix}-state": "Karnataka",
            f"{prefix}-postal_code": "560001",
            f"{prefix}-country": "India",
            f"{prefix}-latitude": "12.971600",
            f"{prefix}-longitude": "77.594600",
        }











    def test_django_admin_store_status_is_readonly(self):
        from stores.admin import StoreAdmin

        self.assertIn("status", StoreAdmin.readonly_fields)








class StorePortalAccessTests(StoreModelTestMixin, TestCase):
    def setUp(self):
        from django.urls import reverse

        self.reverse = reverse
        self.category = self.create_category(name="Portal Access Cat")
        self.store = self.create_store(
            category=self.category,
            name="Portal Access Store",
            status=StoreStatus.ACTIVE,
            email="portal-store@example.com",
            contact_phone="9111111111",
        )
        self.other_store = self.create_store(
            category=self.create_category(name="Other Portal Cat"),
            name="Other Portal Store",
            status=StoreStatus.ACTIVE,
            email="other-portal@example.com",
        )
        self.store_user = self.create_store_user_account(
            username="portal-access-user",
            email="portal-access-user@example.com",
        )
        self.membership = StoreUser.objects.create(
            store=self.store,
            user=self.store_user,
            is_primary=True,
            is_active=True,
            designation="Shift Lead",
        )
        self.other_user = self.create_store_user_account(
            username="other-portal-user",
            email="other-portal-user@example.com",
        )
        StoreUser.objects.create(
            store=self.other_store,
            user=self.other_user,
            is_primary=True,
            is_active=True,
        )











    def test_queryset_isolation_between_stores(self):
        from stores.decorators import portal_stores_queryset

        self.assertTrue(
            self.client.login(
                username="portal-access-user",
                password="secure-password-123",
            )
        )
        qs = portal_stores_queryset(self.store_user)
        self.assertEqual(list(qs.values_list("pk", flat=True)), [self.store.pk])
        self.assertNotIn(self.other_store.pk, qs.values_list("pk", flat=True))


class StoreIsolationTests(StoreModelTestMixin, TestCase):
    """
    Cross-store isolation matrix:

    Store A / Store User A, Store B / Store User B, plus Admin permission cases.
    Foreign store IDs must return 404 to avoid confirming another store exists.
    """

    def setUp(self):
        from django.contrib.auth.models import Permission
        from django.urls import reverse

        self.Permission = Permission
        self.reverse = reverse

        self.store_a = self.create_store(
            name="Store A",
            category_name="Isolation Cat A",
            status=StoreStatus.ACTIVE,
            contact_phone="9000000001",
            email="store-a@example.com",
        )
        self.store_b = self.create_store(
            name="Store B",
            category_name="Isolation Cat B",
            status=StoreStatus.ACTIVE,
            contact_phone="9000000002",
            email="store-b@example.com",
        )

        self.user_a = self.create_store_user_account(
            username="store-user-a",
            email="store-user-a@example.com",
        )
        self.user_b = self.create_store_user_account(
            username="store-user-b",
            email="store-user-b@example.com",
        )
        self.user_a2 = self.create_store_user_account(
            username="store-user-a2",
            email="store-user-a2@example.com",
        )

        self.membership_a = StoreUser.objects.create(
            store=self.store_a,
            user=self.user_a,
            is_primary=True,
            is_active=True,
            designation="Owner A",
        )
        self.membership_a2 = StoreUser.objects.create(
            store=self.store_a,
            user=self.user_a2,
            is_primary=False,
            is_active=True,
            designation="Staff A",
        )
        self.membership_b = StoreUser.objects.create(
            store=self.store_b,
            user=self.user_b,
            is_primary=True,
            is_active=True,
            designation="Owner B",
        )

        self.admin = User.objects.create_user(
            username="isolation-admin",
            email="isolation-admin@example.com",
            password="secure-password-123",
            role=Role.ADMIN,
            is_staff=True,
        )
        self.super_admin = User.objects.create_user(
            username="isolation-super",
            email="isolation-super@example.com",
            password="secure-password-123",
            role=Role.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )


    def _perm(self, codename):
        return self.Permission.objects.get(
            codename=codename,
            content_type__app_label="stores",
        )

    def _login_portal(self, username):
        self.assertTrue(
            self.client.login(username=username, password="secure-password-123")
        )

    def _login_admin_with(self, *codenames):
        self.admin.user_permissions.clear()
        for codename in codenames:
            self.admin.user_permissions.add(self._perm(codename))
        self.assertTrue(
            self.client.login(
                username="isolation-admin",
                password="secure-password-123",
            )
        )

    def _store_edit_payload(self, store, **overrides):
        address = store.address
        payload = {
            "name": store.name,
            "description": store.description or "",
            "contact_phone": store.contact_phone or "",
            "alternative_phone": store.alternative_phone or "",
            "email": store.email or "",
            "store_type": store.store_type,
            "category": store.category_id,
            "commission_percentage": str(store.commission_percentage),
            "is_active": "on" if store.is_active else "",
            "address-line1": address.line1,
            "address-line2": address.line2 or "",
            "address-city": address.city,
            "address-state": address.state,
            "address-postal_code": address.postal_code,
            "address-country": address.country,
            "address-latitude": str(address.latitude),
            "address-longitude": str(address.longitude),
        }
        payload.update(overrides)
        if not payload.get("is_active"):
            payload.pop("is_active", None)
        return payload













