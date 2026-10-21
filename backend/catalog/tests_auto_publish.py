"""An authorized manager's first photo can publish an opted-in product."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from accounts.models import Role
from .models import ProductStatus
from .pricing import MarginType
from .services import add_product_image, apply_admin_pricing
from .tests_image_workflow import WorkflowFixtures


class AutoPublishOnImageTests(WorkflowFixtures, TestCase):
    def setUp(self):
        super().setUp()
        apply_admin_pricing(
            product=self.product, profit_margin_type=MarginType.FIXED,
            profit_margin=Decimal("0"), changed_by=self.actor,
        )





    def test_admin_inline_image_service_also_publishes(self):
        self.product.auto_publish_on_first_image = True
        self.product.save(update_fields=["auto_publish_on_first_image"])
        add_product_image(
            product=self.product, image=self._uploaded_image(), changed_by=self.actor,
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.status, ProductStatus.APPROVED)
        self.assertFalse(self.product.auto_publish_on_first_image)
