"""The shared image pipeline: validation, normalisation, thumbnails, de-duplication."""
from io import BytesIO

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image

from . import image_pipeline
from .models import ProductImage
from .services import add_product_image, delete_product_image
from .tests import CatalogTestMixin


def jpeg_with_gps(size=(3000, 1500)):
    image = Image.new("RGB", size, (200, 30, 30))
    exif = Image.Exif()
    exif[0x0112] = 6  # orientation: rotate 270 on display
    exif[0x8825] = {1: "N", 2: (12.0, 58.0, 0.0), 3: "E", 4: (77.0, 35.0, 0.0)}  # GPS IFD
    out = BytesIO()
    image.save(out, "JPEG", exif=exif)
    return out.getvalue()


class PrepareUploadTests(TestCase):
    def test_strips_metadata_applies_orientation_and_caps_size(self):
        processed = image_pipeline.prepare_upload(SimpleUploadedFile("p.jpg", jpeg_with_gps()))
        with Image.open(BytesIO(processed.file.read())) as out:
            self.assertEqual(out.format, "JPEG")
            self.assertEqual(len(out.getexif()), 0)  # no EXIF at all, so no GPS
            # 3000x1500 rotated by orientation -> 1500x3000, then capped to 2400 on the long side.
            self.assertEqual(out.size, (1200, 2400))
        self.assertEqual((processed.width, processed.height), (1200, 2400))
        self.assertEqual(len(processed.sha256), 64)

    def test_small_images_are_not_upscaled(self):
        buf = BytesIO()
        Image.new("RGB", (50, 30), "red").save(buf, "PNG")
        processed = image_pipeline.prepare_upload(SimpleUploadedFile("s.png", buf.getvalue()))
        self.assertEqual((processed.width, processed.height), (50, 30))

    def test_same_content_gives_same_hash(self):
        data = jpeg_with_gps((200, 100))
        a = image_pipeline.prepare_upload(SimpleUploadedFile("a.jpg", data))
        b = image_pipeline.prepare_upload(SimpleUploadedFile("b.jpg", data))
        self.assertEqual(a.sha256, b.sha256)

    def test_rejects_non_images_even_with_image_name(self):
        with self.assertRaises(ValidationError):
            image_pipeline.prepare_upload(SimpleUploadedFile("evil.jpg", b"<?php echo 1; ?>"))

    def test_rejects_unsupported_formats(self):
        buf = BytesIO()
        Image.new("RGB", (10, 10)).save(buf, "GIF")
        with self.assertRaises(ValidationError):
            image_pipeline.prepare_upload(SimpleUploadedFile("a.gif", buf.getvalue()))

    @override_settings(PRODUCT_IMAGE_MAX_PIXELS=1000)
    def test_rejects_too_many_pixels_before_decoding(self):
        buf = BytesIO()
        Image.new("RGB", (100, 100)).save(buf, "PNG")
        with self.assertRaisesMessage(ValidationError, "megapixels"):
            image_pipeline.prepare_upload(SimpleUploadedFile("big.png", buf.getvalue()))

    @override_settings(PRODUCT_IMAGE_MAX_BYTES=100)
    def test_rejects_oversized_files(self):
        with self.assertRaises(ValidationError):
            image_pipeline.prepare_upload(SimpleUploadedFile("big.jpg", jpeg_with_gps((300, 300))))

    def test_transparent_png_keeps_alpha(self):
        buf = BytesIO()
        Image.new("RGBA", (20, 20), (0, 0, 0, 0)).save(buf, "PNG")
        processed = image_pipeline.prepare_upload(SimpleUploadedFile("t.png", buf.getvalue()))
        with Image.open(BytesIO(processed.file.read())) as out:
            self.assertEqual(out.mode, "RGBA")


class ThumbnailTests(TestCase):
    def thumb(self, size, mode="RGB", color="red"):
        buf = BytesIO()
        Image.new(mode, size, color).save(buf, "PNG")
        return Image.open(BytesIO(image_pipeline.make_thumbnail(SimpleUploadedFile("x.png", buf.getvalue())).read()))

    def test_wide_image_is_contained_not_cropped_or_stretched(self):
        with self.thumb((1600, 800)) as t:
            self.assertEqual((t.format, t.size), ("WEBP", (400, 400)))
            top, middle = t.getpixel((200, 10)), t.getpixel((200, 200))
            self.assertGreater(top[0], 230)  # neutral padding above the product
            self.assertGreater(top[1], 230)
            self.assertGreater(middle[0], 200)  # product is red in the middle
            self.assertLess(middle[1], 60)

    def test_small_image_is_centred_without_upscaling(self):
        with self.thumb((40, 40)) as t:
            self.assertEqual(t.size, (400, 400))
            self.assertGreater(t.getpixel((5, 5))[1], 230)  # corner is padding
            self.assertLess(t.getpixel((200, 200))[1], 60)  # centre is the 40px product


class ServicePipelineTests(CatalogTestMixin, TestCase):
    def setUp(self):
        self.product = self.create_product()

    def test_upload_creates_sanitised_original_thumbnail_and_facts(self):
        image = add_product_image(product=self.product, image=SimpleUploadedFile("p.jpg", jpeg_with_gps((800, 400))))
        image.refresh_from_db()
        self.assertTrue(image.thumbnail.name.endswith(".webp"))
        self.assertEqual(len(image.content_hash), 64)
        self.assertEqual((image.width, image.height), (400, 800))
        with Image.open(image.image) as stored:
            self.assertEqual(len(stored.getexif()), 0)

    def test_identical_images_share_stored_files(self):
        data = jpeg_with_gps((300, 300))
        first = add_product_image(product=self.product, image=SimpleUploadedFile("a.jpg", data))
        other = self.create_product()
        second = add_product_image(product=other, image=SimpleUploadedFile("b.jpg", data))
        self.assertEqual(first.image.name, second.image.name)
        self.assertEqual(first.thumbnail.name, second.thumbnail.name)
        self.assertEqual(ProductImage.objects.filter(content_hash=first.content_hash).count(), 2)

    def test_deleting_one_reference_keeps_files_used_by_another(self):
        data = jpeg_with_gps((300, 300))
        first = add_product_image(product=self.product, image=SimpleUploadedFile("a.jpg", data))
        second = add_product_image(product=self.create_product(), image=SimpleUploadedFile("b.jpg", data))
        storage, name = first.image.storage, first.image.name
        delete_product_image(product=self.product, image_id=first.pk)
        self.assertTrue(storage.exists(name))
        self.assertTrue(storage.exists(second.thumbnail.name))

    def test_invalid_upload_leaves_no_rows(self):
        with self.assertRaises(ValidationError):
            add_product_image(product=self.product, image=SimpleUploadedFile("x.jpg", b"not an image"))
        self.assertFalse(ProductImage.objects.exists())
