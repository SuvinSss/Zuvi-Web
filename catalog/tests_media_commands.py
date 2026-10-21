import os
import time
from io import StringIO

from django.core.files.storage import default_storage
from django.core.management import call_command
from django.test import TestCase

from .models import ProductImage
from .services import add_product_image
from .tests import CatalogTestMixin


class MediaCommandTests(CatalogTestMixin, TestCase):
    def setUp(self):
        self.product = self.create_product()
        self.image = add_product_image(product=self.product, image=self._uploaded_image())

    def _legacy(self):
        """Simulate a pre-pipeline row: no thumbnail, no facts."""
        ProductImage.objects.filter(pk=self.image.pk).update(thumbnail="", content_hash="", width=None, height=None, file_size=None)
        return ProductImage.objects.get(pk=self.image.pk)

    def test_backfill_dry_run_changes_nothing(self):
        self._legacy()
        out = StringIO()
        call_command("backfill_product_thumbnails", stdout=out)
        self.assertIn("Dry run: 1", out.getvalue())
        self.assertEqual(ProductImage.objects.get(pk=self.image.pk).thumbnail.name, "")

    def test_backfill_apply_creates_thumbnail_and_keeps_original(self):
        legacy = self._legacy()
        original = legacy.image.name
        call_command("backfill_product_thumbnails", "--apply", stdout=StringIO())
        fresh = ProductImage.objects.get(pk=self.image.pk)
        self.assertTrue(fresh.thumbnail.name.endswith(".webp"))
        self.assertTrue(default_storage.exists(fresh.thumbnail.name))
        self.assertEqual(fresh.image.name, original)
        self.assertEqual(len(fresh.content_hash), 64)
        self.assertGreater(fresh.width, 0)
        out = StringIO()
        call_command("backfill_product_thumbnails", "--apply", stdout=out)  # idempotent
        self.assertIn("Created 0", out.getvalue())

    def test_cleanup_never_touches_referenced_or_recent_files(self):
        out = StringIO()
        call_command("cleanup_product_media", "--delete", stdout=out)
        self.assertTrue(default_storage.exists(self.image.image.name))
        self.assertTrue(default_storage.exists(self.image.thumbnail.name))
        self.assertIn("Deleted: 0", out.getvalue())

    def test_cleanup_dry_run_lists_then_delete_removes_only_old_orphans(self):
        old = default_storage.save("products/images/orphan-old.jpg", self.image.image.file)
        recent = default_storage.save("products/images/orphan-new.jpg", self.image.image.file)
        stamp = time.time() - 3 * 86400
        os.utime(default_storage.path(old), (stamp, stamp))
        out = StringIO()
        call_command("cleanup_product_media", stdout=out)
        self.assertIn("orphan " + old, out.getvalue())
        self.assertTrue(default_storage.exists(old))
        call_command("cleanup_product_media", "--delete", stdout=StringIO())
        self.assertFalse(default_storage.exists(old))
        self.assertTrue(default_storage.exists(recent))
        self.assertTrue(default_storage.exists(self.image.image.name))
