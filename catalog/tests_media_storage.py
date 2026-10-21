"""Product image compatibility with storage that cannot supply local paths."""

from unittest.mock import patch

from botocore.exceptions import ClientError
from django.core.exceptions import ValidationError
from django.core.files.storage import storages
from django.db import transaction
from django.test import TestCase, override_settings

from config.tests_media_storage import RemoteStorage
from .models import ProductImage
from .public import get_public_product_by_slug, public_product_detail_context
from .services import add_product_image, delete_product_image, replace_product_image
from .tests import CatalogTestMixin
from .validators import validate_product_image


class ProductRemoteStorageTests(CatalogTestMixin, TestCase):
    def setUp(self):
        self.enterContext(override_settings(STORAGES={
            **storages.backends,
            'default': {'BACKEND': 'config.tests_media_storage.RemoteStorage'},
        }))
        self.storage = storages['default']
        self.assertIsInstance(self.storage, RemoteStorage)
        self.product = self.create_product()

    def tearDown(self):
        self.assertEqual(self.storage.path_calls, 0)
        super().tearDown()

    def _distinct_image(self, seq):
        # Identical uploads are de-duplicated and would skip storage entirely.
        return self._uploaded_image(content=self._jpeg_bytes(color=((seq * 47) % 250, (seq * 91) % 250, 90)))

    def test_upload_read_validate_and_url_use_storage_api(self):
        image = add_product_image(product=self.product, image=self._uploaded_image())
        image.refresh_from_db()
        self.assertRegex(image.image.name, r'^products/images/[0-9a-f]{32}\.jpg$')
        # The pipeline re-encodes uploads (orientation fix, metadata stripped), so bytes
        # differ from the original; they must still be a valid JPEG of the same size.
        from io import BytesIO
        from PIL import Image
        with Image.open(BytesIO(image.image.read())) as stored:
            self.assertEqual(stored.format, 'JPEG')
        image.image.close()
        validate_product_image(image.image)
        self.assertIn(image.image.name, image.image.url)
        self.assertIn('signature=synthetic', image.image.url)
        # Pending products are not available through the public detail lookup.
        from django.http import Http404
        with self.assertRaises(Http404):
            get_public_product_by_slug(self.product.slug)
        # Authorized presentation code accepts the remote URL without .path.
        self.assertEqual(public_product_detail_context(self.product)['images'][0]['url'], image.display_image.url)

    def test_replacement_retains_old_object_and_changes_only_reference(self):
        image = add_product_image(product=self.product, image=self._uploaded_image())
        old_key = image.image.name
        replace_product_image(product=self.product, image_id=image.pk,
                              image=self._uploaded_image('replacement.png', self._png_bytes()))
        image.refresh_from_db()
        self.assertNotEqual(image.image.name, old_key)
        self.assertTrue(self.storage.exists(old_key))
        self.assertTrue(self.storage.exists(image.image.name))

    def test_row_deletion_does_not_delete_object(self):
        image = add_product_image(product=self.product, image=self._uploaded_image())
        key = image.image.name
        delete_product_image(product=self.product, image_id=image.pk)
        self.assertFalse(ProductImage.objects.filter(pk=image.pk).exists())
        self.assertTrue(self.storage.exists(key))

    def test_upload_failure_propagates_and_rolls_back_primary_change(self):
        first = add_product_image(product=self.product, image=self._distinct_image(1))
        error = ClientError({'Error': {'Code': 'AccessDenied', 'Message': 'synthetic failure'}}, 'PutObject')
        with patch.object(self.storage, '_save', side_effect=error):
            with self.assertRaises(ClientError):
                add_product_image(product=self.product, image=self._distinct_image(2), is_primary=True)
        first.refresh_from_db()
        self.assertTrue(first.is_primary)
        self.assertEqual(self.product.images.count(), 1)
        # original + display copy + thumbnail of the first image only; the failed upload left nothing.
        self.assertEqual(len(self.storage.objects), 3)

    def test_sql_rollback_leaves_uploaded_object_for_future_cleanup(self):
        with self.assertRaisesRegex(RuntimeError, 'after upload'):
            with transaction.atomic():
                image = add_product_image(product=self.product, image=self._uploaded_image())
                key = image.image.name
                raise RuntimeError('after upload')
        self.assertEqual(self.product.images.count(), 0)
        self.assertTrue(self.storage.exists(key))

    def test_invalid_image_never_reaches_storage(self):
        with patch.object(self.storage, '_save', wraps=self.storage._save) as save:
            with self.assertRaises(ValidationError):
                add_product_image(product=self.product, image=self._uploaded_image(content=b'not an image'))
        save.assert_not_called()
        self.assertEqual(self.product.images.count(), 0)
