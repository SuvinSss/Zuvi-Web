import hashlib
import json
import os
import tempfile
from decimal import Decimal
from io import BytesIO, StringIO
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.test import TestCase
from PIL import Image

from accounts.models import Role
from .models import (
    PhotoImportBatch,
    PhotoImportImage,
    PhotoImportItem,
    ProductImage,
    ProductStatus,
    ProductStatusHistory,
)
from .pricing import MarginType
from .tests import CatalogTestMixin
from .validators import MAX_PRODUCT_IMAGE_SIZE_BYTES

NEW = "Gemini_Generated_Image_"


def jpeg(color):
    buffer = BytesIO()
    Image.new("RGB", (40, 40), color).save(buffer, "JPEG")
    return buffer.getvalue()


def png(color, size=(40, 40)):
    buffer = BytesIO()
    Image.new("RGB", size, color).save(buffer, "PNG")
    return buffer.getvalue()


class ReplaceFolderImagesTests(CatalogTestMixin, TestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_user(
            username="image-admin",
            email="image-admin@example.test",
            password="test-only-password",
            role=Role.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        self.store = self.create_store()
        self.batch = PhotoImportBatch.objects.create(name="Toys", created_by=self.actor, store=self.store)
        self.root = Path(tempfile.mkdtemp())
        self.tick = 1_000_000

    def product(self, key, original, *, approved=True):
        product = self.create_product(
            store=self.store,
            name=f"Toy {key}",
            profit_margin_type=MarginType.FIXED,
            profit_margin=Decimal("0"),
        )
        ProductImage.objects.create(product=product, image=ContentFile(original, name="old.jpg"), is_primary=True)
        if approved:
            product.status = ProductStatus.APPROVED
            product.save()
        item = PhotoImportItem.objects.create(
            batch=self.batch, source_key=key, source_hash=hashlib.sha256(key.encode()).hexdigest(), product=product
        )
        return product, item

    def stage(self, item, data):
        PhotoImportImage.objects.create(
            item=item,
            image=ContentFile(data, name="staged.jpg"),
            sha256=hashlib.sha256(data).hexdigest(),
            original_name="IMG_1.jpg",
        )

    def write(self, folder, name, data):
        path = self.root / folder / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(data)
        self.tick += 10
        os.utime(path, (self.tick, self.tick))
        return path

    def run_command(self, *extra):
        out = StringIO()
        call_command("replace_product_images_from_folders", "--root", str(self.root),
                     "--actor", str(self.actor.pk), *extra, stdout=out)
        rows = [json.loads(line) for line in out.getvalue().splitlines()]
        return {row["folder"]: row for row in rows if "folder" in row}

    def test_matches_by_photo_hash_and_keeps_product_approved(self):
        original = jpeg("red")
        product, item = self.product("Z002", original)
        self.stage(item, original)
        self.write("Toy folder", "IMG_1.jpg", original)
        self.write("Toy folder", NEW + "a.png", png("blue"))
        self.write("Toy folder", NEW + "b.png", png("green"))

        rows = self.run_command("--apply")

        row = rows["Toy folder"]
        self.assertEqual((row["state"], row["match"], row["product_id"]), ("replaced", "photo_hash", product.pk))
        images = list(product.images.order_by("sort_order"))
        self.assertEqual(len(images), 2)
        self.assertTrue(images[0].is_primary)
        self.assertFalse(images[1].is_primary)
        product.refresh_from_db()
        self.assertEqual(product.status, ProductStatus.APPROVED)
        self.assertTrue(
            ProductStatusHistory.objects.filter(
                product=product, new_status=ProductStatus.APPROVED, reason__contains="Toy folder"
            ).exists()
        )

    def test_dry_run_writes_nothing_and_second_run_is_noop(self):
        original = jpeg("red")
        product, item = self.product("Z003", original)
        self.stage(item, original)
        self.write("Z003", "IMG_1.jpg", original)
        self.write("Z003", NEW + "a.png", png("blue"))
        old_ids = list(product.images.values_list("pk", flat=True))

        self.assertEqual(self.run_command()["Z003"]["state"], "ready")
        self.assertEqual(list(product.images.values_list("pk", flat=True)), old_ids)

        self.assertEqual(self.run_command("--apply")["Z003"]["state"], "replaced")
        self.assertEqual(self.run_command("--apply")["Z003"]["state"], "already_replaced")

    def test_source_key_fallback_and_unmatched_and_skipped(self):
        product, _ = self.product("Z004", jpeg("red"), approved=False)
        self.write("Z004", "IMG_unknown.jpg", jpeg("yellow"))
        self.write("Z004", NEW + "a.png", png("blue"))
        self.write("Z999", "IMG_unknown.jpg", jpeg("purple"))
        self.write("Z999", NEW + "a.png", png("blue"))
        self.write("Z038", "IMG_only.jpg", jpeg("black"))

        rows = self.run_command("--apply")

        self.assertEqual((rows["Z004"]["state"], rows["Z004"]["match"]), ("replaced", "source_key"))
        product.refresh_from_db()
        self.assertEqual(product.status, ProductStatus.PENDING)
        self.assertEqual(rows["Z999"]["state"], "unmatched")
        self.assertEqual(rows["Z038"]["state"], "skipped_no_new_images")

    def test_ambiguous_photos_are_skipped(self):
        first, second = jpeg("red"), jpeg("blue")
        _, item_a = self.product("Z005", first)
        _, item_b = self.product("Z006", second)
        self.stage(item_a, first)
        self.stage(item_b, second)
        self.write("Mixed", "IMG_1.jpg", first)
        self.write("Mixed", "IMG_2.jpg", second)
        self.write("Mixed", NEW + "a.png", png("green"))

        self.assertEqual(self.run_command("--apply")["Mixed"]["state"], "ambiguous")

    def test_duplicates_removed_limit_applied_and_large_png_compressed(self):
        original = jpeg("red")
        product, item = self.product("Z044", original)
        self.stage(item, original)
        self.write("Z044", "IMG_1.jpg", original)
        noise = Image.frombytes("RGB", (1600, 1200), os.urandom(1600 * 1200 * 3))
        big = BytesIO()
        noise.save(big, "PNG")
        self.assertGreater(big.tell(), MAX_PRODUCT_IMAGE_SIZE_BYTES)
        self.write("Z044", NEW + "first.png", big.getvalue())
        self.write("Z044", NEW + "first (1).png", big.getvalue())
        for index in range(6):
            self.write("Z044", f"{NEW}{index}.png", png((index * 30, 0, 0)))

        row = self.run_command("--apply")["Z044"]

        self.assertEqual(row["state"], "replaced")
        self.assertEqual(row["new_images"][0], NEW + "first.png")
        self.assertEqual(row["compressed"], [NEW + "first.png"])
        self.assertEqual(row["dropped_over_limit"], 2)
        images = list(product.images.order_by("sort_order"))
        self.assertEqual(len(images), 5)
        self.assertTrue(images[0].is_primary)
        self.assertTrue(images[0].image.name.endswith(".jpg"))
        self.assertLessEqual(images[0].image.size, MAX_PRODUCT_IMAGE_SIZE_BYTES)
