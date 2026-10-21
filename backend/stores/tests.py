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

        self.list_url = reverse("stores:store_list")
        self.detail_url = reverse("stores:store_detail", kwargs={"pk": self.store.pk})
        self.create_url = reverse("stores:store_create")
        self.edit_url = reverse("stores:store_edit", kwargs={"pk": self.store.pk})
        self.change_status_url = reverse(
            "stores:store_change_status", kwargs={"pk": self.store.pk}
        )
        self.users_url = reverse("stores:store_user_list", kwargs={"pk": self.store.pk})
        self.user_create_url = reverse(
            "stores:store_user_create", kwargs={"pk": self.store.pk}
        )
        self.user_edit_url = reverse(
            "stores:store_user_edit",
            kwargs={"pk": self.store.pk, "user_id": self.membership.user_id},
        )
        self.user_toggle_url = reverse(
            "stores:store_user_toggle_status",
            kwargs={"pk": self.store.pk, "user_id": self.membership.user_id},
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

    def test_super_admin_bypasses_store_permission_checks(self):
        self.client.login(username="store-super", password="secure-password-123")
        self.assertEqual(self.client.get(self.list_url).status_code, 200)
        self.assertEqual(self.client.get(self.detail_url).status_code, 200)
        self.assertEqual(self.client.get(self.create_url).status_code, 200)
        self.assertEqual(self.client.get(self.edit_url).status_code, 200)
        self.assertEqual(self.client.get(self.users_url).status_code, 200)
        self.assertEqual(self.client.get(self.user_create_url).status_code, 200)
        self.assertEqual(self.client.get(self.user_edit_url).status_code, 200)

        approve = self.client.post(
            self.change_status_url,
            {"new_status": StoreStatus.ACTIVE, "reason": "ok"},
        )
        self.assertEqual(approve.status_code, 302)
        self.store.refresh_from_db()
        self.assertEqual(self.store.status, StoreStatus.ACTIVE)

        suspend = self.client.post(
            self.change_status_url,
            {"new_status": StoreStatus.SUSPENDED, "reason": "pause"},
        )
        self.assertEqual(suspend.status_code, 302)
        self.store.refresh_from_db()
        self.assertEqual(self.store.status, StoreStatus.SUSPENDED)

    def test_admin_requires_view_store_to_list_and_detail(self):
        self.client.login(username="store-admin", password="secure-password-123")
        self.assertEqual(self.client.get(self.list_url).status_code, 403)
        self.assertEqual(self.client.get(self.detail_url).status_code, 403)

        self._login_admin_with("view_store")
        self.assertEqual(self.client.get(self.list_url).status_code, 200)
        self.assertEqual(self.client.get(self.detail_url).status_code, 200)

    def test_admin_requires_add_store_to_create(self):
        self._login_admin_with("view_store")
        self.assertEqual(self.client.get(self.create_url).status_code, 403)

        self.admin.user_permissions.add(self._perm("add_store"))
        self.assertEqual(self.client.get(self.create_url).status_code, 200)

    def test_admin_requires_change_store_to_edit(self):
        self._login_admin_with("view_store")
        self.assertEqual(self.client.get(self.edit_url).status_code, 403)

        self.admin.user_permissions.add(self._perm("change_store"))
        self.assertEqual(self.client.get(self.edit_url).status_code, 200)

    def test_admin_requires_approve_store_to_approve_or_reject(self):
        self._login_admin_with("view_store")
        response = self.client.post(
            self.change_status_url,
            {"new_status": StoreStatus.ACTIVE, "reason": "approve"},
        )
        self.assertEqual(response.status_code, 403)

        self.admin.user_permissions.add(self._perm("approve_store"))
        approve = self.client.post(
            self.change_status_url,
            {"new_status": StoreStatus.ACTIVE, "reason": "approve"},
        )
        self.assertEqual(approve.status_code, 302)
        self.store.refresh_from_db()
        self.assertEqual(self.store.status, StoreStatus.ACTIVE)

        # Reset to PENDING via an allowed path: ACTIVE -> SUSPENDED -> not to REJECTED.
        # Rejection is only allowed from PENDING.
        self.store.status = StoreStatus.PENDING
        self.store.save(update_fields=["status"])
        reject = self.client.post(
            self.change_status_url,
            {"new_status": StoreStatus.REJECTED, "reason": "Incomplete documents"},
        )
        self.assertEqual(reject.status_code, 302)
        self.store.refresh_from_db()
        self.assertEqual(self.store.status, StoreStatus.REJECTED)

    def test_admin_requires_suspend_store_to_suspend(self):
        self.store.status = StoreStatus.ACTIVE
        self.store.save(update_fields=["status"])
        self._login_admin_with("view_store")
        response = self.client.post(
            self.change_status_url,
            {"new_status": StoreStatus.SUSPENDED, "reason": "suspend"},
        )
        self.assertEqual(response.status_code, 403)

        self.admin.user_permissions.add(self._perm("suspend_store"))
        suspend = self.client.post(
            self.change_status_url,
            {"new_status": StoreStatus.SUSPENDED, "reason": "suspend"},
        )
        self.assertEqual(suspend.status_code, 302)
        self.store.refresh_from_db()
        self.assertEqual(self.store.status, StoreStatus.SUSPENDED)

    def test_admin_requires_storeuser_permissions(self):
        self._login_admin_with("view_store")
        self.assertEqual(self.client.get(self.users_url).status_code, 403)
        self.assertEqual(self.client.get(self.user_create_url).status_code, 403)
        self.assertEqual(self.client.get(self.user_edit_url).status_code, 403)
        self.assertEqual(self.client.post(self.user_toggle_url).status_code, 403)

        self.admin.user_permissions.add(self._perm("view_storeuser"))
        self.assertEqual(self.client.get(self.users_url).status_code, 200)

        self.admin.user_permissions.add(self._perm("add_storeuser"))
        self.assertEqual(self.client.get(self.user_create_url).status_code, 200)

        self.admin.user_permissions.add(self._perm("change_storeuser"))
        self.assertEqual(self.client.get(self.user_edit_url).status_code, 200)
        toggle = self.client.post(self.user_toggle_url)
        self.assertEqual(toggle.status_code, 302)
        self.membership.refresh_from_db()
        self.assertFalse(self.membership.is_active)

    def test_status_actions_require_post(self):
        self.client.login(username="store-super", password="secure-password-123")
        self.assertEqual(self.client.get(self.change_status_url).status_code, 405)
        self.assertEqual(self.client.get(self.user_toggle_url).status_code, 405)

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

    def test_list_search_filters_and_columns(self):
        other = self.create_store(
            category=self.other_category,
            name="Beta Mart",
            email="beta@example.com",
            contact_phone="9000000002",
            store_type=StoreType.PARTNER_STORE,
            status=StoreStatus.ACTIVE,
            is_active=False,
        )
        self.client.login(username="portal-store-admin", password="secure-password-123")
        response = self.client.get(
            self.reverse("stores:store_list"),
            {
                "q": "alpha@",
                "store_type": StoreType.OWN_STORE,
                "category": self.category.pk,
                "status": StoreStatus.PENDING,
                "is_active": "true",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.store.store_code)
        self.assertContains(response, "alpha-primary")
        self.assertNotContains(response, other.store_code)
        self.assertContains(response, "Contact")
        self.assertContains(response, "Primary user")

    def test_create_store_without_primary_user_defaults_to_pending(self):
        self.client.login(username="portal-store-admin", password="secure-password-123")
        # Remove approve so activate checkbox is unavailable / ignored path
        self.admin.user_permissions.remove(
            self.Permission.objects.get(
                codename="approve_store",
                content_type__app_label="stores",
            )
        )
        payload = {
            "name": "Gamma Mart",
            "description": "Neighborhood store",
            "contact_phone": "9000000003",
            "alternative_phone": "9000000004",
            "email": "gamma@example.com",
            "store_type": StoreType.PARTNER_HOME,
            "category": self.category.pk,
            "commission_percentage": "7.50",
            "is_active": "on",
            "user-create_primary_user": "",
            **self._address_payload(),
        }
        response = self.client.post(self.reverse("stores:store_create"), payload)
        self.assertEqual(response.status_code, 302)
        store = Store.objects.get(email="gamma@example.com")
        self.assertEqual(store.status, StoreStatus.PENDING)
        self.assertFalse(store.store_users.exists())
        self.assertTrue(
            self.AdminAuditLog.objects.filter(
                action=self.AdminAuditLog.Action.STORE_CREATED,
                metadata__store_code=store.store_code,
            ).exists()
        )
        self.assertEqual(store.status_history.count(), 1)
        # Password must never appear in response/redirect URL
        self.assertNotIn("password", response.url.lower())

    def test_authorized_approver_can_activate_on_create_with_primary_user(self):
        self.client.login(username="portal-store-super", password="secure-password-123")
        payload = {
            "name": "Delta Mart",
            "description": "Approved store",
            "contact_phone": "9000000005",
            "alternative_phone": "",
            "email": "delta@example.com",
            "store_type": StoreType.OWN_STORE,
            "category": self.category.pk,
            "commission_percentage": "10.00",
            "is_active": "on",
            "activate_on_create": "on",
            "user-create_primary_user": "on",
            "user-first_name": "Dee",
            "user-last_name": "Primary",
            "user-username": "delta-primary",
            "user-email": "delta-primary@example.com",
            "user-phone_number": "9000000006",
            "user-password": "ComplexPass123!",
            "user-confirm_password": "ComplexPass123!",
            "user-designation": "Owner",
            **self._address_payload(),
        }
        response = self.client.post(self.reverse("stores:store_create"), payload)
        self.assertEqual(response.status_code, 302)
        store = Store.objects.get(email="delta@example.com")
        self.assertEqual(store.status, StoreStatus.ACTIVE)
        membership = store.store_users.get(is_primary=True)
        self.assertEqual(membership.user.username, "delta-primary")
        self.assertEqual(membership.user.role, Role.STORE_USER)
        self.assertFalse(membership.user.is_staff)
        self.assertFalse(membership.user.is_superuser)
        self.assertEqual(membership.designation, "Owner")
        self.assertTrue(membership.user.check_password("ComplexPass123!"))
        follow = self.client.get(response.url)
        self.assertNotContains(follow, "ComplexPass123!")
        self.assertTrue(
            self.AdminAuditLog.objects.filter(
                action=self.AdminAuditLog.Action.STORE_USER_CREATED,
                target_user=membership.user,
            ).exists()
        )

    def test_create_rejects_invalid_username_characters(self):
        self.client.login(username="portal-store-admin", password="secure-password-123")
        payload = {
            "name": "Invalid User Mart",
            "description": "",
            "contact_phone": "9000000091",
            "alternative_phone": "",
            "email": "invalid-user-mart@example.com",
            "store_type": StoreType.OWN_STORE,
            "category": self.category.pk,
            "commission_percentage": "5.00",
            "is_active": "on",
            "user-create_primary_user": "on",
            "user-first_name": "Bad",
            "user-last_name": "Name",
            "user-username": "bad user!",
            "user-email": "bad-user@example.com",
            "user-phone_number": "",
            "user-password": "ComplexPass123!",
            "user-confirm_password": "ComplexPass123!",
            "user-designation": "Owner",
            **self._address_payload(),
        }
        before_count = Store.objects.count()
        response = self.client.post(self.reverse("stores:store_create"), payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Store.objects.count(), before_count)
        self.assertContains(response, "Enter a valid username")
        form = response.context["user_form"]
        self.assertIn("username", form.errors)

    def test_create_rejects_duplicate_username_email_phone(self):
        self.client.login(username="portal-store-admin", password="secure-password-123")
        payload = {
            "name": "Echo Mart",
            "description": "",
            "contact_phone": "9000000007",
            "alternative_phone": "",
            "email": "echo@example.com",
            "store_type": StoreType.OWN_STORE,
            "category": self.category.pk,
            "commission_percentage": "1.00",
            "is_active": "on",
            "user-create_primary_user": "on",
            "user-username": "alpha-primary",
            "user-email": "alpha-primary@example.com",
            "user-phone_number": self.primary.user.phone_number or "9000000099",
            "user-password": "ComplexPass123!",
            "user-confirm_password": "ComplexPass123!",
            "user-designation": "Staff",
            **self._address_payload(),
        }
        # Ensure phone collision
        self.primary.user.phone_number = "9000000099"
        self.primary.user.save(update_fields=["phone_number"])
        payload["user-phone_number"] = "9000000099"
        response = self.client.post(self.reverse("stores:store_create"), payload)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already in use")
        self.assertFalse(Store.objects.filter(email="echo@example.com").exists())

    def test_change_status_records_history_and_audit(self):
        self.client.login(username="portal-store-admin", password="secure-password-123")
        response = self.client.post(
            self.reverse("stores:store_change_status", kwargs={"pk": self.store.pk}),
            {"new_status": StoreStatus.ACTIVE, "reason": "Looks good"},
        )
        self.assertEqual(response.status_code, 302)
        self.store.refresh_from_db()
        self.assertEqual(self.store.status, StoreStatus.ACTIVE)
        self.assertTrue(
            self.store.status_history.filter(
                new_status=StoreStatus.ACTIVE,
                reason="Looks good",
            ).exists()
        )
        self.assertTrue(
            self.AdminAuditLog.objects.filter(
                action=self.AdminAuditLog.Action.STORE_STATUS_CHANGED,
                metadata__store_code=self.store.store_code,
            ).exists()
        )

    def test_audit_ip_ignores_spoofed_x_forwarded_for(self):
        self.client.login(username="portal-store-admin", password="secure-password-123")
        response = self.client.post(
            self.reverse("stores:store_change_status", kwargs={"pk": self.store.pk}),
            {"new_status": StoreStatus.ACTIVE, "reason": "IP spoof check"},
            HTTP_X_FORWARDED_FOR="203.0.113.50, 198.51.100.1",
            REMOTE_ADDR="127.0.0.1",
        )
        self.assertEqual(response.status_code, 302)
        audit = self.AdminAuditLog.objects.filter(
            action=self.AdminAuditLog.Action.STORE_STATUS_CHANGED,
            metadata__store_code=self.store.store_code,
        ).latest("created_at")
        self.assertEqual(audit.ip_address, "127.0.0.1")
        self.assertNotEqual(audit.ip_address, "203.0.113.50")
        history = self.store.status_history.filter(
            new_status=StoreStatus.ACTIVE,
            reason="IP spoof check",
        ).latest("created_at")
        self.assertEqual(history.ip_address, "127.0.0.1")

    def test_store_user_edit_and_toggle(self):
        self.client.login(username="portal-store-admin", password="secure-password-123")
        edit_url = self.reverse(
            "stores:store_user_edit",
            kwargs={"pk": self.store.pk, "user_id": self.primary.user_id},
        )
        response = self.client.post(
            edit_url,
            {
                "first_name": "Updated",
                "last_name": "Primary",
                "username": "alpha-primary",
                "email": "alpha-primary@example.com",
                "phone_number": "9000000010",
                "designation": "Lead Manager",
                "is_primary": "on",
                "password": "",
                "confirm_password": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.primary.refresh_from_db()
        self.primary.user.refresh_from_db()
        self.assertEqual(self.primary.designation, "Lead Manager")
        self.assertEqual(self.primary.user.first_name, "Updated")
        self.assertTrue(
            self.AdminAuditLog.objects.filter(
                action=self.AdminAuditLog.Action.STORE_USER_UPDATED,
                target_user=self.primary.user,
            ).exists()
        )

        toggle_url = self.reverse(
            "stores:store_user_toggle_status",
            kwargs={"pk": self.store.pk, "user_id": self.primary.user_id},
        )
        toggle = self.client.post(toggle_url)
        self.assertEqual(toggle.status_code, 302)
        self.primary.refresh_from_db()
        self.assertFalse(self.primary.is_active)
        self.assertTrue(
            self.AdminAuditLog.objects.filter(
                action=self.AdminAuditLog.Action.STORE_USER_DEACTIVATED,
                target_user=self.primary.user,
            ).exists()
        )

    def test_primary_reassignment_demotes_previous_primary(self):
        secondary_user = self.create_store_user_account(
            username="alpha-secondary",
            email="alpha-secondary@example.com",
        )
        secondary = StoreUser.objects.create(
            store=self.store,
            user=secondary_user,
            is_primary=False,
            designation="Associate",
        )
        self.client.login(username="portal-store-admin", password="secure-password-123")
        edit_url = self.reverse(
            "stores:store_user_edit",
            kwargs={"pk": self.store.pk, "user_id": secondary.user_id},
        )
        response = self.client.post(
            edit_url,
            {
                "first_name": "Sec",
                "last_name": "Ondary",
                "username": "alpha-secondary",
                "email": "alpha-secondary@example.com",
                "phone_number": "",
                "designation": "New Lead",
                "is_primary": "on",
                "password": "",
                "confirm_password": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.primary.refresh_from_db()
        secondary.refresh_from_db()
        self.assertFalse(self.primary.is_primary)
        self.assertTrue(secondary.is_primary)
        self.assertEqual(
            StoreUser.objects.filter(store=self.store, is_primary=True).count(),
            1,
        )

    def test_create_store_user_as_primary_transfers_in_one_transaction(self):
        self.client.login(username="portal-store-admin", password="secure-password-123")
        create_url = self.reverse(
            "stores:store_user_create", kwargs={"pk": self.store.pk}
        )
        response = self.client.post(
            create_url,
            {
                "first_name": "New",
                "last_name": "Primary",
                "username": "alpha-new-primary",
                "email": "alpha-new-primary@example.com",
                "phone_number": "",
                "designation": "Director",
                "is_primary": "on",
                "password": "secure-password-123",
                "confirm_password": "secure-password-123",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.primary.refresh_from_db()
        self.assertFalse(self.primary.is_primary)
        new_primary = StoreUser.objects.get(user__username="alpha-new-primary")
        self.assertTrue(new_primary.is_primary)
        self.assertEqual(
            StoreUser.objects.filter(store=self.store, is_primary=True).count(),
            1,
        )

    def test_django_admin_store_status_is_readonly(self):
        from stores.admin import StoreAdmin

        self.assertIn("status", StoreAdmin.readonly_fields)


class StoreStatusManagementTests(StoreModelTestMixin, TestCase):
    def setUp(self):
        from django.contrib.auth.models import Permission
        from django.urls import reverse

        from accounts.models import AdminAuditLog

        self.reverse = reverse
        self.AdminAuditLog = AdminAuditLog
        self.Permission = Permission

        self.super_admin = User.objects.create_user(
            username="status-super",
            email="status-super@example.com",
            password="secure-password-123",
            role=Role.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        self.approver = User.objects.create_user(
            username="status-approver",
            email="status-approver@example.com",
            password="secure-password-123",
            role=Role.ADMIN,
            is_staff=True,
        )
        self.suspender = User.objects.create_user(
            username="status-suspender",
            email="status-suspender@example.com",
            password="secure-password-123",
            role=Role.ADMIN,
            is_staff=True,
        )
        self.viewer = User.objects.create_user(
            username="status-viewer",
            email="status-viewer@example.com",
            password="secure-password-123",
            role=Role.ADMIN,
            is_staff=True,
        )
        for user, perms in (
            (self.approver, ("view_store", "approve_store")),
            (self.suspender, ("view_store", "suspend_store")),
            (self.viewer, ("view_store",)),
        ):
            for codename in perms:
                user.user_permissions.add(
                    Permission.objects.get(
                        codename=codename,
                        content_type__app_label="stores",
                    )
                )

        self.category = self.create_category(name="Status Cat")
        self.store = self.create_store(category=self.category, name="Status Store")
        self.store_user = self.create_store_user_account(username="status-portal-user")
        self.membership = StoreUser.objects.create(
            store=self.store,
            user=self.store_user,
            is_primary=True,
            is_active=True,
        )
        self.change_url = reverse(
            "stores:store_change_status", kwargs={"pk": self.store.pk}
        )
        self.dashboard_url = reverse("stores:store_portal_dashboard")
        self.login_url = reverse("stores:store_portal_login")

    def _change(self, username, new_status, reason=""):
        self.client.login(username=username, password="secure-password-123")
        return self.client.post(
            self.change_url,
            {"new_status": new_status, "reason": reason},
        )

    def test_pending_to_active_requires_approve_permission(self):
        denied = self._change("status-viewer", StoreStatus.ACTIVE)
        self.assertEqual(denied.status_code, 403)
        allowed = self._change("status-approver", StoreStatus.ACTIVE)
        self.assertEqual(allowed.status_code, 302)
        self.store.refresh_from_db()
        self.assertEqual(self.store.status, StoreStatus.ACTIVE)
        history = self.store.status_history.latest("created_at")
        self.assertEqual(history.old_status, StoreStatus.PENDING)
        self.assertEqual(history.new_status, StoreStatus.ACTIVE)
        self.assertEqual(history.changed_by.username, "status-approver")

    def test_pending_to_rejected_requires_reason_and_approve_permission(self):
        missing_reason = self._change("status-approver", StoreStatus.REJECTED, reason="")
        self.assertEqual(missing_reason.status_code, 302)
        self.store.refresh_from_db()
        self.assertEqual(self.store.status, StoreStatus.PENDING)

        denied = self._change(
            "status-suspender",
            StoreStatus.REJECTED,
            reason="Missing documents",
        )
        self.assertEqual(denied.status_code, 403)

        allowed = self._change(
            "status-approver",
            StoreStatus.REJECTED,
            reason="Missing documents",
        )
        self.assertEqual(allowed.status_code, 302)
        self.store.refresh_from_db()
        self.assertEqual(self.store.status, StoreStatus.REJECTED)
        history = self.store.status_history.latest("created_at")
        self.assertEqual(history.reason, "Missing documents")
        self.assertEqual(history.old_status, StoreStatus.PENDING)
        self.assertEqual(history.new_status, StoreStatus.REJECTED)

    def test_rejected_to_pending_requires_approve_permission(self):
        self.store.status = StoreStatus.REJECTED
        self.store.save(update_fields=["status"])
        denied = self._change("status-viewer", StoreStatus.PENDING)
        self.assertEqual(denied.status_code, 403)
        allowed = self._change("status-approver", StoreStatus.PENDING)
        self.assertEqual(allowed.status_code, 302)
        self.store.refresh_from_db()
        self.assertEqual(self.store.status, StoreStatus.PENDING)

    def test_active_to_suspended_requires_reason_and_suspend_permission(self):
        self.store.status = StoreStatus.ACTIVE
        self.store.save(update_fields=["status"])

        missing_reason = self._change("status-suspender", StoreStatus.SUSPENDED, "")
        self.assertEqual(missing_reason.status_code, 302)
        self.store.refresh_from_db()
        self.assertEqual(self.store.status, StoreStatus.ACTIVE)

        denied = self._change(
            "status-approver",
            StoreStatus.SUSPENDED,
            reason="Policy violation",
        )
        self.assertEqual(denied.status_code, 403)

        allowed = self._change(
            "status-suspender",
            StoreStatus.SUSPENDED,
            reason="Policy violation",
        )
        self.assertEqual(allowed.status_code, 302)
        self.store.refresh_from_db()
        self.assertEqual(self.store.status, StoreStatus.SUSPENDED)
        history = self.store.status_history.latest("created_at")
        self.assertEqual(history.reason, "Policy violation")
        self.assertEqual(history.changed_by.username, "status-suspender")

    def test_suspended_to_active_requires_approve_permission(self):
        self.store.status = StoreStatus.SUSPENDED
        self.store.save(update_fields=["status"])
        denied = self._change("status-suspender", StoreStatus.ACTIVE)
        self.assertEqual(denied.status_code, 403)
        allowed = self._change("status-approver", StoreStatus.ACTIVE)
        self.assertEqual(allowed.status_code, 302)
        self.store.refresh_from_db()
        self.assertEqual(self.store.status, StoreStatus.ACTIVE)

    def test_invalid_transitions_are_rejected(self):
        invalid_cases = (
            (StoreStatus.PENDING, StoreStatus.SUSPENDED),
            (StoreStatus.ACTIVE, StoreStatus.REJECTED),
            (StoreStatus.ACTIVE, StoreStatus.PENDING),
            (StoreStatus.REJECTED, StoreStatus.ACTIVE),
            (StoreStatus.SUSPENDED, StoreStatus.REJECTED),
            (StoreStatus.SUSPENDED, StoreStatus.PENDING),
        )
        for current, target in invalid_cases:
            with self.subTest(current=current, target=target):
                self.store.status = current
                self.store.save(update_fields=["status"])
                before_count = self.store.status_history.count()
                response = self._change(
                    "status-super",
                    target,
                    reason="attempt",
                )
                self.assertEqual(response.status_code, 302)
                self.store.refresh_from_db()
                self.assertEqual(self.store.status, current)
                self.assertEqual(self.store.status_history.count(), before_count)

    def test_status_change_requires_post(self):
        self.client.login(username="status-super", password="secure-password-123")
        self.assertEqual(self.client.get(self.change_url).status_code, 405)

    def test_suspension_blocks_store_portal_without_deleting_users(self):
        self.store.status = StoreStatus.ACTIVE
        self.store.save(update_fields=["status"])
        self.assertTrue(
            self.client.login(
                username="status-portal-user",
                password="secure-password-123",
            )
        )
        self.assertEqual(self.client.get(self.dashboard_url).status_code, 200)

        self.client.logout()
        self._change(
            "status-suspender",
            StoreStatus.SUSPENDED,
            reason="Temporary hold",
        )
        self.membership.refresh_from_db()
        self.assertTrue(StoreUser.objects.filter(pk=self.membership.pk).exists())
        self.assertTrue(self.membership.is_active)

        self.assertTrue(
            self.client.login(
                username="status-portal-user",
                password="secure-password-123",
            )
        )
        self.assertEqual(self.client.get(self.dashboard_url).status_code, 403)
        login_response = self.client.post(
            self.login_url,
            {"username": "status-portal-user", "password": "secure-password-123"},
        )
        self.assertEqual(login_response.status_code, 200)
        self.assertContains(login_response, "suspended")

    def test_activation_restores_store_portal_for_active_users(self):
        self.store.status = StoreStatus.SUSPENDED
        self.store.save(update_fields=["status"])
        self.assertTrue(
            self.client.login(
                username="status-portal-user",
                password="secure-password-123",
            )
        )
        self.assertEqual(self.client.get(self.dashboard_url).status_code, 403)

        self.client.logout()
        self._change("status-approver", StoreStatus.ACTIVE)
        self.assertTrue(
            self.client.login(
                username="status-portal-user",
                password="secure-password-123",
            )
        )
        self.assertEqual(self.client.get(self.dashboard_url).status_code, 200)

    def test_inactive_membership_remains_blocked_after_activation(self):
        self.store.status = StoreStatus.ACTIVE
        self.store.save(update_fields=["status"])
        self.membership.is_active = False
        self.membership.save(update_fields=["is_active"])
        self.assertTrue(
            self.client.login(
                username="status-portal-user",
                password="secure-password-123",
            )
        )
        self.assertEqual(self.client.get(self.dashboard_url).status_code, 403)


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
        self.login_url = reverse("stores:store_portal_login")
        self.logout_url = reverse("stores:store_portal_logout")
        self.dashboard_url = reverse("stores:store_portal_dashboard")
        self.profile_url = reverse("stores:store_portal_profile")

    def _login_portal(self, username="portal-access-user"):
        return self.client.post(
            self.login_url,
            {"username": username, "password": "secure-password-123"},
        )

    def test_active_store_user_can_login_and_see_dashboard(self):
        response = self._login_portal()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, self.dashboard_url)
        dashboard = self.client.get(self.dashboard_url)
        self.assertEqual(dashboard.status_code, 200)
        self.assertContains(dashboard, self.store.name)
        self.assertContains(dashboard, self.store.store_code)
        self.assertContains(dashboard, self.store.get_store_type_display())
        self.assertContains(dashboard, "Active")
        self.assertContains(dashboard, self.category.name)
        self.assertContains(dashboard, "9111111111")
        self.assertContains(dashboard, self.store.address.city)
        self.assertContains(dashboard, "Shift Lead")
        self.assertContains(dashboard, "Products")
        self.assertContains(dashboard, "Inventory")
        self.assertContains(dashboard, "Orders")
        self.assertContains(dashboard, "Total Store Products:")
        self.assertContains(dashboard, "Draft Products:")
        self.assertContains(dashboard, "Pending Products:")
        self.assertContains(dashboard, "Approved Products:")
        self.assertContains(dashboard, "Rejected Products:")
        self.assertContains(dashboard, "Low-stock Products:")
        self.assertContains(dashboard, "Total inventory Products:")
        self.assertContains(dashboard, "In-stock Products:")
        self.assertContains(dashboard, "Out-of-stock Products:")
        self.assertContains(dashboard, "Expired Products:")
        self.assertContains(dashboard, "Products expiring within 30 days:")
        self.assertContains(dashboard, "Pending StoreOrders:")
        self.assertContains(dashboard, "Accepted StoreOrders:")
        self.assertContains(dashboard, "Processing StoreOrders:")
        self.assertContains(dashboard, "Ready StoreOrders:")
        self.assertContains(dashboard, "Open Products")
        self.assertContains(dashboard, "Open Inventory")
        self.assertContains(dashboard, "Open Orders")
        self.assertNotContains(dashboard, "Coming Soon")
        self.assertEqual(dashboard.context["product_stats"]["total"], 0)
        self.assertEqual(dashboard.context["inventory_stats"]["total"], 0)
        self.assertEqual(dashboard.context["order_stats"]["pending"], 0)

    def test_non_store_user_roles_cannot_login(self):
        User.objects.create_user(
            username="admin-portal-try",
            email="admin-portal-try@example.com",
            password="secure-password-123",
            role=Role.ADMIN,
            is_staff=True,
        )
        response = self._login_portal("admin-portal-try")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Only Store Users")

    def test_inactive_user_cannot_login(self):
        self.store_user.is_active = False
        self.store_user.save(update_fields=["is_active"])
        response = self._login_portal()
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_inactive_membership_cannot_login(self):
        self.membership.is_active = False
        self.membership.save(update_fields=["is_active"])
        response = self._login_portal()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No active store membership")

    def test_pending_rejected_suspended_and_inactive_store_denied(self):
        cases = (
            (StoreStatus.PENDING, True, "pending"),
            (StoreStatus.REJECTED, True, "rejected"),
            (StoreStatus.SUSPENDED, True, "suspended"),
            (StoreStatus.ACTIVE, False, "inactive"),
        )
        for status, is_active, needle in cases:
            with self.subTest(status=status, is_active=is_active):
                self.store.status = status
                self.store.is_active = is_active
                self.store.save(update_fields=["status", "is_active"])
                response = self._login_portal()
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, needle)

    def test_logout_requires_post(self):
        self._login_portal()
        self.assertEqual(self.client.get(self.logout_url).status_code, 405)
        response = self.client.post(self.logout_url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, self.login_url)

    def test_anonymous_redirected_to_store_login(self):
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/store/login/", response.url)

    def test_profile_updates_allowed_fields_only(self):
        self._login_portal()
        original_code = self.store.store_code
        original_type = self.store.store_type
        original_status = self.store.status
        original_commission = self.store.commission_percentage
        response = self.client.post(
            self.profile_url,
            {
                "first_name": "Pat",
                "last_name": "Porter",
                "phone_number": "9222222222",
                "designation": "Manager",
                "contact_phone": "9333333333",
                "alternative_phone": "9444444444",
                "email": "updated-store@example.com",
                "description": "Updated description",
                "store_code": "HACKED",
                "store_type": StoreType.PARTNER_HOME,
                "status": StoreStatus.SUSPENDED,
                "commission_percentage": "99.99",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.store.refresh_from_db()
        self.store_user.refresh_from_db()
        self.membership.refresh_from_db()
        self.assertEqual(self.store.store_code, original_code)
        self.assertEqual(self.store.store_type, original_type)
        self.assertEqual(self.store.status, original_status)
        self.assertEqual(self.store.commission_percentage, original_commission)
        self.assertEqual(self.store.contact_phone, "9333333333")
        self.assertEqual(self.store.email, "updated-store@example.com")
        self.assertEqual(self.store_user.first_name, "Pat")
        self.assertEqual(self.membership.designation, "Manager")

    def test_profile_rejects_foreign_store_id(self):
        self._login_portal()
        response = self.client.get(f"{self.profile_url}?store_id={self.other_store.pk}")
        self.assertEqual(response.status_code, 404)
        response = self.client.post(
            self.profile_url,
            {
                "store_id": self.other_store.pk,
                "first_name": "Nope",
                "last_name": "",
                "phone_number": "",
                "designation": "",
                "contact_phone": "9555555555",
                "alternative_phone": "",
                "email": "hack@example.com",
                "description": "",
            },
        )
        self.assertEqual(response.status_code, 404)
        self.other_store.refresh_from_db()
        self.assertNotEqual(self.other_store.contact_phone, "9555555555")

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

        self.dashboard_url = reverse("stores:store_portal_dashboard")
        self.profile_url = reverse("stores:store_portal_profile")
        self.login_url = reverse("stores:store_portal_login")
        self.store_a_detail_url = reverse(
            "stores:store_detail", kwargs={"pk": self.store_a.pk}
        )
        self.store_b_detail_url = reverse(
            "stores:store_detail", kwargs={"pk": self.store_b.pk}
        )
        self.store_b_edit_url = reverse(
            "stores:store_edit", kwargs={"pk": self.store_b.pk}
        )
        self.store_a_edit_url = reverse(
            "stores:store_edit", kwargs={"pk": self.store_a.pk}
        )
        self.store_b_users_url = reverse(
            "stores:store_user_list", kwargs={"pk": self.store_b.pk}
        )
        self.store_b_user_edit_url = reverse(
            "stores:store_user_edit",
            kwargs={"pk": self.store_b.pk, "user_id": self.user_b.pk},
        )
        self.store_b_user_create_url = reverse(
            "stores:store_user_create", kwargs={"pk": self.store_b.pk}
        )
        self.store_a_change_status_url = reverse(
            "stores:store_change_status", kwargs={"pk": self.store_a.pk}
        )
        self.store_list_url = reverse("stores:store_list")

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

    def test_user_a_can_view_store_a_dashboard(self):
        self._login_portal("store-user-a")
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.store_a.name)
        self.assertContains(response, self.store_a.store_code)
        self.assertNotContains(response, self.store_b.store_code)

    def test_user_a_cannot_view_store_b_by_changing_url_id(self):
        from django.http import Http404

        from stores.decorators import get_portal_store_or_404

        self._login_portal("store-user-a")

        with self.assertRaises(Http404):
            get_portal_store_or_404(self.user_a, store_id=self.store_b.pk)

        response = self.client.get(f"{self.profile_url}?store_id={self.store_b.pk}")
        self.assertEqual(response.status_code, 404)

        # Store Users are not management users; probing management IDs is denied.
        self.assertEqual(self.client.get(self.store_b_detail_url).status_code, 403)

    def test_user_a_cannot_modify_store_b(self):
        original_phone = self.store_b.contact_phone
        self._login_portal("store-user-a")

        response = self.client.post(
            self.profile_url,
            {
                "store_id": self.store_b.pk,
                "first_name": "Hack",
                "last_name": "Attempt",
                "phone_number": "",
                "designation": "Hacker",
                "contact_phone": "9111111999",
                "alternative_phone": "",
                "email": "hacked-b@example.com",
                "description": "compromised",
            },
        )
        self.assertEqual(response.status_code, 404)
        self.store_b.refresh_from_db()
        self.assertEqual(self.store_b.contact_phone, original_phone)
        self.assertEqual(self.store_b.email, "store-b@example.com")

        edit_response = self.client.post(
            self.store_b_edit_url,
            self._store_edit_payload(self.store_b, name="Hacked Store B"),
        )
        self.assertEqual(edit_response.status_code, 403)
        self.store_b.refresh_from_db()
        self.assertEqual(self.store_b.name, "Store B")

    def test_user_a_cannot_access_store_b_storeuser_records(self):
        self._login_portal("store-user-a")
        self.assertEqual(self.client.get(self.store_b_users_url).status_code, 403)
        self.assertEqual(self.client.get(self.store_b_user_edit_url).status_code, 403)
        self.assertEqual(self.client.get(self.store_b_user_create_url).status_code, 403)

        # Cross-store membership lookup must not confirm Store B user existence.
        self._login_admin_with("view_storeuser", "change_storeuser")
        mismatched = self.reverse(
            "stores:store_user_edit",
            kwargs={"pk": self.store_a.pk, "user_id": self.user_b.pk},
        )
        self.assertEqual(self.client.get(mismatched).status_code, 404)

    def test_user_b_cannot_access_store_a(self):
        from django.http import Http404

        from stores.decorators import get_portal_store_or_404, portal_stores_queryset

        self._login_portal("store-user-b")
        dashboard = self.client.get(self.dashboard_url)
        self.assertEqual(dashboard.status_code, 200)
        self.assertContains(dashboard, self.store_b.name)
        self.assertNotContains(dashboard, self.store_a.store_code)

        with self.assertRaises(Http404):
            get_portal_store_or_404(self.user_b, store_id=self.store_a.pk)

        self.assertEqual(
            self.client.get(f"{self.profile_url}?store_id={self.store_a.pk}").status_code,
            404,
        )
        self.assertEqual(self.client.get(self.store_a_detail_url).status_code, 403)
        self.assertEqual(self.client.get(self.store_a_edit_url).status_code, 403)

        qs = portal_stores_queryset(self.user_b)
        self.assertEqual(list(qs.values_list("pk", flat=True)), [self.store_b.pk])

    def test_inactive_storeuser_cannot_access_either_store(self):
        self.membership_a.is_active = False
        self.membership_a.save(update_fields=["is_active"])

        self._login_portal("store-user-a")
        self.assertEqual(self.client.get(self.dashboard_url).status_code, 403)
        self.assertEqual(self.client.get(self.profile_url).status_code, 403)
        self.assertEqual(self.client.get(self.store_a_detail_url).status_code, 403)
        self.assertEqual(self.client.get(self.store_b_detail_url).status_code, 403)

        login_response = self.client.post(
            self.login_url,
            {"username": "store-user-a", "password": "secure-password-123"},
        )
        self.assertEqual(login_response.status_code, 200)
        self.assertContains(login_response, "No active store membership")

    def test_suspended_store_blocks_all_its_store_users(self):
        self.store_a.status = StoreStatus.SUSPENDED
        self.store_a.save(update_fields=["status"])

        for username in ("store-user-a", "store-user-a2"):
            with self.subTest(username=username):
                self.client.logout()
                self._login_portal(username)
                self.assertEqual(self.client.get(self.dashboard_url).status_code, 403)
                self.assertEqual(self.client.get(self.profile_url).status_code, 403)

        # Store B users remain unaffected.
        self.client.logout()
        self._login_portal("store-user-b")
        self.assertEqual(self.client.get(self.dashboard_url).status_code, 200)

        self.membership_a.refresh_from_db()
        self.membership_a2.refresh_from_db()
        self.assertTrue(self.membership_a.is_active)
        self.assertTrue(self.membership_a2.is_active)

    def test_admin_without_store_permissions_is_denied(self):
        self._login_admin_with()
        self.assertEqual(self.client.get(self.store_list_url).status_code, 403)
        self.assertEqual(self.client.get(self.store_a_detail_url).status_code, 403)
        self.assertEqual(self.client.get(self.store_a_edit_url).status_code, 403)
        self.assertEqual(self.client.get(self.store_b_users_url).status_code, 403)
        approve = self.client.post(
            self.store_a_change_status_url,
            {"new_status": StoreStatus.SUSPENDED, "reason": "nope"},
        )
        self.assertEqual(approve.status_code, 403)

    def test_admin_with_view_store_can_view_but_cannot_edit(self):
        self._login_admin_with("view_store")
        self.assertEqual(self.client.get(self.store_list_url).status_code, 200)
        self.assertEqual(self.client.get(self.store_a_detail_url).status_code, 200)
        self.assertEqual(self.client.get(self.store_b_detail_url).status_code, 200)
        self.assertEqual(self.client.get(self.store_a_edit_url).status_code, 403)
        self.assertEqual(self.client.get(self.store_b_edit_url).status_code, 403)

        edit_response = self.client.post(
            self.store_b_edit_url,
            self._store_edit_payload(self.store_b, name="Should Not Save"),
        )
        self.assertEqual(edit_response.status_code, 403)
        self.store_b.refresh_from_db()
        self.assertEqual(self.store_b.name, "Store B")

    def test_admin_with_change_store_can_edit(self):
        self._login_admin_with("view_store", "change_store")
        self.assertEqual(self.client.get(self.store_a_edit_url).status_code, 200)

        response = self.client.post(
            self.store_a_edit_url,
            self._store_edit_payload(
                self.store_a,
                name="Store A Updated",
                contact_phone="9000000099",
            ),
        )
        self.assertEqual(response.status_code, 302)
        self.store_a.refresh_from_db()
        self.assertEqual(self.store_a.name, "Store A Updated")
        self.assertEqual(self.store_a.contact_phone, "9000000099")

    def test_only_authorized_users_can_approve_or_suspend(self):
        # Viewer cannot approve or suspend.
        self._login_admin_with("view_store")
        approve_denied = self.client.post(
            self.store_a_change_status_url,
            {"new_status": StoreStatus.SUSPENDED, "reason": "unauthorized"},
        )
        self.assertEqual(approve_denied.status_code, 403)
        self.store_a.refresh_from_db()
        self.assertEqual(self.store_a.status, StoreStatus.ACTIVE)

        # Approver can restore PENDING→ACTIVE but still cannot suspend.
        self.store_a.status = StoreStatus.PENDING
        self.store_a.save(update_fields=["status"])
        self._login_admin_with("view_store", "approve_store")
        approve = self.client.post(
            self.store_a_change_status_url,
            {"new_status": StoreStatus.ACTIVE, "reason": "approved"},
        )
        self.assertEqual(approve.status_code, 302)
        self.store_a.refresh_from_db()
        self.assertEqual(self.store_a.status, StoreStatus.ACTIVE)

        suspend_denied = self.client.post(
            self.store_a_change_status_url,
            {"new_status": StoreStatus.SUSPENDED, "reason": "needs suspend perm"},
        )
        self.assertEqual(suspend_denied.status_code, 403)
        self.store_a.refresh_from_db()
        self.assertEqual(self.store_a.status, StoreStatus.ACTIVE)

        # Suspender can suspend; store users stay linked but portal is blocked.
        self._login_admin_with("view_store", "suspend_store")
        suspend = self.client.post(
            self.store_a_change_status_url,
            {"new_status": StoreStatus.SUSPENDED, "reason": "policy violation"},
        )
        self.assertEqual(suspend.status_code, 302)
        self.store_a.refresh_from_db()
        self.assertEqual(self.store_a.status, StoreStatus.SUSPENDED)
        self.assertTrue(StoreUser.objects.filter(pk=self.membership_a.pk).exists())

        self.client.logout()
        self._login_portal("store-user-a")
        self.assertEqual(self.client.get(self.dashboard_url).status_code, 403)

        # Super Admin may perform both transitions.
        self.store_a.status = StoreStatus.ACTIVE
        self.store_a.save(update_fields=["status"])
        self.assertTrue(
            self.client.login(
                username="isolation-super",
                password="secure-password-123",
            )
        )
        super_suspend = self.client.post(
            self.store_a_change_status_url,
            {"new_status": StoreStatus.SUSPENDED, "reason": "super hold"},
        )
        self.assertEqual(super_suspend.status_code, 302)
        restore = self.client.post(
            self.store_a_change_status_url,
            {"new_status": StoreStatus.ACTIVE, "reason": "restored"},
        )
        self.assertEqual(restore.status_code, 302)
        self.store_a.refresh_from_db()
        self.assertEqual(self.store_a.status, StoreStatus.ACTIVE)


class StorePortalProductDashboardStatsTests(StoreModelTestMixin, TestCase):
    def setUp(self):
        from django.urls import reverse

        from catalog.models import Product, ProductCategory, ProductStatus

        self.category = self.create_category(name="Portal Prod Cat")
        self.store_a = self.create_store(
            name="Portal Prod A",
            category=self.category,
            status=StoreStatus.ACTIVE,
            is_active=True,
        )
        self.store_b = self.create_store(
            name="Portal Prod B",
            category=self.category,
            status=StoreStatus.ACTIVE,
            is_active=True,
        )
        self.user_a = self.create_store_user_account(username="portal-prod-a")
        self.user_b = self.create_store_user_account(username="portal-prod-b")
        StoreUser.objects.create(
            store=self.store_a,
            user=self.user_a,
            is_primary=True,
            is_active=True,
        )
        StoreUser.objects.create(
            store=self.store_b,
            user=self.user_b,
            is_primary=True,
            is_active=True,
        )
        product_category = ProductCategory.objects.create(name="Portal Prod Products")

        def make_product(store, sku, status, stock, threshold):
            return Product.objects.create(
                store=store,
                name=f"{sku} name",
                sku=sku,
                category=product_category,
                store_price=Decimal("25.00"),
                status=status,
                stock_quantity=stock,
                low_stock_threshold=threshold,
            )

        make_product(
            self.store_a, "A-D", ProductStatus.DRAFT, Decimal("5"), Decimal("1")
        )
        make_product(
            self.store_a, "A-P1", ProductStatus.PENDING, Decimal("5"), Decimal("1")
        )
        make_product(
            self.store_a, "A-P2", ProductStatus.PENDING, Decimal("1"), Decimal("2")
        )
        make_product(
            self.store_a, "A-A", ProductStatus.APPROVED, Decimal("8"), Decimal("1")
        )
        make_product(
            self.store_a, "A-R", ProductStatus.REJECTED, Decimal("0"), Decimal("1")
        )
        make_product(
            self.store_b, "B-A1", ProductStatus.APPROVED, Decimal("10"), Decimal("1")
        )
        make_product(
            self.store_b, "B-A2", ProductStatus.APPROVED, Decimal("1"), Decimal("3")
        )

        self.dashboard_url = reverse("stores:store_portal_dashboard")

    def test_store_a_dashboard_counts_only_own_products(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        from catalog.services import get_store_product_dashboard_stats

        with CaptureQueriesContext(connection) as ctx:
            stats = get_store_product_dashboard_stats(self.store_a)
        self.assertEqual(len(ctx.captured_queries), 1)
        self.assertEqual(stats["total"], 5)
        self.assertEqual(stats["draft"], 1)
        self.assertEqual(stats["pending"], 2)
        self.assertEqual(stats["approved"], 1)
        self.assertEqual(stats["rejected"], 1)
        self.assertEqual(stats["low_stock"], 1)

        self.client.login(username="portal-prod-a", password="secure-password-123")
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["product_stats"]["total"], 5)
        self.assertEqual(response.context["product_stats"]["approved"], 1)
        self.assertContains(response, "<strong>Total Store Products:</strong> 5")
        self.assertContains(response, "<strong>Draft Products:</strong> 1")
        self.assertContains(response, "<strong>Pending Products:</strong> 2")
        self.assertContains(response, "<strong>Approved Products:</strong> 1")
        self.assertContains(response, "<strong>Rejected Products:</strong> 1")
        self.assertContains(response, "<strong>Low-stock Products:</strong> 1")

    def test_store_b_dashboard_isolated_from_store_a(self):
        self.client.login(username="portal-prod-b", password="secure-password-123")
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)
        stats = response.context["product_stats"]
        self.assertEqual(stats["total"], 2)
        self.assertEqual(stats["draft"], 0)
        self.assertEqual(stats["pending"], 0)
        self.assertEqual(stats["approved"], 2)
        self.assertEqual(stats["rejected"], 0)
        self.assertEqual(stats["low_stock"], 1)
        self.assertContains(response, "<strong>Total Store Products:</strong> 2")
        self.assertNotContains(response, "<strong>Total Store Products:</strong> 5")
