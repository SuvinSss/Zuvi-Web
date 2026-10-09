import hashlib
from datetime import timedelta
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from accounts.models import Role
from inventory.models import InventoryTransaction
from .models import PhotoImportBatch, PhotoImportItem, PhotoImportImage, Product
from .photo_import import import_item, price_research
from .tests import CatalogTestMixin


def image_file():
    f = BytesIO()
    Image.new("RGB", (30, 30), "green").save(f, "JPEG")
    return SimpleUploadedFile("test.jpg", f.getvalue(), content_type="image/jpeg")


class PhotoImportTests(CatalogTestMixin, TestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_user(
            username="import-admin",
            email="import@example.test",
            password="test-only-password",
            role=Role.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        self.store = self.create_store()
        self.category = self.create_product_category()
        self.batch = PhotoImportBatch.objects.create(
            name="Import", created_by=self.actor, store=self.store
        )
        self.item = PhotoImportItem.objects.create(
            batch=self.batch,
            source_key="Z001",
            source_hash="a" * 64,
            details={
                "name": "Verified product",
                "category": self.category.pk,
                "unit": "PIECE",
                "unit_value": "1",
                "pricing_policy": "retail_mean",
                "identity_verified": True,
                "offers_verified": True,
                "offers": [
                    self.offer("one.example", "100.00"),
                    self.offer("two.example", "120.00"),
                    self.offer("three.example", "140.00"),
                ],
            },
        )
        PhotoImportImage.objects.create(
            item=self.item,
            image=image_file(),
            sha256="b" * 64,
            original_name="test.jpg",
        )
        self.client.force_login(self.actor)

    def offer(self, domain, price):
        return {
            "url": "https://" + domain + "/product",
            "price": price,
            "checked_at": timezone.localdate().isoformat(),
            "availability": "in_stock",
            "exact_match": True,
            "currency": "INR",
        }

    def test_mean_dry_run_and_publish_idempotently(self):
        result = import_item(
            item_id=self.item.pk, actor=self.actor, publish=True, dry_run=True
        )
        self.assertEqual(result["final_price"], "120.00")
        self.assertFalse(Product.objects.exists())
        result = import_item(item_id=self.item.pk, actor=self.actor, publish=True)
        product = Product.objects.get(pk=result["product_id"])
        self.assertEqual(product.status, "APPROVED")
        self.assertEqual(product.final_price, Decimal("120"))
        self.assertEqual(product.stock_quantity, 0)
        self.assertEqual(product.images.count(), 1)
        self.assertTrue(product.status_history.exists())
        self.assertTrue(product.price_history.exists())
        self.assertEqual(
            import_item(item_id=self.item.pk, actor=self.actor, publish=True)["state"],
            "already_imported",
        )
        self.assertEqual(Product.objects.count(), 1)

    def test_same_source_new_batch_does_not_duplicate(self):
        import_item(item_id=self.item.pk, actor=self.actor, publish=True)
        batch = PhotoImportBatch.objects.create(
            name="Again", created_by=self.actor, store=self.store
        )
        other = PhotoImportItem.objects.create(
            batch=batch,
            source_key="Renamed",
            source_hash=self.item.source_hash,
            details=self.item.details,
        )
        PhotoImportImage.objects.create(
            item=other, image=image_file(), sha256="b" * 64, original_name="test.jpg"
        )
        result = import_item(item_id=other.pk, actor=self.actor, publish=True)
        self.assertEqual(result["state"], "existing_product")
        self.assertEqual(Product.objects.count(), 1)

    def test_unknown_price_and_identity_blocked(self):
        self.item.details.update(identity_verified=False)
        self.item.save()
        with self.assertRaises(ValidationError):
            import_item(item_id=self.item.pk, actor=self.actor, publish=True)
        self.item.details.update(identity_verified=True, offers=[])
        self.item.save()
        with self.assertRaises(ValidationError):
            import_item(item_id=self.item.pk, actor=self.actor, publish=True)
        self.assertFalse(Product.objects.exists())

    def test_opening_stock_once(self):
        self.item.details["stock"] = "4"
        self.item.save()
        import_item(item_id=self.item.pk, actor=self.actor, publish=True)
        import_item(item_id=self.item.pk, actor=self.actor, publish=True)
        self.assertEqual(InventoryTransaction.objects.count(), 1)
        self.assertEqual(Product.objects.get().stock_quantity, Decimal("4"))

    def test_approval_failure_rolls_back_product_stock_and_item(self):
        self.item.details["stock"] = "4"
        self.item.save()
        with patch(
            "catalog.photo_import.record_product_status_change",
            side_effect=ValidationError("Fail"),
        ):
            with self.assertRaises(ValidationError):
                import_item(item_id=self.item.pk, actor=self.actor, publish=True)
        self.assertFalse(Product.objects.exists())
        self.assertFalse(InventoryTransaction.objects.exists())
        self.item.refresh_from_db()
        self.assertIsNone(self.item.product_id)

    def test_inactive_store_and_missing_pricing_permission(self):
        self.store.is_active = False
        self.store.save()
        with self.assertRaises(ValidationError):
            import_item(item_id=self.item.pk, actor=self.actor, publish=True)
        admin = get_user_model().objects.create_user(
            username="limited",
            email="limited@example.test",
            role=Role.ADMIN,
            is_staff=True,
        )
        admin.user_permissions.add(Permission.objects.get(codename="add_product"))
        with self.assertRaises(PermissionDenied):
            import_item(item_id=self.item.pk, actor=admin)

    def test_store_user_cannot_access_import(self):
        user = self.create_store_user(self.store)
        self.client.force_login(user)
        self.assertEqual(
            self.client.get(reverse("catalog:photo_import")).status_code, 403
        )
        self.assertEqual(
            self.client.post(
                reverse("catalog:photo_import_create"),
                data="{}",
                content_type="application/json",
            ).status_code,
            403,
        )

    def test_other_admin_cannot_read_batch(self):
        admin = get_user_model().objects.create_user(
            username="other", email="other@example.test", role=Role.ADMIN, is_staff=True
        )
        admin.user_permissions.add(Permission.objects.get(codename="add_product"))
        self.client.force_login(admin)
        self.assertEqual(
            self.client.get(
                reverse("catalog:photo_import_batch", args=[self.batch.pk])
            ).status_code,
            404,
        )

    def test_post_required_and_invalid_image(self):
        url = reverse("catalog:photo_import_action", args=[self.batch.pk, self.item.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(
            self.client.post(
                url,
                {"action": "upload", "image": SimpleUploadedFile("bad.jpg", b"bad")},
            ).status_code,
            400,
        )
        self.assertEqual(self.item.photos.count(), 1)

    def test_upload_retry_deduplicates_and_max_five(self):
        url = reverse("catalog:photo_import_action", args=[self.batch.pk, self.item.pk])
        self.item.photos.all().delete()
        for _ in range(2):
            self.assertEqual(
                self.client.post(
                    url, {"action": "upload", "image": image_file()}
                ).status_code,
                200,
            )
        self.assertEqual(self.item.photos.count(), 1)

    def test_offers_reject_bad_values_and_mismatches(self):
        for price in ["NaN", "Infinity", "-1", "0", "1.234"]:
            with self.assertRaises(ValidationError):
                price_research([self.offer("one.example", price)])
        with self.assertRaises(ValidationError):
            price_research(
                [self.offer("one.example", "100"), self.offer("one.example", "110")]
            )
        offer = self.offer("one.example", "100")
        offer["exact_match"] = False
        with self.assertRaises(ValidationError):
            price_research([offer])
        offer = self.offer("one.example", "100")
        offer["checked_at"] = (timezone.localdate() - timedelta(days=31)).isoformat()
        with self.assertRaises(ValidationError):
            price_research([offer])

    def test_no_browser_final_price_or_stock_assignment(self):
        self.item.details.update(final_price="1", stock_quantity="999")
        self.item.save()
        import_item(item_id=self.item.pk, actor=self.actor, publish=True)
        p = Product.objects.get()
        self.assertEqual(p.final_price, Decimal("120"))
        self.assertEqual(p.stock_quantity, 0)

    def test_page_and_json(self):
        self.assertContains(
            self.client.get(reverse("catalog:photo_import")), "Read photo text"
        )
        r = self.client.get(reverse("catalog:photo_import_batch", args=[self.batch.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["items"][0]["source_key"], "Z001")

    def test_photo_selection_and_split(self):
        url = reverse("catalog:photo_import_action", args=[self.batch.pk, self.item.pk])
        photo = self.item.photos.get()
        photo.sha256 = hashlib.sha256(image_file().read()).hexdigest()
        photo.save(update_fields=["sha256"])
        result = self.client.post(
            url,
            data={
                "action": "split",
                "source_key": "Z001-blue",
                "photo_ids": [photo.pk],
            },
            content_type="application/json",
        )
        self.assertEqual(result.status_code, 200)
        split = self.batch.items.get(source_key="Z001-blue")
        self.assertEqual(split.photos.count(), 1)
        self.assertEqual(self.item.photos.count(), 0)
        resumed = self.client.post(url, {"action": "upload", "image": image_file()})
        self.assertEqual(resumed.status_code, 200)
        self.assertEqual(self.item.photos.count(), 0)
        self.assertEqual(split.photos.count(), 1)
        self.item.refresh_from_db()
        self.assertFalse(self.item.details["identity_verified"])
        with self.assertRaises(ValidationError):
            import_item(item_id=self.item.pk, actor=self.actor, publish=True)

    def test_photo_endpoint_is_private_and_parent_scoped(self):
        photo = self.item.photos.get()
        url = reverse(
            "catalog:photo_import_photo", args=[self.batch.pk, self.item.pk, photo.pk]
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(b"".join(response.streaming_content))
        bad = reverse(
            "catalog:photo_import_photo",
            args=[self.batch.pk, self.item.pk + 100, photo.pk],
        )
        self.assertEqual(self.client.get(bad).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_selection_rejects_foreign_photos(self):
        url = reverse("catalog:photo_import_action", args=[self.batch.pk, self.item.pk])
        r = self.client.post(
            url,
            data={
                "action": "save",
                "details": self.item.details,
                "selected_photo_ids": [99999],
            },
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 400)
        self.assertTrue(self.item.photos.get().selected)

    def test_admin_requires_approval_and_inventory_adjustment(self):
        admin = get_user_model().objects.create_user(
            username="importer",
            email="importer@example.test",
            role=Role.ADMIN,
            is_staff=True,
        )
        admin.user_permissions.add(
            *Permission.objects.filter(
                codename__in=["add_product", "manage_product_pricing"]
            )
        )
        self.batch.created_by = admin
        self.batch.save()
        with self.assertRaises(PermissionDenied):
            import_item(item_id=self.item.pk, actor=admin, publish=True)
        self.item.details["stock"] = "2"
        self.item.save()
        with self.assertRaises(PermissionDenied):
            import_item(item_id=self.item.pk, actor=admin)
        self.assertFalse(Product.objects.exists())


class RetailerPriceTests(TestCase):
    def test_untrusted_hosts_and_paths_never_requested(self):
        from .retailer_prices import fetch_offer

        with patch("catalog.retailer_prices.requests.Session") as session:
            for url in [
                "http://127.0.0.1/products/test",
                "https://truewholesale.in.evil.test/products/test",
                "https://user@truewholesale.in/products/test",
                "https://truewholesale.in:444/products/test",
                "https://truewholesale.in/admin",
                "https://truewholesale.in/products/../admin",
            ]:
                with self.assertRaises(ValidationError):
                    fetch_offer(url)
            session.assert_not_called()

    def test_price_currency_and_variant_are_verified(self):
        from .retailer_prices import fetch_offer

        product = {
            "title": "Test",
            "variants": [
                {"id": 1, "title": "Default", "available": True, "price": 19900}
            ],
        }
        with patch(
            "catalog.retailer_prices.read_json",
            side_effect=[{"currency": "INR"}, product],
        ):
            result = fetch_offer("https://truewholesale.in/products/test")
        self.assertEqual(result["price"], "199.00")
        self.assertFalse(result["exact_match"])
        with patch(
            "catalog.retailer_prices.read_json", return_value={"currency": "USD"}
        ):
            with self.assertRaises(ValidationError):
                fetch_offer("https://truewholesale.in/products/test")
        product["variants"][0]["available"] = False
        with patch(
            "catalog.retailer_prices.read_json",
            side_effect=[{"currency": "INR"}, product],
        ):
            with self.assertRaises(ValidationError):
                fetch_offer("https://truewholesale.in/products/test")
