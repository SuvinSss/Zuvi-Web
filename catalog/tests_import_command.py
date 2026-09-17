import io
import threading
from datetime import timedelta
from unittest.mock import patch
from django.db import connection, connections, transaction
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TransactionTestCase
from django.utils import timezone
from .tests_import_contract import ImportTestMixin
from .import_contract import ImportProblem
from .import_services import execute_job, operator_lease, lock_identifier, LEASE_SECONDS
from .models import ImportJob, Product


class ImportCommandTests(ImportTestMixin, TransactionTestCase):
    def test_command_prepare_execute_status_and_repeat(self):
        job = self.job()
        out = io.StringIO()
        call_command('catalog_import', 'prepare', job=str(job.pk), actor=self.admin.username, image_dir=str(self.incoming), stdout=out)
        from .import_services import approve_job
        job.refresh_from_db()
        approve_job(job_id=job.pk, actor=self.admin, expected_hash=job.fingerprint)
        call_command('catalog_import', 'execute', job=str(job.pk), actor=self.admin.username, stdout=out)
        call_command('catalog_import', 'status', job=str(job.pk), actor=self.admin.username, stdout=out)
        self.assertIn('COMPLETED', out.getvalue())
        self.assertEqual(Product.objects.count(), 1)
        with self.assertRaises(CommandError):
            call_command('catalog_import', 'status', job='not-a-uuid', actor=self.admin.username)

    def test_no_replacement_inputs_during_execution(self):
        job = self.job(approved=True)
        with self.assertRaises(CommandError):
            call_command('catalog_import', 'execute', job=str(job.pk), actor=self.admin.username, image_dir=str(self.incoming))

    def test_interrupt_before_commit_and_resume(self):
        job = self.job(approved=True)
        from .import_services import _write_product
        def interrupted(*args, **kwargs):
            _write_product(*args, **kwargs)
            raise KeyboardInterrupt
        with patch('catalog.import_services._write_product', side_effect=interrupted), self.assertRaises(KeyboardInterrupt):
            execute_job(job_id=job.pk, actor=self.admin)
        self.assertEqual(Product.objects.count(), 0)
        self.assertEqual(job.rows.get().status, 'RUNNING')
        execute_job(job_id=job.pk, actor=self.admin, resume=True)
        self.assertEqual(Product.objects.count(), 1)
        self.assertEqual(job.rows.get().attempts, 2)

    def test_interrupt_after_commit_resume_skips_receipt(self):
        job = self.job([self.raw(external_sku='ONE'), self.raw(external_sku='TWO')], approved=True)
        def interrupted(event):
            raise KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            execute_job(job_id=job.pk, actor=self.admin, progress=interrupted)
        self.assertEqual(Product.objects.count(), 1)
        execute_job(job_id=job.pk, actor=self.admin, resume=True)
        self.assertEqual(Product.objects.count(), 2)
        self.assertEqual(list(job.rows.values_list('attempts', flat=True)), [1, 1])

    def test_competing_operator_refused_by_session_lock(self):
        job = self.job(approved=True)
        results = []
        with operator_lease(job.pk, self.admin):
            def contender():
                try:
                    execute_job(job_id=job.pk, actor=self.admin)
                except ImportProblem as exc:
                    results.append(exc.code)
                finally:
                    connections['default'].close()
            thread = threading.Thread(target=contender)
            thread.start()
            thread.join(10)
            self.assertFalse(thread.is_alive())
        self.assertEqual(results, ['OPERATOR_BUSY'])
        self.assertEqual(Product.objects.count(), 0)

    def test_stale_lease_requires_expiry_and_explicit_reclaim(self):
        job = self.job(approved=True)
        with operator_lease(job.pk, self.admin) as lease:
            pass
        with self.assertRaises(ImportProblem):
            execute_job(job_id=job.pk, actor=self.admin, resume=True, reclaim_stale=True)
        ImportJob.objects.filter(pk=job.pk).update(lease_expires_at=timezone.now() - timedelta(seconds=1))
        with self.assertRaises(ImportProblem):
            execute_job(job_id=job.pk, actor=self.admin, resume=True)
        execute_job(job_id=job.pk, actor=self.admin, resume=True, reclaim_stale=True)
        self.assertEqual(Product.objects.count(), 1)

    def test_lost_session_aborts_without_reconnection(self):
        import psycopg
        from django.core.files.storage import default_storage
        job = self.job([self.raw(image_1='front.png', opening_stock='2', opening_stock_reason='Synthetic')], approved=True)
        raw = connection.connection
        params = connection.get_connection_params()
        original = default_storage.save
        def lose_session(*args, **kwargs):
            saved = original(*args, **kwargs)
            with psycopg.connect(**params, autocommit=True) as control:
                control.execute('SELECT pg_terminate_backend(%s)', [raw.info.backend_pid])
            return saved
        with patch.object(default_storage, 'save', side_effect=lose_session), self.assertRaises(ImportProblem):
            execute_job(job_id=job.pk, actor=self.admin)
        self.assertTrue(connection.connection is raw or connection.connection is None)
        self.assertTrue(raw.closed)
        connection.close()  # A separate supervised invocation may reconnect.
        self.assertEqual(Product.objects.count(), 0)
        job.refresh_from_db()
        self.assertEqual(job.status, 'RUNNING')
        self.assertEqual(job.rows.get().status, 'RUNNING')
        ImportJob.objects.filter(pk=job.pk).update(lease_expires_at=timezone.now() - timedelta(seconds=1))
        execute_job(job_id=job.pk, actor=self.admin, resume=True, reclaim_stale=True)
        self.assertEqual(Product.objects.count(), 1)
        self.assertTrue(job.rows.get().result['orphan_objects_possible'])

    def test_deterministic_lock_and_fencing_token(self):
        self.assertEqual(lock_identifier('source', '1:ABC'), lock_identifier('source', '1:ABC'))
        self.assertNotEqual(lock_identifier('source', '1:ABC'), lock_identifier('source', '2:ABC'))
        import uuid
        job = self.job(approved=True)
        with self.assertRaises(ImportProblem):
            with operator_lease(job.pk, self.admin) as lease:
                ImportJob.objects.filter(pk=job.pk).update(lease_token=uuid.uuid4())
                with transaction.atomic():
                    lease.locked_job()
        self.assertEqual(Product.objects.count(), 0)

    def test_competing_jobs_same_source_create_once(self):
        first = self.job(approved=True)
        second = self.job([self.raw(external_sku=' SOURCE-001 ')], approved=True)
        results, barrier = [], threading.Barrier(2)
        def run(job):
            try:
                barrier.wait(timeout=10)
                results.append(execute_job(job_id=job.pk, actor=self.admin).status)
            except Exception as exc:
                results.append(type(exc).__name__ + ':' + str(exc))
            finally:
                connections['default'].close()
        threads = [threading.Thread(target=run, args=[job]) for job in (first, second)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(30)
        self.assertEqual(sorted(results), ['COMPLETED', 'COMPLETED'])
        self.assertEqual(Product.objects.count(), 1)
        self.assertEqual(sorted([first.rows.get().status, second.rows.get().status]), ['ALREADY_IMPORTED', 'SUCCEEDED'])


    def abrupt_process(self, job, mode):
        # Fresh interpreter: forking psycopg/native image state is unsafe on macOS.
        import json
        import os
        import subprocess
        import sys
        config = {'db': {key: connection.settings_dict[key] for key in ('ENGINE', 'NAME', 'HOST', 'PORT', 'USER', 'PASSWORD')},
                  'root': str(self.root), 'media': str(self.media), 'job': str(job.pk), 'actor': self.admin.pk, 'mode': mode}
        script = """
import json, os, signal, sys
from unittest.mock import patch
from django.conf import settings
config = json.loads(sys.argv[1])
settings.DATABASES = {'default': config['db']}
settings.CATALOG_IMPORT_ROOT = config['root']
settings.MEDIA_ROOT = config['media']
settings.STORAGES = {'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'}, 'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}}
import django
django.setup()
from django.contrib.auth import get_user_model
from catalog.import_services import execute_job, _write_product
actor = get_user_model().objects.get(pk=config['actor'])
def killed(*args, **kwargs):
    _write_product(*args, **kwargs)
    os.kill(os.getpid(), signal.SIGKILL)
if config['mode'] == 'before':
    with patch('catalog.import_services._write_product', side_effect=killed):
        execute_job(job_id=config['job'], actor=actor)
else:
    execute_job(job_id=config['job'], actor=actor, progress=lambda event: os._exit(93))
"""
        env = dict(os.environ, PYTHONPATH=os.pathsep.join(sys.path))
        return subprocess.run([sys.executable, '-c', script, json.dumps(config)], env=env, capture_output=True, timeout=20)

    def test_process_kill_before_commit_rolls_back_and_reclaims(self):
        import signal
        job = self.job([self.raw(image_1='front.png', opening_stock='2', opening_stock_reason='Synthetic')], approved=True)
        process = self.abrupt_process(job, 'before')
        self.assertEqual(process.returncode, -signal.SIGKILL, process.stderr.decode())
        self.assertEqual(Product.objects.count(), 0)
        self.assertEqual(job.rows.get().status, 'RUNNING')
        ImportJob.objects.filter(pk=job.pk).update(lease_expires_at=timezone.now() - timedelta(seconds=1))
        execute_job(job_id=job.pk, actor=self.admin, resume=True, reclaim_stale=True)
        row = job.rows.get()
        self.assertEqual(row.status, 'SUCCEEDED')
        self.assertTrue(row.result['orphan_objects_possible'])
        self.assertEqual(Product.objects.count(), 1)
        self.assertEqual(row.product.images.count(), 1)
        from inventory.models import InventoryTransaction
        self.assertEqual(InventoryTransaction.objects.count(), 1)

    def test_process_exit_after_commit_skips_success_on_reclaim(self):
        job = self.job([self.raw(external_sku='ONE'), self.raw(external_sku='TWO')], approved=True)
        process = self.abrupt_process(job, 'after')
        self.assertEqual(process.returncode, 93, process.stderr.decode())
        self.assertEqual(Product.objects.count(), 1)
        ImportJob.objects.filter(pk=job.pk).update(lease_expires_at=timezone.now() - timedelta(seconds=1))
        execute_job(job_id=job.pk, actor=self.admin, resume=True, reclaim_stale=True)
        self.assertEqual(Product.objects.count(), 2)
        self.assertEqual(list(job.rows.values_list('attempts', flat=True)), [1, 1])
