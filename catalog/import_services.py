"""Durable importer orchestration; commerce writes use existing services only."""
from contextlib import contextmanager
from datetime import timedelta, date
from decimal import Decimal
import hashlib
import logging
from pathlib import Path
import uuid

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.base import ContentFile
from django.db import connection, transaction, DatabaseError, IntegrityError
from django.db.models import Count, F
from django.utils import timezone

from inventory.services import record_opening_stock
from stores.models import Store
from .import_contract import (ImportProblem, VERSION, PRICING_FIELDS, bind_images, digest,
                             fingerprint, normalize, parse_csv, reference_catalogue)
from .import_files import prepare_bundle, read_bundle_image, verify_bundle, staging_root
from .import_permissions import require_action, require_capabilities, require_participants
from .models import ImportJob, ImportRow, Product, ProductStatus
from .services import create_product, apply_admin_pricing, mutate_product_images

logger = logging.getLogger(__name__)
TERMINAL = ('SUCCEEDED', 'ALREADY_IMPORTED')
LEASE_SECONDS = 300


def lock_identifier(namespace, identity):
    # Python hash() is process-randomized; this key must survive process restarts.
    return int.from_bytes(hashlib.blake2b(f'zuuvi-import:{namespace}:{identity}'.encode(), digest_size=8).digest(), 'big', signed=True)


def counts(job):
    result = {status: 0 for status in ImportRow.Status.values}
    result.update({item['status']: item['n'] for item in job.rows.values('status').annotate(n=Count('pk'))})
    result['total'] = sum(result.values())
    return result


def safe_error(exc):
    if isinstance(exc, ImportProblem):
        return exc.as_error()
    if isinstance(exc, PermissionDenied):
        return {'code': 'PERMISSION_REVOKED', 'field': '', 'message': 'Requester, approver or operator permission is unavailable. No restricted action is delegated.'}
    if isinstance(exc, (KeyboardInterrupt, SystemExit)):
        return {'code': 'INTERRUPTED', 'field': '', 'message': 'Execution was interrupted. Inspect durable receipts before explicit resume.'}
    if isinstance(exc, DatabaseError):
        return {'code': 'DATABASE_FAILURE', 'field': '', 'message': 'Database operation failed. Inspect durable receipts before resuming.'}
    return {'code': 'EXECUTION_FAILURE', 'field': '', 'message': 'The operation failed. Ask the operator to inspect this job; storage objects may be unreferenced.'}


@transaction.atomic
def create_job(*, actor, store, content, filename, job_id=None):
    actor = require_action(actor, 'create', store=store)
    job_id = uuid.UUID(str(job_id)) if job_id else uuid.uuid4()
    # Serialize retries of the same signed browser nonce before inserting it.
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_advisory_xact_lock(%s)', [lock_identifier('submission', job_id)])
    existing = ImportJob.objects.filter(pk=job_id).first()
    if existing:
        if existing.created_by_id != actor.pk or existing.store_id != store.pk or existing.csv_sha256 != digest(content):
            raise ImportProblem('SUBMISSION_CONFLICT', 'This submission identifier is already bound to different input.')
        return existing
    if len(content) > 5 * 1024 * 1024:
        raise ImportProblem('CSV_SIZE', 'CSV must be no larger than 5 MiB.')
    job = ImportJob.objects.create(id=job_id, store=store, created_by=actor, csv_bytes=content,
                                  csv_sha256=digest(content), original_filename=Path(filename.replace('\\', '/')).name[:255])
    try:
        rows = parse_csv(content, store)
    except ImportProblem as exc:
        job.status = 'INVALID'
        job.last_error_code, job.last_error_detail = exc.code, exc.as_error()
        job.save()
        return job
    invalid = False
    for values in rows:
        try:
            require_capabilities(actor, store, values['payload']['raw'])
        except PermissionDenied as exc:
            values['errors'].append(safe_error(exc))
            values['external_sku'] = None
        status = 'INVALID' if values['errors'] else 'READY'
        invalid |= status == 'INVALID'
        ImportRow.objects.create(job=job, status=status, **values)
    if invalid:
        job.status = 'INVALID'
        job.last_error_code = 'CSV_VALIDATION'
        job.last_error_detail = {'message': 'Correct the reported CSV errors and upload a new job.'}
        job.save()
    return job


