from io import BytesIO
from decimal import Decimal
from django.test import TestCase, SimpleTestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image
from .tests_public import PublicCatalogueTestMixin
from .image_processing import display_image
from .models import ProductImage
from .pricing import DiscountType

class ReleaseCatalogueTests(PublicCatalogueTestMixin, TestCase):
    def test_offers_filter_keeps_visibility_and_backend_prices(self):
        deal=self.create_public_product(name='Eligible Deal',discount_type=DiscountType.FIXED,discount_value=Decimal('10.00'))
        self.create_public_product(name='Regular Product')
        self.create_public_product(name='Hidden Deal',discount_type=DiscountType.FIXED,discount_value=Decimal('10.00'),is_active=False)
        r=self.client.get(reverse('catalog:public_product_list'),{'offers':'1'})
        self.assertContains(r,'Eligible Deal');self.assertContains(r,'Grab Deal')
        self.assertNotContains(r,'Regular Product');self.assertNotContains(r,'Hidden Deal')
        self.assertNotContains(r,'Most ordered');self.assertNotContains(r,'Trending')
        self.assertContains(r,'name="offers"')

    def test_derivative_preserves_original_and_metadata_does_not_reencode(self):
        product=self.create_public_product();image=self.attach_image(product)
        original=image.image.name;derived=image.display_image.name
        self.assertTrue(derived.endswith('.png'));self.assertNotEqual(original,derived)
        image.alt_text='Updated description';image.save(update_fields=['alt_text']);image.refresh_from_db()
        self.assertEqual(image.display_image.name,derived)
        self.assertTrue(image.image.storage.exists(original))

    def test_manifest_and_service_worker_do_not_cache_private_pages(self):
        r=self.client.get('/manifest.webmanifest');self.assertEqual(r.status_code,200)
        self.assertEqual(r.json()['display'],'standalone')
        sw=self.client.get('/service-worker.js')
        self.assertEqual(sw.status_code,200);self.assertNotContains(sw,'cache.put');self.assertNotContains(sw,'caches.open')

class ImageNormalizationTests(SimpleTestCase):
    def test_transparent_trim_and_non_destructive_fit(self):
        source=BytesIO();im=Image.new('RGBA',(1800,1400),(0,0,0,0));im.paste((120,40,20,255),(100,100,1700,1300));im.save(source,format='PNG')
        upload=SimpleUploadedFile('source.png',source.getvalue());result=display_image(upload)
        with Image.open(result) as out:
            self.assertEqual(out.size,(1200,900));self.assertEqual(out.format,'PNG')
        self.assertEqual(upload.read(),source.getvalue())

    def test_optional_white_background_removal_preserves_colored_subject(self):
        source=BytesIO();im=Image.new('RGB',(100,100),'white');im.paste((200,30,20),(20,20,80,80));im.save(source,format='PNG')
        upload=SimpleUploadedFile('source.png',source.getvalue())
        with Image.open(display_image(upload,remove_background=True)) as out:
            self.assertEqual(out.size,(60,60));self.assertEqual(out.getpixel((30,30)),(200,30,20,255))
        self.assertEqual(upload.read(),source.getvalue())
