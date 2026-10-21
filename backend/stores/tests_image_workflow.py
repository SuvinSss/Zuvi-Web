"""Store image request rollback and object retention without remote connections."""

from unittest.mock import patch

from botocore.exceptions import ClientError
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.core.files.storage import storages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from catalog.tests_image_workflow import admin_payload
from config.storage_errors import STORAGE_ERROR_MESSAGE
from locations.models import Address
from .models import Store
from .tests import StoreModelTestMixin, _image_bytes


class StoreImageWorkflowTests(StoreModelTestMixin, TestCase):
    def setUp(self):
        self.enterContext(override_settings(STORAGES={
            **storages.backends, 'default': {'BACKEND': 'config.tests_media_storage.RemoteStorage'},
        }))
        self.storage = storages['default']
        self.actor = get_user_model().objects.create_superuser('store-image-admin', password='test-password')
        self.client.force_login(self.actor)
        self.store = self.create_store()
        self.store.image = self.upload()
        self.store.save()
        self.old_key = self.store.image.name
        self.status = self.store.status
        self.url = reverse('stores:store_edit', args=[self.store.pk])

    def upload(self):
        return SimpleUploadedFile('store.jpg', _image_bytes('JPEG'), content_type='image/jpeg')

    def payload(self, **overrides):
        address = self.store.address
        data = {'name': self.store.name, 'store_type': self.store.store_type,
            'category': self.store.category_id, 'commission_percentage': str(self.store.commission_percentage),
            'is_active': 'on', 'address-line1': address.line1, 'address-line2': address.line2,
            'address-city': address.city, 'address-state': address.state,
            'address-postal_code': address.postal_code, 'address-country': address.country,
            'address-latitude': str(address.latitude), 'address-longitude': str(address.longitude)}
        data.update(overrides)
        return data

    def error(self):
        return ClientError({'Error': {'Code': 'AccessDenied', 'Message': 'synthetic-secret-storage-detail'}}, 'PutObject')

    def assert_retained(self):
        self.store.refresh_from_db()
        self.assertEqual(self.store.image.name, self.old_key)
        self.assertTrue(self.storage.exists(self.old_key))
        self.assertEqual(self.store.status, self.status)

    def test_edit_without_upload_retains_reference(self):
        with patch.object(self.storage, '_save', wraps=self.storage._save) as save:
            response = self.client.post(self.url, self.payload(name='Edited'))
        self.assertEqual(response.status_code, 302)
        save.assert_not_called()
        self.assert_retained()
        self.assertEqual(self.store.name, 'Edited')

    def test_replacement_retains_old_object_and_status(self):
        with patch.object(self.storage, 'delete') as delete:
            response = self.client.post(self.url, self.payload(image=self.upload()))
        self.assertEqual(response.status_code, 302)
        delete.assert_not_called()
        self.store.refresh_from_db()
        self.assertNotEqual(self.store.image.name, self.old_key)
        self.assertTrue(self.storage.exists(self.old_key))
        self.assertTrue(self.storage.exists(self.store.image.name))
        self.assertEqual(self.store.status, self.status)
        self.assertFalse(self.store.status_history.exists())

    def test_clear_retains_old_object_and_status(self):
        with patch.object(self.storage, 'delete') as delete:
            response = self.client.post(self.url, self.payload(**{'image-clear': 'on'}))
        self.assertEqual(response.status_code, 302)
        delete.assert_not_called()
        self.store.refresh_from_db()
        self.assertFalse(self.store.image)
        self.assertTrue(self.storage.exists(self.old_key))
        self.assertEqual(self.store.status, self.status)

    def test_replacement_failure_rolls_back_store_address_and_reports_generic_error(self):
        with patch.object(self.storage, '_save', side_effect=self.error()), patch.object(self.storage, 'delete') as delete, self.assertLogs('config.storage_errors', 'ERROR') as logs:
            response = self.client.post(self.url, self.payload(name='Must roll back', image=self.upload(),
                **{'address-city': 'Must roll back'}))
        delete.assert_not_called()
        self.assertEqual(response.status_code, 302)
        self.assert_retained()
        self.assertNotEqual(self.store.name, 'Must roll back')
        self.store.address.refresh_from_db()
        self.assertNotEqual(self.store.address.city, 'Must roll back')
        self.assertEqual([str(m) for m in get_messages(response.wsgi_request)], [STORAGE_ERROR_MESSAGE])
        self.assertIn('synthetic-secret-storage-detail', '\n'.join(logs.output))

    def test_storage_failure_rendering_get_is_generic_without_redirect_loop(self):
        with patch.object(self.storage, "url", side_effect=self.error()), self.assertLogs("config.storage_errors", "ERROR"):
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.content.decode(), STORAGE_ERROR_MESSAGE)
        self.assertNotIn("Location", response)
        self.assert_retained()

    def test_existing_image_validation_storage_read_failure_is_handled(self):
        with patch.object(self.storage, '_open', side_effect=self.error()), self.assertLogs('config.storage_errors', 'ERROR'):
            response = self.client.post(self.url, self.payload(name='Must roll back'))
        self.assertEqual(response.status_code, 302)
        self.assert_retained()
        self.assertNotEqual(self.store.name, 'Must roll back')

    def test_create_upload_failure_rolls_back_new_store_and_address(self):
        counts = Store.objects.count(), Address.objects.count()
        with patch.object(self.storage, '_save', side_effect=self.error()), self.assertLogs('config.storage_errors', 'ERROR'):
            response = self.client.post(reverse('stores:store_create'), self.payload(name='Failed store', image=self.upload()))
        self.assertEqual(response.status_code, 302)
        self.assertEqual((Store.objects.count(), Address.objects.count()), counts)
        self.assertEqual([str(m) for m in get_messages(response.wsgi_request)], [STORAGE_ERROR_MESSAGE])

    def test_invalid_image_rejected_without_storage_write(self):
        invalid = SimpleUploadedFile('bad.jpg', b'not an image', content_type='image/jpeg')
        with patch.object(self.storage, '_save') as save:
            response = self.client.post(self.url, self.payload(image=invalid))
        self.assertEqual(response.status_code, 200)
        save.assert_not_called()
        self.assert_retained()

    def test_admin_replacement_failure_preserves_old_reference_and_log(self):
        from django.contrib.admin.models import LogEntry
        url = reverse('admin:stores_store_change', args=[self.store.pk])
        data = admin_payload(self.client.get(url))
        data.update({'name': 'Must roll back', 'image': self.upload()})
        before = LogEntry.objects.count()
        with patch.object(self.storage, '_save', side_effect=self.error()), self.assertLogs('config.storage_errors', 'ERROR'):
            response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        self.assert_retained()
        self.assertNotEqual(self.store.name, 'Must roll back')
        self.assertEqual(LogEntry.objects.count(), before)
        self.assertEqual([str(m) for m in get_messages(response.wsgi_request)], [STORAGE_ERROR_MESSAGE])

    def test_admin_clear_retains_old_object(self):
        url = reverse('admin:stores_store_change', args=[self.store.pk])
        data = admin_payload(self.client.get(url))
        data['image-clear'] = 'on'
        with patch.object(self.storage, 'delete') as delete:
            response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        delete.assert_not_called()
        self.store.refresh_from_db()
        self.assertFalse(self.store.image)
        self.assertTrue(self.storage.exists(self.old_key))
        self.assertEqual(self.store.status, self.status)

    def tearDown(self):
        self.assertEqual(self.storage.path_calls, 0)
        super().tearDown()