class Lease:
    def __init__(self, job, token, raw_connection):
        self.job, self.token, self.raw = job, token, raw_connection
        self.finished = False

    def check_session(self):
        if connection.connection is not self.raw or self.raw.closed:
            raise ImportProblem('LOCK_SESSION_LOST', 'The database lock session was lost. This process must stop; use a new supervised resume.')
        # Use the captured connection directly: never reconnect implicitly.
        try:
            with self.raw.cursor() as cursor:
                cursor.execute('SELECT 1')
        except Exception:
            raise ImportProblem('LOCK_SESSION_LOST', 'The database lock session was lost. This process must stop; use a new supervised resume.')

    def locked_job(self):
        self.check_session()
        job = ImportJob.objects.select_for_update(of=('self',)).select_related('store', 'created_by', 'approved_by').get(pk=self.job.pk)
        if job.lease_token != self.token:
            raise ImportProblem('LEASE_LOST', 'A newer operator lease owns this job. This process must stop.')
        return job

    def finish(self, status, **fields):
        self.check_session()
        with transaction.atomic():
            self.locked_job()
            ImportJob.objects.filter(pk=self.job.pk, lease_token=self.token).update(
                status=status, lease_token=None, lease_expires_at=None, heartbeat_at=timezone.now(), updated_at=timezone.now(), **fields)
        self.finished = True


@contextmanager
def operator_lease(job_id, actor, *, prepare=False, resume=False, reclaim_stale=False):
    connection.ensure_connection()
    raw = connection.connection
    key = lock_identifier('job', job_id)
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_try_advisory_lock(%s)', [key])
        if not cursor.fetchone()[0]:
            raise ImportProblem('OPERATOR_BUSY', 'Another operator holds this job lock. Nothing was started.')
    lease = None
    original_connect = connection.connect

    def reject_reconnect():
        raise ImportProblem('LOCK_SESSION_LOST', 'The database lock session was lost. Stop and use a new supervised resume.')

    # Django may reconnect while restoring autocommit after a failed rollback.
    # This DatabaseWrapper is thread-local: fence that path for the whole lease.
    connection.connect = reject_reconnect
    try:
        with transaction.atomic():
            job = ImportJob.objects.select_for_update(of=('self',)).select_related('store', 'created_by', 'approved_by').get(pk=job_id)
            actor = require_action(actor, 'execute', store=job.store, job=job)
            now = timezone.now()
            if job.lease_token and (not reclaim_stale or job.lease_expires_at > now):
                raise ImportProblem('LEASE_BUSY', 'An existing lease must expire and be explicitly reclaimed.')
            if prepare:
                if job.status not in ('UPLOADED', 'INVALID', 'PREPARING') or job.approved_at:
                    raise ImportProblem('INPUT_FROZEN', 'Prepared/approved input cannot be replaced. Create a new job.')
                target = 'PREPARING'
            else:
                valid = job.status == 'AWAITING_OPERATOR' or (resume and job.status in ('PAUSED', 'COMPLETED_WITH_ERRORS', 'RUNNING'))
                if not valid or not job.approved_at:
                    raise ImportProblem('NOT_APPROVED', 'Execution requires approved input; paused/failed jobs require explicit resume.')
                target = 'RUNNING'
            token = uuid.uuid4()
            fields = dict(status=target, operator=actor, lease_token=token, lease_expires_at=now + timedelta(seconds=LEASE_SECONDS), heartbeat_at=now, updated_at=now)
            if not prepare and not job.started_at:
                fields['started_at'] = now
            ImportJob.objects.filter(pk=job.pk).update(**fields)
            job.refresh_from_db()
            lease = Lease(job, token, raw)
        yield lease
    except BaseException as exc:
        if lease and not lease.finished and connection.connection is raw and not raw.closed:
            try:
                error = safe_error(exc)
                lease.finish('INVALID' if prepare else 'PAUSED', last_error_code=error['code'], last_error_detail=error)
            except Exception:
                # A lost DB session leaves its durable lease/RUNNING row unresolved.
                pass
        raise
    finally:
        if connection.connection is raw and not raw.closed:
            try:
                with raw.cursor() as cursor:
                    cursor.execute('SELECT pg_advisory_unlock(%s)', [key])
            except Exception:
                pass
        connection.connect = original_connect


def row_hash(job, data):
    return fingerprint({'version': job.template_version, 'store': job.store_id, 'data': data})


