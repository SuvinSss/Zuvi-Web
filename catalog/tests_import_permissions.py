from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.test import TestCase
from accounts.models import Role
from stores.models import StoreUser
from .tests_import_contract import ImportTestMixin
from .import_permissions import require_action, visible_jobs
from .import_services import execute_job
from .models import Product


class ImportPermissionTests(ImportTestMixin, TestCase):
    def merchant(self, username='merchant'):
        user = get_user_model().objects.create_user(username=username, email=username + '@example.invalid', role=Role.STORE_USER)
        member = StoreUser.objects.create(user=user, store=self.store, is_active=True, can_manage_inventory=False)
        self.grant(user, 'catalog.add_importjob', 'catalog.view_importjob', 'catalog.approve_importjob', 'catalog.execute_importjob', 'catalog.manage_product_pricing')
        return user, member

    def test_merchant_cannot_approve_or_execute_even_with_grants(self):
        user, member = self.merchant()
        for action in ('approve', 'execute'):
            with self.assertRaises(PermissionDenied):
                require_action(user, action, store=self.store)
        self.assertEqual(require_action(user, 'create', store=self.store).pk, user.pk)

    def test_merchant_only_own_created_jobs(self):
        first, member = self.merchant()
        second, member2 = self.merchant('other')
        own = self.job(actor=first)
        self.job(actor=second)
        self.job()
        self.assertEqual(list(visible_jobs(first).values_list('pk', flat=True)), [own.pk])
        with self.assertRaises(PermissionDenied):
            require_action(first, 'create', store=self.create_store())

    def test_customer_and_ungranted_admin_denied(self):
        for role, staff in [(Role.CUSTOMER, False), (Role.ADMIN, True)]:
            user = get_user_model().objects.create_user(username=str(role), email=str(role) + '@example.invalid', role=role, is_staff=staff)
            for action in ('view', 'create', 'approve', 'execute'):
                with self.subTest(role=role, action=action), self.assertRaises(PermissionDenied):
                    require_action(user, action, store=self.store)

    def test_merchant_zero_pricing_and_inventory_require_capability(self):
        user, member = self.merchant()
        for raw in (self.raw(profit_margin='0'), self.raw(opening_stock='2', opening_stock_reason='Synthetic')):
            job = self.job([raw], actor=user)
            self.assertEqual(job.status, 'INVALID')
            self.assertTrue(job.rows.get().errors)

    def test_creator_revocation_pauses_before_next_row(self):
        user, member = self.merchant()
        job = self.job([self.raw(external_sku='ONE'), self.raw(external_sku='TWO')], actor=user, approved=True)
        def revoke(event):
            StoreUser.objects.filter(pk=member.pk).update(is_active=False)
        with self.assertRaises(PermissionDenied):
            execute_job(job_id=job.pk, actor=self.admin, progress=revoke)
        self.assertEqual(Product.objects.count(), 1)
        job.refresh_from_db()
        self.assertEqual(job.status, 'PAUSED')

    def test_approver_revocation_blocks_execution(self):
        job = self.job(approved=True)
        get_user_model().objects.filter(pk=self.admin.pk).update(is_active=False)
        with self.assertRaises(PermissionDenied):
            execute_job(job_id=job.pk, actor=self.admin)
        self.assertEqual(Product.objects.count(), 0)

    def test_regular_admin_execute_needs_no_upload_grant(self):
        user = get_user_model().objects.create_user(username='operator', email='operator@example.invalid', role=Role.ADMIN, is_staff=True)
        self.grant(user, 'catalog.execute_importjob', 'catalog.view_importjob', 'catalog.add_product')
        job = self.job(approved=True)
        execute_job(job_id=job.pk, actor=user)
        self.assertEqual(job.rows.get().executed_by_id, user.pk)
