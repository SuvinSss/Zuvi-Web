import io

from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import Http404
from django.test import SimpleTestCase
from PIL import Image

from core import uploads
from core.exceptions import api_exception_handler
from core.geo import haversine_m


class ExceptionHandlerTests(SimpleTestCase):
    def status(self, exc):
        return api_exception_handler(exc, {}).status_code

    def test_mapping(self):
        self.assertEqual(self.status(ValidationError("bad")), 400)
        self.assertEqual(self.status(PermissionDenied()), 403)
        self.assertEqual(self.status(Http404()), 404)
        self.assertEqual(self.status(ObjectDoesNotExist()), 404)

    def test_unhandled_errors_do_not_leak_details(self):
        with self.assertLogs("core.exceptions", level="ERROR"):
            response = api_exception_handler(RuntimeError("secret db password"), {})
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("secret", str(response.data))

    def test_field_errors_keep_field_names(self):
        response = api_exception_handler(ValidationError({"name": ["required"]}), {})
        self.assertEqual(response.data, {"name": ["required"]})


class UploadTests(SimpleTestCase):
    def png(self, exif=False):
        buf = io.BytesIO()
        img = Image.new("RGB", (40, 40), "red")
        if exif:
            ex = Image.Exif()
            ex[0x010F] = "SecretCam"
            img.save(buf, "JPEG", exif=ex)
        else:
            img.save(buf, "PNG")
        return SimpleUploadedFile("x.jpg" if exif else "x.png", buf.getvalue())

    def test_image_is_reencoded_without_metadata(self):
        clean = uploads.clean_image(self.png(exif=True))
        self.assertEqual(Image.open(clean.file).getexif().get(0x010F), None)

    def test_text_renamed_as_image_is_rejected(self):
        with self.assertRaises(ValidationError):
            uploads.clean_image(SimpleUploadedFile("a.jpg", b"hello", content_type="image/jpeg"))

    def test_pdf_accepted_by_magic_bytes_only(self):
        ok = uploads.clean_document(SimpleUploadedFile("a.bin", b"%PDF-1.4 data"))
        self.assertEqual(ok.content_type, "application/pdf")
        with self.assertRaises(ValidationError):
            uploads.clean_document(SimpleUploadedFile("a.pdf", b"not a pdf at all"))

    def test_oversize_rejected(self):
        with self.settings(EVIDENCE_MAX_BYTES=10):
            with self.assertRaises(ValidationError):
                uploads.clean_document(SimpleUploadedFile("a.pdf", b"%PDF-" + b"x" * 50))


class GeoTests(SimpleTestCase):
    def test_haversine(self):
        self.assertAlmostEqual(haversine_m(0, 0, 0, 0), 0, places=6)
        self.assertAlmostEqual(haversine_m(0, 0, 0, 1), 111195, delta=500)