def prior_receipt(job, row, *, lock=False):
    # Source identity survives an authorized edit of Product.sku.
    receipts = list(ImportRow.objects.filter(job__store_id=job.store_id, external_sku=row.external_sku,
                                            status='SUCCEEDED').select_related('product')[:2])
    if len(receipts) > 1:
        raise ImportProblem('PROVENANCE_CONFLICT', 'Multiple source receipts exist; operator review is required.', 'external_sku')
    current = Product.objects.filter(store_id=job.store_id, sku=row.external_sku).first()
    if not receipts:
        if current:
            raise ImportProblem('SKU_CONFLICT', 'This SKU already belongs to a product without matching import provenance.', 'external_sku')
        return None
    receipt = receipts[0]
    product = Product.objects.select_for_update().get(pk=receipt.product_id) if lock else receipt.product
    if product.store_id != job.store_id or receipt.row_fingerprint != row.row_fingerprint or (current and current.pk != product.pk):
        raise ImportProblem('PROVENANCE_CONFLICT', 'Source identity, ownership or approved intent conflicts with an existing product.', 'external_sku')
    return receipt


def snapshot(job):
    if digest(bytes(job.csv_bytes)) != job.csv_sha256 or job.template_version != VERSION:
        raise ImportProblem('INPUT_CHANGED', 'CSV bytes or template version changed.')
    parsed = parse_csv(bytes(job.csv_bytes), job.store)
    rows = list(job.rows.all())
    if len(parsed) != len(rows):
        raise ImportProblem('INPUT_CHANGED', 'The prepared row set changed.')
    hashes = []
    for saved, original in zip(rows, parsed):
        if original['errors'] or saved.payload['raw'] != original['payload']['raw'] or saved.row_number != original['row_number']:
            raise ImportProblem('INPUT_CHANGED', 'CSV row content or references changed; create a new job.')
        data = bind_images(original['payload']['data'], job.image_manifest)
        expected = row_hash(job, data)
        if expected != saved.row_fingerprint or saved.payload['data'] != data:
            raise ImportProblem('INPUT_CHANGED', 'A prepared row or taxonomy reference changed; create a new job.')
        hashes.append([saved.row_number, expected])
    return {'version': VERSION, 'creator': job.created_by_id, 'store': job.store_id, 'store_code': job.store.store_code,
            'csv_sha256': job.csv_sha256, 'manifest_hash': fingerprint(job.image_manifest), 'rows': hashes}


def prepare_job(*, job_id, actor, image_dir, reclaim_stale=False):
    with operator_lease(job_id, actor, prepare=True, reclaim_stale=reclaim_stale) as lease:
        job = lease.job
        require_participants(job, actor)
        rows = parse_csv(bytes(job.csv_bytes), job.store)
        if digest(bytes(job.csv_bytes)) != job.csv_sha256 or any(row['errors'] for row in rows):
            raise ImportProblem('CSV_VALIDATION', 'Correct CSV errors in a new job before image preparation.')
        for row in rows:
            require_participants(job, actor, raw=row['payload']['raw'])
        if not job.image_bundle_key:
            ImportJob.objects.filter(pk=job.pk).update(image_bundle_key=uuid.uuid4())
            job.refresh_from_db()
        filenames = [image['filename'] for row in rows for image in row['payload']['data']['images']]
        manifest = prepare_bundle(job, image_dir, filenames)
        lease.check_session()
        with transaction.atomic():
            job = lease.locked_job()
            ImportJob.objects.filter(pk=job.pk).update(image_manifest=manifest)
            job.image_manifest = manifest
            invalid = False
            for values in rows:
                record = job.rows.get(row_number=values['row_number'])
                data, errors = values['payload']['data'], []
                try:
                    data = bind_images(data, manifest)
                    record.external_sku = values['external_sku']
                    record.row_fingerprint = row_hash(job, data)
                    receipt = prior_receipt(job, record)
                    result = {'planned': 'already_imported' if receipt else 'create', 'missing_photo': not data['images']}
                except ImportProblem as exc:
                    errors, result = [exc.as_error()], {}
                record.payload = {'raw': values['payload']['raw'], 'data': data}
                record.errors, record.result = errors, result
                record.status = 'INVALID' if errors else 'READY'
                if errors:
                    record.external_sku = None
                record.save()
                invalid |= bool(errors)
            if invalid:
                lease.finish('INVALID', last_error_code='ROW_VALIDATION', last_error_detail={'message': 'Review row errors; corrected input requires a new job.'})
                return ImportJob.objects.get(pk=job.pk)
            prepared = snapshot(job)
            job_fingerprint = fingerprint(prepared)
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_advisory_xact_lock(%s)', [lock_identifier('fingerprint', job_fingerprint)])
            canonical = ImportJob.objects.filter(fingerprint=job_fingerprint).exclude(pk=job.pk).first()
            if canonical:
                lease.finish('DUPLICATE', duplicate_of=canonical, last_error_code='', last_error_detail={})
            else:
                lease.finish('READY', fingerprint=job_fingerprint, last_error_code='', last_error_detail={})
        return ImportJob.objects.get(pk=job.pk)


