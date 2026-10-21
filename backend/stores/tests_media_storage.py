"""Store ImageField/ModelForm compatibility without a local uploaded-file path."""

from unittest.mock import patch

from botocore.exceptions import ClientError
from django.core.files.storage import storages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.test import TestCase, override_settings

from .forms import StoreForm
from .tests import StoreModelTestMixin, _image_bytes


class StoreRemoteStorageTests(StoreModelTestMixin, TestCase):
    def setUp(self):
        self.enterContext(override_settings(STORAGES={
            **storages.backends,
            'default': {'BACKEND': 'config.tests_media_storage.RemoteStorage'},
        }))
        self.storage = storages['default']
        self.store = self.create_store()
        self.store.image = self.upload()
        self.store.full_clean()
        self.store.save()
        self.store.refresh_from_db()
        self.old_key = self.store.image.name

    def tearDown(self):
        self.assertEqual(self.storage.path_calls, 0)
        super().tearDown()

    def upload(self, name='store.jpg', content=None):
        return SimpleUploadedFile(name, _image_bytes('JPEG') if content is None else content, content_type='image/jpeg')

    def form(self, files=None, **overrides):
        data = {
            'name': 'Edited Store',
            'store_type': self.store.store_type,
            'category': self.store.category_id,
            'commission_percentage': self.store.commission_percentage,
            'is_active': self.store.is_active,
        }
        data.update(overrides)
        return StoreForm(data, files=files, instance=self.store)

    def test_store_upload_uses_existing_key_format_and_remote_url(self):
        self.assertRegex(self.old_key, r'^stores/images/[0-9a-f]{32}\.jpg$')
        self.assertEqual(self.store.image.read(), _image_bytes('JPEG'))
        self.assertIn('signature=synthetic', self.store.image.url)
        self.assertIn(self.old_key, StoreForm(instance=self.store).as_p())

    def test_edit_retains_existing_remote_image_without_reupload(self):
        form = self.form()
        with patch.object(self.storage, '_save', wraps=self.storage._save) as save:
            self.assertTrue(form.is_valid(), form.errors)
            form.save()
        save.assert_not_called()
        self.store.refresh_from_db()
        self.assertEqual(self.store.name, 'Edited Store')
        self.assertEqual(self.store.image.name, self.old_key)
        self.assertEqual(len(self.storage.objects), 1)

    def test_replacement_keeps_old_object(self):
        form = self.form(files={'image': self.upload('replacement.jpg')})
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.store.refresh_from_db()
        self.assertNotEqual(self.store.image.name, self.old_key)
        self.assertTrue(self.storage.exists(self.old_key))
        self.assertTrue(self.storage.exists(self.store.image.name))

    def test_clear_removes_reference_without_deleting_object(self):
        form = self.form(**{'image-clear': 'on'})
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.store.refresh_from_db()
        self.assertFalse(self.store.image)
        self.assertTrue(self.storage.exists(self.old_key))

    def test_storage_failure_keeps_existing_database_reference(self):
        form = self.form(files={'image': self.upload('replacement.jpg')})
        self.assertTrue(form.is_valid(), form.errors)
        error = ClientError({'Error': {'Code': 'AccessDenied', 'Message': 'synthetic failure'}}, 'PutObject')
        with patch.object(self.storage, '_save', side_effect=error):
            with self.assertRaises(ClientError):
                # Match store_edit_view's transaction and let it roll back
                # before inspecting the database outside the failed operation.
                with transaction.atomic():
                    form.save()
        self.store.refresh_from_db()
        self.assertEqual(self.store.image.name, self.old_key)
        self.assertNotEqual(self.store.name, 'Edited Store')

    def test_invalid_image_is_rejected_before_upload(self):
        form = self.form(files={'image': self.upload(content=b'not an image')})
        with patch.object(self.storage, '_save', wraps=self.storage._save) as save:
            self.assertFalse(form.is_valid())
        self.assertIn('image', form.errors)
        save.assert_not_called()
