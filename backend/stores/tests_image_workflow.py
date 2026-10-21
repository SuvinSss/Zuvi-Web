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