@transaction.atomic
def approve_job(*, job_id, actor, expected_hash):
    job = ImportJob.objects.select_for_update(of=('self',)).select_related('store', 'created_by').get(pk=job_id)
    actor = require_action(actor, 'approve', store=job.store, job=job)
    require_action(job.created_by, 'create', store=job.store)
    if job.status != 'READY' or job.approved_at:
        raise ImportProblem('NOT_READY', 'Only a fully prepared, unapproved preview may be approved.')
    prepared = snapshot(job)
    if fingerprint(prepared) != expected_hash or job.fingerprint != expected_hash:
        raise ImportProblem('STALE_PREVIEW', 'This preview changed. Review the current validated input before approval.')
    verify_bundle(job)
    for row in job.rows.all():
        require_capabilities(job.created_by, job.store, row.payload['raw'])
        require_capabilities(actor, job.store, row.payload['raw'])
    ImportJob.objects.filter(pk=job.pk).update(approved_by=actor, approved_at=timezone.now(), approved_snapshot=prepared,
                                              approval_hash=fingerprint(prepared), status='AWAITING_OPERATOR', updated_at=timezone.now())
    return ImportJob.objects.get(pk=job.pk)


def verified_approved(job):
    if not job.approved_at or fingerprint(job.approved_snapshot) != job.approval_hash or job.fingerprint != job.approval_hash or snapshot(job) != job.approved_snapshot:
        raise ImportProblem('INPUT_CHANGED', 'Approved input or approval hash changed. No execution is allowed.')
    verify_bundle(job)


def _write_product(job, row, actor, data, content):
    fields = {k: data[k] for k in ('name', 'description', 'unit')}
    fields.update(sku=row.external_sku, category_id=data['category']['id'], brand_id=data['brand']['id'] if data['brand'] else None)
    fields.update({k: Decimal(data[k]) for k in ('unit_value', 'store_price', 'low_stock_threshold')})
    fields.update({k: date.fromisoformat(data[k]) if data[k] else None for k in ('manufacturing_date', 'expiry_date')})
    product = create_product(store=job.store, product_data=fields, created_by=actor, tag_ids=[t['id'] for t in data['tags']], initial_status=ProductStatus.PENDING)
    if data['price_preview'] is not None:
        apply_admin_pricing(product=product, profit_margin_type=data['profit_margin_type'], profit_margin=Decimal(data['profit_margin']),
                            discount_type=data['discount_type'], discount_value=Decimal(data['discount_value'] or '0'), changed_by=actor, reason=f'Approved import {job.pk} row {row.row_number}')
    images = mutate_product_images(mutations={product.pk: {'add': [
        {'image': ContentFile(value, name=image['filename']), 'sort_order': i, 'is_primary': data['primary_image_index'] == i + 1}
        for i, (image, value) in enumerate(zip(data['images'], content))]}}, changed_by=actor)[product.pk]
    opening = None
    if data['opening_stock'] is not None:
        opening = record_opening_stock(product=product, store=job.store, quantity=Decimal(data['opening_stock']), actor=actor,
                                       reason=data['opening_stock_reason'], reference=f'import:{job.pk}:{row.row_number}')
    return product, {'product_code': product.product_code, 'image_ids': [image.pk for image in images], 'opening_transaction_id': opening.pk if opening else None}


