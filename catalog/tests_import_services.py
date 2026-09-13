import uuid
from decimal import Decimal
from unittest.mock import patch
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from catalog.services import update_product
from inventory.models import InventoryTransaction
from .tests_import_contract import ImportTestMixin
from .models import ImportJob, ImportRow, Product, ProductImage
from .import_contract import ImportProblem
from .import_services import create_job, approve_job, execute_job


class ImportServiceTests(ImportTestMixin, TestCase):
    def test_create_pending_images_prices_stock_and_receipt_together(self):
        job = self.job([self.raw(image_1='front.png', image_2='back.png', primary_image_index='2', opening_stock='2.5', opening_stock_reason='Synthetic counted opening', profit_margin_type='FIXED', profit_margin='2')], approved=True)
        job = execute_job(job_id=job.pk, actor=self.admin)
        row = job.rows.get()
        product = row.product
        self.assertEqual(job.status, 'COMPLETED')
        self.assertEqual(row.status, 'SUCCEEDED')
        self.assertEqual(product.status, 'PENDING')
        self.assertIsNone(product.approved_by_id)
        self.assertEqual(product.final_price, Decimal('12.00'))
        self.assertEqual(product.stock_quantity, Decimal('2.500'))
        self.assertEqual(product.images.count(), 2)
        self.assertEqual(product.images.filter(is_primary=True).count(), 1)
        self.assertEqual(set(row.result['image_ids']), set(product.images.values_list('pk', flat=True)))
        self.assertTrue(InventoryTransaction.objects.filter(pk=row.result['opening_transaction_id'], product=product).exists())
        execute_job(job_id=job.pk, actor=self.admin)
        self.assertEqual(Product.objects.count(), 1)
        self.assertEqual(InventoryTransaction.objects.count(), 1)

    def test_blank_stock_creates_no_movement(self):
        job = self.job(approved=True)
        execute_job(job_id=job.pk, actor=self.admin)
        self.assertEqual(InventoryTransaction.objects.count(), 0)
        self.assertEqual(Product.objects.get().stock_quantity, 0)

    def test_storage_failure_rolls_back_every_service_and_resume(self):
        job = self.job([self.raw(image_1='front.png', image_2='back.png', opening_stock='3', opening_stock_reason='Synthetic count')], approved=True)
        from django.core.files.storage import default_storage
        original, calls = default_storage.save, []
        def fail_second(*args, **kwargs):
            calls.append(1)
            if len(calls) == 2:
                raise OSError('private storage details must not leak')
            return original(*args, **kwargs)
        with patch.object(default_storage, 'save', side_effect=fail_second), self.assertRaises(ImportProblem):
            execute_job(job_id=job.pk, actor=self.admin)
        self.assertEqual(Product.objects.count(), 0)
        self.assertEqual(ProductImage.objects.count(), 0)
        self.assertEqual(InventoryTransaction.objects.count(), 0)
        row = job.rows.get()
        self.assertEqual(row.status, 'FAILED')
        self.assertTrue(row.result['orphan_objects_possible'])
        self.assertNotIn('private storage details', str(row.errors))
        self.assertTrue(any(self.media.rglob('*.png')))
        execute_job(job_id=job.pk, actor=self.admin, resume=True)
        self.assertEqual(Product.objects.count(), 1)
        self.assertEqual(ProductImage.objects.count(), 2)
        self.assertEqual(InventoryTransaction.objects.count(), 1)

    def test_failure_after_opening_stock_rolls_back_receipt_and_product(self):
        job = self.job([self.raw(opening_stock='2', opening_stock_reason='Synthetic')], approved=True)
        from .import_services import _write_product
        def fail(*args, **kwargs):
            _write_product(*args, **kwargs)
            raise IntegrityError('unrelated constraint failure')
        with patch('catalog.import_services._write_product', side_effect=fail):
            result = execute_job(job_id=job.pk, actor=self.admin)
        self.assertEqual(result.status, 'COMPLETED_WITH_ERRORS')
        self.assertEqual(Product.objects.count(), 0)
        self.assertEqual(InventoryTransaction.objects.count(), 0)
        self.assertEqual(job.rows.get().status, 'FAILED')

    def test_same_submission_nonce_idempotent_and_changed_bytes_conflict(self):
        key = uuid.uuid4()
        a = create_job(actor=self.admin, store=self.store, content=self.csv(), filename='x.csv', job_id=key)
        b = create_job(actor=self.admin, store=self.store, content=self.csv(), filename='x.csv', job_id=key)
        self.assertEqual(a.pk, b.pk)
        with self.assertRaises(ImportProblem):
            create_job(actor=self.admin, store=self.store, content=self.csv([self.raw(name='changed')]), filename='x.csv', job_id=key)

    def test_identical_preparation_resolves_canonical_job(self):
        first = self.job(ready=True)
        duplicate = self.job(ready=True)
        self.assertEqual(duplicate.status, 'DUPLICATE')
        self.assertEqual(duplicate.duplicate_of_id, first.pk)
        self.assertIsNone(duplicate.fingerprint)

    def test_original_provenance_after_authorized_sku_edit(self):
        first = self.job([self.raw(image_1='front.png', opening_stock='2', opening_stock_reason='Synthetic')], approved=True)
        execute_job(job_id=first.pk, actor=self.admin)
        product = first.rows.get().product
        update_product(product=product, product_data={'sku': 'MANUAL-EDIT', 'name': 'Authorized later name'}, updated_by=self.admin)
        # Different original CSV bytes, same normalized product intent; own approval.
        second = self.job([self.raw(external_sku=' SOURCE-001 ', image_1='front.png', opening_stock='2.000', opening_stock_reason='Synthetic')], approved=True)
        execute_job(job_id=second.pk, actor=self.admin)
        row = second.rows.get()
        self.assertEqual(row.status, 'ALREADY_IMPORTED')
        self.assertEqual(row.product_id, product.pk)
        product.refresh_from_db()
        self.assertEqual((product.sku, product.name), ('MANUAL-EDIT', 'Authorized later name'))
        self.assertEqual((Product.objects.count(), ProductImage.objects.count(), InventoryTransaction.objects.count()), (1, 1, 1))
        changed = self.job([self.raw(name='Changed import intent')], ready=True)
        self.assertEqual(changed.status, 'INVALID')
        self.assertEqual(changed.rows.get().errors[0]['code'], 'PROVENANCE_CONFLICT')

    def test_unrelated_sku_is_explicit_conflict(self):
        self.create_public_product(store=self.store, sku='SOURCE-001')
        job = self.job(ready=True)
        self.assertEqual(job.status, 'INVALID')
        self.assertEqual(job.rows.get().errors[0]['code'], 'SKU_CONFLICT')

    def test_approval_stale_hash_and_reference_change(self):
        job = self.job(ready=True)
        with self.assertRaises(ImportProblem):
            approve_job(job_id=job.pk, actor=self.admin, expected_hash='0' * 64)
        job = approve_job(job_id=job.pk, actor=self.admin, expected_hash=job.fingerprint)
        self.category.name = 'Renamed reference'
        self.category.save()
        with self.assertRaises(ImportProblem):
            execute_job(job_id=job.pk, actor=self.admin)
        self.assertEqual(Product.objects.count(), 0)

    def test_inputs_approval_and_receipts_are_immutable(self):
        job = self.job(approved=True)
        for update in ({'csv_bytes': b'changed'}, {'approved_by': self.admin}, {'store': self.store}):
            with self.assertRaises(ValidationError):
                ImportJob.objects.filter(pk=job.pk).update(**update)
        with self.assertRaises(ValidationError):
            job.rows.update(payload={})
        execute_job(job_id=job.pk, actor=self.admin)
        with self.assertRaises(ValidationError):
            job.rows.update(result={})
        with self.assertRaises(ValidationError):
            job.rows.get().delete()

    def test_database_null_and_empty_constraints(self):
        job = self.job()
        from django.db import connection
        for status, fp, bundle in [('READY', None, None), ('READY', '', uuid.uuid4()), ('RUNNING', 'x' * 64, uuid.uuid4())]:
            with self.subTest(status=status, fp=fp), self.assertRaises(IntegrityError), transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute('UPDATE catalog_importjob SET status=%s,fingerprint=%s,image_bundle_key=%s WHERE id=%s', [status, fp, bundle, job.pk])
        row = job.rows.get()
        for sku in (None, ''):
            with self.subTest(sku=sku), self.assertRaises(IntegrityError), transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute('UPDATE catalog_importrow SET external_sku=%s WHERE id=%s', [sku, row.pk])

    def test_inconsistent_provenance_store_is_conflict(self):
        first = self.job(approved=True)
        execute_job(job_id=first.pk, actor=self.admin)
        Product.objects.filter(pk=first.rows.get().product_id).update(store=self.create_store())
        second = self.job([self.raw(external_sku=' SOURCE-001 ')], ready=True)
        self.assertEqual(second.status, 'INVALID')
        self.assertEqual(second.rows.get().errors[0]['code'], 'PROVENANCE_CONFLICT')

    def test_new_occupant_of_original_sku_is_conflict(self):
        first = self.job(approved=True)
        execute_job(job_id=first.pk, actor=self.admin)
        product = first.rows.get().product
        update_product(product=product, product_data={'sku': 'EDITED'}, updated_by=self.admin)
        self.create_public_product(store=self.store, sku='SOURCE-001')
        second = self.job([self.raw(external_sku=' SOURCE-001 ')], ready=True)
        self.assertEqual(second.status, 'INVALID')
        self.assertEqual(second.rows.get().errors[0]['code'], 'PROVENANCE_CONFLICT')

    def test_approved_image_change_blocks_all_writes(self):
        job = self.job([self.raw(image_1='front.png')], approved=True)
        meta = job.image_manifest['front.png']
        path = self.root / 'snapshots' / str(job.image_bundle_key) / (meta['sha256'] + meta['suffix'])
        path.chmod(0o600)
        path.write_bytes(b'changed')
        with self.assertRaises(ImportProblem):
            execute_job(job_id=job.pk, actor=self.admin)
        self.assertEqual(Product.objects.count(), 0)
        job.refresh_from_db()
        self.assertEqual(job.status, 'PAUSED')
