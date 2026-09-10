"""Image mutations exercise PostgreSQL locks and offline object storage."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

from botocore.exceptions import ClientError
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.core.exceptions import ValidationError
from django.core.files.storage import storages
from django.db import IntegrityError, close_old_connections, connection
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import AdminAuditLog
from config.storage_errors import STORAGE_ERROR_MESSAGE
from .models import Product, ProductImage, ProductStatus, ProductStatusHistory, ProductPriceHistory
from .public import get_public_product_by_slug
from .services import (PRICING_FIELDS, add_product_image, create_product,
                       delete_product_image, mutate_product_images, replace_product_image)
from .tests import CatalogTestMixin


def form_payload(form):
    """Submit actual admin form fields, including hidden inline management IDs."""
    data = {}
    for name, field in form.fields.items():
        if isinstance(field, forms.FileField) or field.disabled:
            continue
        value = form[name].value()
        if isinstance(field.widget, forms.CheckboxInput):
            if value:
                data[form.add_prefix(name)] = 'on'
        elif value is not None:
            data[form.add_prefix(name)] = value
    return data


def admin_payload(response):
    data = form_payload(response.context['adminform'].form)
    for inline in response.context['inline_admin_formsets']:
        data.update(form_payload(inline.formset.management_form))
        for form in inline.formset.forms:
            data.update(form_payload(form))
    return data


class WorkflowFixtures(CatalogTestMixin):
    def setUp(self):
        super().setUp()
        self.enterContext(override_settings(STORAGES={
            **storages.backends,
            'default': {'BACKEND': 'config.tests_media_storage.RemoteStorage'},
        }))
        self.storage = storages['default']
        self.actor = get_user_model().objects.create_superuser('image-admin', password='test-password')
        self.product = self.create_product()

    def add(self, product=None):
        return add_product_image(product=product or self.product, image=self._uploaded_image(), changed_by=self.actor)

    def approve_fixture(self, product=None):
        product = product or self.product
        Product.objects.filter(pk=product.pk).update(status=ProductStatus.APPROVED,
            approved_by=self.actor, approved_at=timezone.now())
        product.refresh_from_db()

    def assert_pending(self):
        self.product.refresh_from_db()
        self.assertEqual(self.product.status, ProductStatus.PENDING)
        self.assertIsNone(self.product.approved_at)
        self.assertIsNone(self.product.approved_by_id)
        history = self.product.status_history.get()
        self.assertEqual((history.old_status, history.new_status), (ProductStatus.APPROVED, ProductStatus.PENDING))
        self.assertEqual(history.changed_by, self.actor)
        self.assertTrue(AdminAuditLog.objects.filter(action=AdminAuditLog.Action.PRODUCT_STATUS_CHANGED,
            metadata__product_id=self.product.pk).exists())
        from django.http import Http404
        with self.assertRaises(Http404):
            get_public_product_by_slug(self.product.slug)

    def storage_error(self):
        return ClientError({'Error': {'Code': 'AccessDenied', 'Message': 'synthetic-private-backend-detail'}}, 'PutObject')

    def tearDown(self):
        self.assertEqual(self.storage.path_calls, 0)
        super().tearDown()


class ImageServiceWorkflowTests(WorkflowFixtures, TestCase):
    def test_one_through_five_succeed_sixth_fails(self):
        for number in range(1, 6):
            self.add()
            self.assertEqual(self.product.images.count(), number)
        with self.assertRaisesMessage(ValidationError, 'at most 5'):
            self.add()
        self.assertEqual(len(self.storage.objects), 5)
        self.assertEqual(self.product.images.filter(is_primary=True).count(), 1)

    def test_add_reapproves_without_price_changes(self):
        self.add()
        self.approve_fixture()
        prices = {name: getattr(self.product, name) for name in PRICING_FIELDS}
        self.add()
        self.assert_pending()
        self.assertEqual(prices, {name: getattr(self.product, name) for name in PRICING_FIELDS})
        self.assertFalse(self.product.price_history.exists())

    def test_remove_reapproves_and_retains_blob(self):
        image = self.add()
        self.add()
        self.approve_fixture()
        with patch.object(self.storage, 'delete') as delete:
            delete_product_image(product=self.product, image_id=image.pk, changed_by=self.actor)
        delete.assert_not_called()
        self.assertTrue(self.storage.exists(image.image.name))
        self.assert_pending()

    def test_replacing_only_image_reapproves_and_retains_old_blob(self):
        image = self.add()
        self.approve_fixture()
        with patch.object(self.storage, 'delete') as delete:
            replacement = replace_product_image(product=self.product, image_id=image.pk,
                image=self._uploaded_image(), changed_by=self.actor)
        delete.assert_not_called()
        self.assertNotEqual(image.image.name, replacement.image.name)
        self.assertTrue(self.storage.exists(image.image.name))
        self.assertEqual(self.product.images.count(), 1)
        self.assert_pending()

    def test_metadata_only_changes_do_not_reapprove(self):
        image = self.add()
        second = self.add()
        self.approve_fixture()
        mutate_product_images(mutations={self.product.pk: {'update': {
            image.pk: {'alt_text': 'New text', 'sort_order': 2, 'is_primary': False},
            second.pk: {'is_primary': True},
        }}}, changed_by=self.actor)
        self.product.refresh_from_db()
        self.assertEqual(self.product.status, ProductStatus.APPROVED)
        self.assertFalse(self.product.status_history.exists())
        self.assertEqual(self.product.images.get(is_primary=True).pk, second.pk)

    def test_other_statuses_preserved_and_allow_zero(self):
        for status in (ProductStatus.DRAFT, ProductStatus.REJECTED, ProductStatus.PENDING, ProductStatus.INACTIVE):
            with self.subTest(status=status):
                Product.objects.filter(pk=self.product.pk).update(status=status)
                image = self.add()
                replace_product_image(product=self.product, image_id=image.pk, image=self._uploaded_image())
                delete_product_image(product=self.product, image_id=image.pk)
                self.product.refresh_from_db()
                self.assertEqual(self.product.status, status)
                self.assertEqual(self.product.images.count(), 0)
        self.assertFalse(self.product.status_history.exists())

    def test_last_image_uses_fresh_locked_status(self):
        image = self.add()
        Product.objects.filter(pk=self.product.pk).update(status=ProductStatus.APPROVED)
        with self.assertRaisesMessage(ValidationError, 'at least one'):
            delete_product_image(product=self.product, image_id=image.pk)
        self.assertTrue(ProductImage.objects.filter(pk=image.pk).exists())

    def test_complete_batch_cannot_delete_all_approved_images(self):
        ids = [self.add().pk, self.add().pk]
        self.approve_fixture()
        with self.assertRaisesMessage(ValidationError, 'at least one'):
            mutate_product_images(mutations={self.product.pk: {'delete': ids}}, changed_by=self.actor)
        self.assertEqual(self.product.images.count(), 2)
        self.assertFalse(self.product.status_history.exists())

    def test_delete_and_add_at_capacity_is_one_valid_batch(self):
        images = [self.add() for _ in range(5)]
        self.approve_fixture()
        mutate_product_images(mutations={self.product.pk: {'delete': [images[0].pk],
            'add': [{'image': self._uploaded_image()}]}}, changed_by=self.actor)
        self.assertEqual(self.product.images.count(), 5)
        self.assert_pending()

    def test_multiple_products_are_validated_before_any_storage_write(self):
        first = self.add()
        other = self.create_product()
        only = self.add(other)
        self.approve_fixture(other)
        with patch.object(self.storage, '_save', wraps=self.storage._save) as save:
            with self.assertRaises(ValidationError):
                mutate_product_images(mutations={self.product.pk: {'add': [{'image': self._uploaded_image()}]},
                    other.pk: {'delete': [only.pk]}})
        save.assert_not_called()
        self.assertTrue(ProductImage.objects.filter(pk=first.pk).exists())

    def test_first_upload_failure_preserves_approval_and_primary(self):
        first = self.add()
        self.approve_fixture()
        with patch.object(self.storage, '_save', side_effect=self.storage_error()):
            with self.assertRaises(ClientError):
                self.add()
        self.product.refresh_from_db()
        first.refresh_from_db()
        self.assertEqual(self.product.status, ProductStatus.APPROVED)
        self.assertTrue(first.is_primary)
        self.assertEqual(self.product.images.count(), 1)
        self.assertFalse(self.product.status_history.exists())

    def test_replacement_failure_preserves_reference_and_approval(self):
        image = self.add()
        self.approve_fixture()
        key = image.image.name
        with patch.object(self.storage, '_save', side_effect=OSError('synthetic disk failure')):
            with self.assertRaises(OSError):
                replace_product_image(product=self.product, image_id=image.pk, image=self._uploaded_image())
        image.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(image.image.name, key)
        self.assertEqual(self.product.status, ProductStatus.APPROVED)

    def test_database_failure_rolls_back_images_status_and_history(self):
        self.add()
        self.approve_fixture()
        with patch.object(ProductStatusHistory.objects, 'create', side_effect=IntegrityError('synthetic db failure')):
            with self.assertRaises(IntegrityError):
                self.add()
        self.product.refresh_from_db()
        self.assertEqual(self.product.status, ProductStatus.APPROVED)
        self.assertEqual(self.product.images.count(), 1)
        self.assertEqual(len(self.storage.objects), 2)
        self.assertFalse(self.product.status_history.exists())

    def test_later_upload_failure_rolls_back_whole_existing_product_batch(self):
        self.add()
        self.approve_fixture()
        original = self.storage._save
        calls = 0
        def failing_save(name, content):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise self.storage_error()
            return original(name, content)
        with patch.object(self.storage, '_save', side_effect=failing_save), patch.object(self.storage, 'delete') as delete:
            with self.assertRaises(ClientError):
                mutate_product_images(mutations={self.product.pk: {'add': [
                    {'image': self._uploaded_image()}, {'image': self._uploaded_image()}]}})
        delete.assert_not_called()
        self.product.refresh_from_db()
        self.assertEqual(self.product.status, ProductStatus.APPROVED)
        self.assertEqual(self.product.images.count(), 1)
        self.assertEqual(len(self.storage.objects), 2)
        self.assertFalse(self.product.status_history.exists())

    def test_multi_image_creation_failure_rolls_back_all_database_records(self):
        before = [model.objects.count() for model in (Product, ProductImage, ProductStatusHistory, ProductPriceHistory, AdminAuditLog)]
        original = self.storage._save
        def later_failure(name, content):
            if self.storage.objects:
                raise self.storage_error()
            return original(name, content)
        with patch.object(self.storage, '_save', side_effect=later_failure):
            with self.assertRaises(ClientError):
                create_product(store=self.product.store, created_by=self.actor,
                    product_data={'name': 'Failed creation', 'sku': 'failed', 'category': self.product.category,
                                  'store_price': self.product.store_price},
                    images=[self._uploaded_image(), self._uploaded_image()])
        self.assertEqual(before, [model.objects.count() for model in (Product, ProductImage, ProductStatusHistory, ProductPriceHistory, AdminAuditLog)])
        self.assertEqual(len(self.storage.objects), 1)


class ImagePortalWorkflowTests(WorkflowFixtures, TestCase):
    def test_management_and_store_direct_post_capacity_and_reapproval(self):
        store_user = self.create_store_user(self.product.store)
        for user, route in ((self.actor, 'product_images'), (store_user, 'store_product_images')):
            with self.subTest(route=route):
                self.client.force_login(user)
                url = reverse('catalog:' + route, args=[self.product.pk])
                if not self.product.images.exists():
                    self.add()
                self.approve_fixture()
                response = self.client.post(url, {'image': self._uploaded_image()})
                self.assertEqual(response.status_code, 302)
                self.product.refresh_from_db()
                self.assertEqual(self.product.status, ProductStatus.PENDING)
                while self.product.images.count() < 5:
                    self.add()
                response = self.client.post(url, {'image': self._uploaded_image()})
                self.assertEqual(self.product.images.count(), 5)
                self.assertContains(response, 'at most 5')
                ProductImage.objects.filter(product=self.product).exclude(is_primary=True).delete()

    def test_foreign_image_ids_remain_404_on_own_product_routes(self):
        other = self.create_product()
        foreign = self.add(other)
        own = self.add()
        store_user = self.create_store_user(self.product.store)
        for user, prefix in ((self.actor, "product"), (store_user, "store_product")):
            self.client.force_login(user)
            for operation in ("delete", "set_primary"):
                url = reverse(f"catalog:{prefix}_image_{operation}", args=[self.product.pk, foreign.pk])
                self.assertEqual(self.client.post(url).status_code, 404)
        self.assertTrue(ProductImage.objects.filter(pk=foreign.pk).exists())
        self.assertTrue(ProductImage.objects.filter(pk=own.pk).exists())

    def test_portal_storage_failure_is_generic_logged_and_not_success(self):
        self.client.force_login(self.actor)
        url = reverse('catalog:product_images', args=[self.product.pk])
        with patch.object(self.storage, '_save', side_effect=self.storage_error()), self.assertLogs('config.storage_errors', 'ERROR') as logs:
            response = self.client.post(url, {'image': self._uploaded_image()})
        self.assertEqual(response.status_code, 302)
        self.assertEqual([str(m) for m in get_messages(response.wsgi_request)], [STORAGE_ERROR_MESSAGE])
        self.assertIn('synthetic-private-backend-detail', '\n'.join(logs.output))
        self.assertFalse(self.product.images.exists())

    def test_store_multiupload_failure_returns_no_success_and_no_product(self):
        self.client.force_login(self.create_store_user(self.product.store))
        original = self.storage._save
        def later_failure(name, content):
            if self.storage.objects:
                raise self.storage_error()
            return original(name, content)
        payload = {'name': 'New upload', 'sku': 'multi', 'category': self.product.category_id,
            'store_price': '100.00', 'unit': self.product.unit, 'unit_value': self.product.unit_value,
            'low_stock_threshold': '0', 'images': [self._uploaded_image(), self._uploaded_image()]}
        with patch.object(self.storage, '_save', side_effect=later_failure), self.assertLogs('config.storage_errors', 'ERROR'):
            response = self.client.post(reverse('catalog:store_product_create'), payload)
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Product.objects.filter(sku='multi').exists())
        self.assertEqual([str(m) for m in get_messages(response.wsgi_request)], [STORAGE_ERROR_MESSAGE])
        self.assertEqual(len(self.storage.objects), 1)


class ImageAdminWorkflowTests(WorkflowFixtures, TestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.actor)

    def post_image(self, record=None, **overrides):
        url = reverse('admin:catalog_productimage_change', args=[record.pk]) if record else reverse('admin:catalog_productimage_add')
        data = admin_payload(self.client.get(url))
        data.update(overrides)
        return self.client.post(url, data)

    def test_standalone_add_limit_and_reapproval(self):
        self.add()
        self.approve_fixture()
        response = self.post_image(product=self.product.pk, image=self._uploaded_image(), sort_order=0)
        self.assertEqual(response.status_code, 302)
        self.assert_pending()
        while self.product.images.count() < 5:
            self.add()
        response = self.post_image(product=self.product.pk, image=self._uploaded_image(), sort_order=0)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.product.images.count(), 5)
        self.assertIn('at most 5', ' '.join(str(m) for m in get_messages(response.wsgi_request)))

    def test_standalone_replace_and_reparent_rejection(self):
        image = self.add()
        other = self.create_product()
        self.approve_fixture()
        response = self.post_image(image, product=other.pk, alt_text='forged')
        self.assertEqual(response.status_code, 302)
        image.refresh_from_db()
        self.assertEqual(image.product_id, self.product.pk)
        self.assertEqual(image.alt_text, '')
        self.assertFalse(self.product.status_history.exists())
        response = self.post_image(image, **{'image': self._uploaded_image()})
        self.assertEqual(response.status_code, 302)
        self.assert_pending()

    def test_standalone_last_image_delete_rejected(self):
        image = self.add()
        self.approve_fixture()
        response = self.client.post(reverse('admin:catalog_productimage_delete', args=[image.pk]), {'post': 'yes'})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(ProductImage.objects.filter(pk=image.pk).exists())
        self.assertFalse(self.product.status_history.exists())

    def test_bulk_delete_all_rejected_without_admin_log_entries(self):
        from django.contrib.admin.models import LogEntry
        images = [self.add(), self.add()]
        self.approve_fixture()
        before = LogEntry.objects.count()
        response = self.client.post(reverse('admin:catalog_productimage_changelist'), {
            'action': 'delete_selected', '_selected_action': [im.pk for im in images], 'post': 'yes'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.product.images.count(), 2)
        self.assertEqual(LogEntry.objects.count(), before)

    def test_bulk_delete_one_per_product_reapproves_both(self):
        other = self.create_product()
        images = [self.add(), self.add(other)]
        self.add()
        self.add(other)
        self.approve_fixture()
        self.approve_fixture(other)
        response = self.client.post(reverse('admin:catalog_productimage_changelist'), {
            'action': 'delete_selected', '_selected_action': [im.pk for im in reversed(images)], 'post': 'yes'})
        self.assertEqual(response.status_code, 302)
        self.assert_pending()
        other.refresh_from_db()
        self.assertEqual(other.status, ProductStatus.PENDING)

    def inline_payload(self):
        url = reverse('admin:catalog_product_change', args=[self.product.pk])
        response = self.client.get(url)
        return url, admin_payload(response)

    def test_forged_inline_sixth_image_rejected(self):
        for _ in range(5):
            self.add()
        url, data = self.inline_payload()
        data.update({'images-TOTAL_FORMS': '6', 'images-5-image': self._uploaded_image(), 'images-5-sort_order': 5})
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.product.images.count(), 5)
        self.assertIn('at most 5', ' '.join(str(m) for m in get_messages(response.wsgi_request)))

    def test_inline_batch_delete_all_rejected(self):
        self.add()
        self.add()
        self.approve_fixture()
        url, data = self.inline_payload()
        data.update({'images-0-DELETE': 'on', 'images-1-DELETE': 'on'})
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.product.images.count(), 2)
        self.assertFalse(self.product.status_history.exists())

    def test_inline_replace_reapproves_preserves_prices_and_admin_logging(self):
        from django.contrib.admin.models import LogEntry
        self.add()
        self.approve_fixture()
        prices = {name: getattr(self.product, name) for name in PRICING_FIELDS}
        url, data = self.inline_payload()
        data['images-0-image'] = self._uploaded_image()
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        self.assert_pending()
        self.assertEqual(prices, {name: getattr(self.product, name) for name in PRICING_FIELDS})
        self.assertTrue(LogEntry.objects.filter(object_id=str(self.product.pk), action_flag=2).exists())

    def test_inline_later_upload_failure_rolls_back_parent_edit(self):
        url, data = self.inline_payload()
        data.update({'name': 'Should roll back', 'images-TOTAL_FORMS': '2',
            'images-0-image': self._uploaded_image(), 'images-0-sort_order': 0,
            'images-1-image': self._uploaded_image(), 'images-1-sort_order': 1})
        original = self.storage._save
        def later_failure(name, content):
            if self.storage.objects:
                raise self.storage_error()
            return original(name, content)
        with patch.object(self.storage, '_save', side_effect=later_failure), self.assertLogs('config.storage_errors', 'ERROR'):
            response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        self.product.refresh_from_db()
        self.assertNotEqual(self.product.name, 'Should roll back')
        self.assertEqual(self.product.images.count(), 0)
        self.assertEqual(len(self.storage.objects), 1)
        self.assertEqual([str(m) for m in get_messages(response.wsgi_request)], [STORAGE_ERROR_MESSAGE])

    def test_parent_product_and_store_deletion_cannot_remove_approved_last_image(self):
        self.add()
        self.approve_fixture()
        for model, obj in [('catalog_product', self.product), ('stores_store', self.product.store)]:
            response = self.client.post(reverse('admin:' + model + '_delete', args=[obj.pk]), {'post': 'yes'})
            self.assertIn(response.status_code, (302, 403))
            self.assertTrue(Product.objects.filter(pk=self.product.pk).exists())
            self.assertEqual(self.product.images.count(), 1)


class ImageConcurrencyTests(WorkflowFixtures, TransactionTestCase):
    def test_concurrent_additions_serialize_at_five(self):
        self.assertEqual(connection.vendor, 'postgresql')
        for _ in range(4):
            self.add()
        gate = Barrier(2)
        pk = self.product.pk
        def upload():
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '5s'")
                product = Product.objects.get(pk=pk)
                gate.wait(timeout=10)
                try:
                    add_product_image(product=product, image=self._uploaded_image())
                    return 'saved'
                except ValidationError:
                    return 'capacity'
            finally:
                connection.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(upload) for _ in range(2)]
            results = [future.result(timeout=20) for future in futures]
        self.assertCountEqual(results, ['saved', 'capacity'])
        self.assertEqual(self.product.images.count(), 5)
        self.assertEqual(self.product.images.filter(is_primary=True).count(), 1)