def execute_job(*, job_id, actor, resume=False, reclaim_stale=False, progress=None):
    initial = ImportJob.objects.select_related('store').get(pk=job_id)
    require_action(actor, 'execute', store=initial.store, job=initial)
    if initial.status == 'COMPLETED':
        return initial
    with operator_lease(job_id, actor, resume=resume, reclaim_stale=reclaim_stale) as lease:
        job = lease.job
        require_participants(job, actor)
        verified_approved(job)
        ids = list(job.rows.exclude(status__in=TERMINAL).values_list('pk', flat=True))
        for pk in ids:
            lease.check_session()
            row = ImportRow.objects.get(pk=pk)
            raw = row.payload['raw']
            require_participants(job, actor, raw=raw)
            # Re-resolve current reference identity; use only approved values/bytes.
            store = Store.objects.get(pk=job.store_id)
            data = bind_images(normalize(raw, store, reference_catalogue()), job.image_manifest)
            if row_hash(job, data) != row.row_fingerprint:
                raise ImportProblem('INPUT_CHANGED', 'Row intent or a referenced category/brand/tag changed after approval.')
            content = [read_bundle_image(job, image['filename']) for image in data['images']]
            with transaction.atomic():
                lease.locked_job()
                ImportRow.objects.filter(pk=pk).update(status='RUNNING', attempts=F('attempts') + 1, executed_by=actor,
                                                       last_attempt_at=timezone.now(), completed_at=None, errors=[], result={'orphan_objects_possible': row.status == 'RUNNING'})
            try:
                with transaction.atomic():
                    current_job = lease.locked_job()
                    if current_job.approval_hash != job.approval_hash or fingerprint(current_job.approved_snapshot) != job.approval_hash:
                        raise ImportProblem('INPUT_CHANGED', 'The approved envelope changed during execution.')
                    row = ImportRow.objects.select_for_update().get(pk=pk)
                    if row.payload['data'] != data or row_hash(job, row.payload['data']) != row.row_fingerprint:
                        raise ImportProblem('INPUT_CHANGED', 'The prepared row changed during execution.')
                    require_participants(current_job, actor, raw=raw)
                    with connection.cursor() as cursor:
                        cursor.execute('SELECT pg_advisory_xact_lock(%s)', [lock_identifier('source', f'{job.store_id}:{row.external_sku}')])
                    receipt = prior_receipt(job, row, lock=True)
                    if receipt:
                        product, result, status = receipt.product, {'product_code': receipt.product.product_code, 'source_receipt': receipt.pk}, 'ALREADY_IMPORTED'
                    else:
                        product, result = _write_product(job, row, actor, data, content)
                        status = 'SUCCEEDED'
                    if content and row.attempts > 1:
                        result['orphan_objects_possible'] = True
                    require_participants(current_job, actor, raw=raw)
                    lease.check_session()
                    ImportRow.objects.filter(pk=pk).update(status=status, product=product, result=result, errors=[], completed_at=timezone.now())
                    ImportJob.objects.filter(pk=job.pk, lease_token=lease.token).update(heartbeat_at=timezone.now(), lease_expires_at=timezone.now() + timedelta(seconds=LEASE_SECONDS), updated_at=timezone.now())
            except (Exception,) as exc:
                # The failed atomic block is already rolled back here.
                lease.check_session()
                error = safe_error(exc)
                with transaction.atomic():
                    lease.locked_job()
                    row = ImportRow.objects.select_for_update().get(pk=pk)
                    if row.status in TERMINAL:
                        raise ImportProblem('RECEIPT_CONFLICT', 'Unexpected committed receipt; stop for operator review.')
                    # A non-importing writer may have won Product's unique SKU race.
                    if isinstance(exc, IntegrityError) and getattr(getattr(exc.__cause__, 'diag', None), 'constraint_name', None) == 'unique_sku_per_store':
                        try:
                            with transaction.atomic():
                                with connection.cursor() as cursor:
                                    cursor.execute('SELECT pg_advisory_xact_lock(%s)', [lock_identifier('source', f'{job.store_id}:{row.external_sku}')])
                                receipt = prior_receipt(job, row, lock=True)
                                if receipt:
                                    require_participants(job, actor, raw=raw)
                                    ImportRow.objects.filter(pk=pk).update(status='ALREADY_IMPORTED', product=receipt.product,
                                        result={'source_receipt': receipt.pk, 'product_code': receipt.product.product_code, 'orphan_objects_possible': bool(content)}, completed_at=timezone.now())
                                    continue
                        except ImportProblem as conflict:
                            error = conflict.as_error()
                    ImportRow.objects.filter(pk=pk).update(status='FAILED', errors=[error], result={'orphan_objects_possible': bool(content)}, completed_at=timezone.now())
                if not isinstance(exc, (ImportProblem, ValidationError, IntegrityError)) or error['code'] in ('INPUT_CHANGED', 'PERMISSION_REVOKED', 'LOCK_SESSION_LOST', 'LEASE_LOST'):
                    raise ImportProblem(error['code'], error['message'])
            if progress:
                progress({'row': row.row_number, 'counts': counts(job)})
        failed = job.rows.filter(status='FAILED').exists()
        lease.finish('COMPLETED_WITH_ERRORS' if failed else 'COMPLETED', finished_at=timezone.now(), last_error_code='', last_error_detail={})
    return ImportJob.objects.get(pk=job_id)
