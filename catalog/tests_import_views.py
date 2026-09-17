from django.contrib.auth import get_user_model
from django.core import signing
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse
from accounts.models import Role
from stores.models import StoreUser
from .tests_import_contract import ImportTestMixin
from .models import ImportJob


class ImportViewTests(ImportTestMixin, TestCase):
    def test_template_sample_and_instructions_protected(self):
        url = reverse('catalog:import_download', args=['template'])
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.admin)
        for kind in ('template', 'sample', 'instructions'):
            response = self.client.get(reverse('catalog:import_download', args=[kind]))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response['Cache-Control'], 'private, no-store')

    def test_upload_preview_and_signed_duplicate_post(self):
        self.client.force_login(self.admin)
        url = reverse('catalog:import_create')
        response = self.client.get(url)
        nonce = response.context['form']['nonce'].value()
        def post():
            return self.client.post(url, {'store': self.store.pk, 'nonce': nonce, 'csv_file': SimpleUploadedFile('products.csv', self.csv())})
        first, second = post(), post()
        self.assertEqual(first.status_code, 302)
        self.assertEqual(first.url, second.url)
        self.assertEqual(ImportJob.objects.count(), 1)
        self.assertContains(self.client.get(first.url), 'Awaiting operator')

    def test_approval_csrf_and_post_only(self):
        job = self.job(ready=True)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        url = reverse('catalog:import_approve', args=[job.pk])
        self.assertEqual(client.get(url).status_code, 405)
        self.assertEqual(client.post(url, {'expected_hash': job.fingerprint, 'acknowledge': 'on'}).status_code, 403)
        client.get(reverse('catalog:import_detail', args=[job.pk]))
        response = client.post(url, {'expected_hash': job.fingerprint, 'acknowledge': 'on', 'csrfmiddlewaretoken': client.cookies['csrftoken'].value})
        self.assertEqual(response.status_code, 302)
        job.refresh_from_db()
        self.assertEqual(job.status, 'AWAITING_OPERATOR')

    def test_preview_pagination_and_escaped_html(self):
        job = self.job([self.raw(external_sku=str(i), name='<script>alert(1)</script>') for i in range(51)])
        self.client.force_login(self.admin)
        response = self.client.get(reverse('catalog:import_detail', args=[job.pk]))
        self.assertEqual(len(response.context['page']), 50)
        self.assertNotContains(response, '<script>alert(1)</script>')
        self.assertContains(response, '&lt;script&gt;')
        self.assertEqual(len(self.client.get(reverse('catalog:import_detail', args=[job.pk]) + '?page=2').context['page']), 1)

    def test_private_image_owner_isolation(self):
        job = self.job([self.raw(image_1='front.png')], ready=True)
        user = get_user_model().objects.create_user(username='merchant', email='merchant@example.invalid', role=Role.STORE_USER)
        StoreUser.objects.create(user=user, store=self.store, is_active=True)
        self.grant(user, 'catalog.view_importjob')
        self.client.force_login(user)
        for name, args in [('detail', [job.pk]), ('report', [job.pk]), ('image', [job.pk, 1, 1])]:
            self.assertEqual(self.client.get(reverse('catalog:store_import_' + name, args=args)).status_code, 404)
        self.client.force_login(self.admin)
        response = self.client.get(reverse('catalog:import_image', args=[job.pk, 1, 1]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')

    def test_management_pricing_redacted_without_permission(self):
        job = self.job([self.raw(profit_margin_type='FIXED', profit_margin='7.31')], ready=True)
        user = get_user_model().objects.create_user(username='viewer', email='viewer@example.invalid', role=Role.ADMIN, is_staff=True)
        self.grant(user, 'catalog.view_importjob', 'catalog.view_product')
        self.client.force_login(user)
        response = self.client.get(reverse('catalog:import_detail', args=[job.pk]))
        self.assertNotContains(response, '7.31')
        self.assertNotContains(response, 'profit_margin')
        report = self.client.get(reverse('catalog:import_report', args=[job.pk]))
        self.assertNotIn(b'7.31', report.content)
        from .import_services import approve_job, execute_job
        approve_job(job_id=job.pk, actor=self.admin, expected_hash=job.fingerprint)
        execute_job(job_id=job.pk, actor=self.admin)
        repeat = self.job([self.raw(external_sku=' SOURCE-001 ', profit_margin_type='FIXED', profit_margin='7.31')], ready=True)
        self.assertContains(self.client.get(reverse('catalog:import_detail', args=[repeat.pk])), 'Matching original import receipt found.')

    def test_missing_staging_has_honest_state(self):
        from django.test import override_settings
        self.client.force_login(self.admin)
        with override_settings(CATALOG_IMPORT_ROOT=''):
            self.assertContains(self.client.get(reverse('catalog:import_create')), 'Private staging unavailable')
