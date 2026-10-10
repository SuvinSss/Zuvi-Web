"""An authorized manager's first photo can publish an opted-in product."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from accounts.models import Role
from .models import ProductStatus
from .pricing import MarginType
from .services import apply_admin_pricing
from .tests_image_workflow import WorkflowFixtures


class AutoPublishOnImageTests(WorkflowFixtures, TestCase):
    def setUp(self):
        super().setUp()
        apply_admin_pricing(
            product=self.product, profit_margin_type=MarginType.FIXED,
            profit_margin=Decimal("0"), changed_by=self.actor,
        )
        self.url = reverse("catalog:product_images", kwargs={"pk": self.product.pk})

    def upload(self, user):
        self.client.force_login(user)
        return self.client.post(self.url, {"image": self._uploaded_image()})

    def test_opted_in_product_publishes_after_authorized_upload(self):
        self.product.auto_publish_on_first_image = True
        self.product.save(update_fields=["auto_publish_on_first_image"])
        response = self.upload(self.actor)
        self.assertEqual(response.status_code, 302)
        self.product.refresh_from_db()
        self.assertEqual(self.product.status, ProductStatus.APPROVED)
        self.assertEqual(self.product.approved_by, self.actor)
        self.assertFalse(self.product.auto_publish_on_first_image)
        self.assertEqual(self.product.images.count(), 1)
        self.assertEqual(self.product.status_history.last().reason,
            "Published after an authorized manager uploaded the first product image.")

    def test_upload_without_approval_permission_stays_pending(self):
        self.product.auto_publish_on_first_image = True
        self.product.save(update_fields=["auto_publish_on_first_image"])
        admin = get_user_model().objects.create_user(
            "image-editor", email="image-editor@example.test",
            password="test-password", role=Role.ADMIN, is_staff=True,
        )
        admin.user_permissions.add(Permission.objects.get(
            codename="change_product", content_type__app_label="catalog"))
        response = self.upload(admin)
        self.assertEqual(response.status_code, 302)
        self.product.refresh_from_db()
        self.assertEqual(self.product.status, ProductStatus.PENDING)
        self.assertTrue(self.product.auto_publish_on_first_image)
        self.assertEqual(self.product.images.count(), 1)

    def test_other_products_do_not_auto_publish(self):
        response = self.upload(self.actor)
        self.assertEqual(response.status_code, 302)
        self.product.refresh_from_db()
        self.assertEqual(self.product.status, ProductStatus.PENDING)
        self.assertEqual(self.product.images.count(), 1)
