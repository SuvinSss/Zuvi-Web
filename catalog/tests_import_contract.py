import csv
import io
import tempfile
from pathlib import Path
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings
from PIL import Image
from accounts.models import Role
from catalog.tests_public import PublicCatalogueTestMixin
from .import_contract import HEADERS, ImportProblem, parse_csv, safe_cell, csv_text
from .import_services import create_job, prepare_job, approve_job


class ImportTestMixin(PublicCatalogueTestMixin):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory(prefix='catalog-import-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve() / 'private'
        self.root.mkdir(mode=0o700)
        self.incoming = self.root / 'incoming' / 'delivery'
        self.incoming.mkdir(parents=True)
        self.media = Path(self.tmp.name) / 'media'
        self.override = override_settings(CATALOG_IMPORT_ROOT=str(self.root), MEDIA_ROOT=str(self.media), STORAGES={'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'}, 'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.store = self.create_store()
        self.category = self.create_product_category('Synthetic import category')
        self.admin = get_user_model().objects.create_user(username='import_super', email='super@example.invalid', password='Synthetic-Test-Only!', role=Role.SUPER_ADMIN, is_staff=True, is_superuser=True)
        Image.new('RGB', (12, 12), 'blue').save(self.incoming / 'front.png')
        Image.new('RGB', (12, 12), 'red').save(self.incoming / 'back.png')

    def raw(self, **overrides):
        row = dict.fromkeys(HEADERS, '')
        row.update(store_code=self.store.store_code, external_sku='SOURCE-001', name='Synthetic product', category_path=self.category.name, unit='PIECE', unit_value='1', store_price='10.00')
        row.update(overrides)
        return row

    def csv(self, rows=None):
        stream = io.StringIO(newline='')
        writer = csv.DictWriter(stream, fieldnames=HEADERS, lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows or [self.raw()])
        return stream.getvalue().encode()

    def job(self, rows=None, actor=None, ready=False, approved=False):
        actor = actor or self.admin
        job = create_job(actor=actor, store=self.store, content=self.csv(rows), filename='synthetic.csv')
        if ready or approved:
            job = prepare_job(job_id=job.pk, actor=self.admin, image_dir=self.incoming)
        if approved:
            job = approve_job(job_id=job.pk, actor=self.admin, expected_hash=job.fingerprint)
        return job

    def grant(self, user, *names):
        for name in names:
            app, codename = name.split('.')
            user.user_permissions.add(Permission.objects.get(content_type__app_label=app, codename=codename))


class ImportContractTests(ImportTestMixin, TestCase):
    def test_required_values_and_blank_stock(self):
        parsed = parse_csv(self.csv(), self.store)[0]
        self.assertEqual(parsed['errors'], [])
        self.assertIsNone(parsed['payload']['data']['opening_stock'])
        for field in ('store_code', 'external_sku', 'name', 'category_path', 'unit', 'unit_value', 'store_price'):
            with self.subTest(field=field):
                self.assertEqual(parse_csv(self.csv([self.raw(**{field: ''})]), self.store)[0]['errors'][0]['code'], 'REQUIRED')

    def test_exact_headers_utf8_and_bom(self):
        self.assertFalse(parse_csv(b'\xef\xbb\xbf' + self.csv(), self.store)[0]['errors'])
        for value in (b'no,headers\n', b'\xff', self.csv().replace(b'store_code', b'name', 1), self.csv().replace(b'Synthetic product', b'\x00')):
            with self.subTest(value=value[:20]), self.assertRaises(ImportProblem):
                parse_csv(value, self.store)

    def test_decimal_contract(self):
        for value in ('NaN', 'Infinity', '-1', '1e2', '1,000', '1.001', '10000000000'):
            with self.subTest(value=value):
                self.assertEqual(parse_csv(self.csv([self.raw(store_price=value)]), self.store)[0]['errors'][0]['code'], 'DECIMAL')
        self.assertEqual(parse_csv(self.csv([self.raw(store_price='0')]), self.store)[0]['payload']['data']['store_price'], '0.00')

    def test_duplicate_source_rows_all_invalid(self):
        rows = parse_csv(self.csv([self.raw(), self.raw()]), self.store)
        self.assertTrue(all(r['external_sku'] is None and r['errors'][0]['code'] == 'DUPLICATE_SKU' for r in rows))

    def test_rows_limit(self):
        with self.assertRaisesMessage(ImportProblem, '1,000'):
            parse_csv(self.csv([self.raw(external_sku=str(i)) for i in range(1001)]), self.store)

    def test_references_store_dates_and_units(self):
        for values, code in [({'category_path': 'unknown'}, 'CATEGORY'), ({'store_code': 'wrong'}, 'STORE_MISMATCH'), ({'brand_slug': 'unknown'}, 'BRAND'), ({'tag_slugs': 'x|x'}, 'TAGS'), ({'unit': 'BAG'}, 'UNIT'), ({'manufacturing_date': '2026-01-02', 'expiry_date': '2026-01-01'}, 'DATE_ORDER')]:
            with self.subTest(values=values):
                self.assertEqual(parse_csv(self.csv([self.raw(**values)]), self.store)[0]['errors'][0]['code'], code)

    def test_images_and_opening_pairs(self):
        for values in ({'image_2': 'front.png'}, {'image_1': '../front.png'}, {'primary_image_index': '1'}, {'opening_stock': '0', 'opening_stock_reason': 'test'}, {'opening_stock': '2'}):
            with self.subTest(values=values):
                self.assertTrue(parse_csv(self.csv([self.raw(**values)]), self.store)[0]['errors'])

    def test_server_price_calculation(self):
        data = parse_csv(self.csv([self.raw(profit_margin_type='FIXED', profit_margin='2', discount_type='PERCENTAGE', discount_value='10')]), self.store)[0]['payload']['data']
        self.assertEqual(data['price_preview'], {'selling_price': '12.00', 'final_price': '10.80'})

    def test_formula_safe_reports(self):
        for value in ('=SUM(1)', ' +123', '-123', '@cmd', 'x\ty', 'x\ny'):
            self.assertTrue(safe_cell(value).startswith("'"))
        self.assertEqual(list(csv.reader(io.StringIO(csv_text([['=1', 'a,b']]))))[0], ["'=1", 'a,b'])

    def test_sample_has_no_stock(self):
        from django.conf import settings
        rows = list(csv.DictReader((Path(settings.BASE_DIR) / 'docs/catalog-import-sample-v1.csv').open()))
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(not r['opening_stock'] and not r['opening_stock_reason'] for r in rows))
