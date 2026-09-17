import os
from unittest.mock import patch
from django.test import TestCase, override_settings
from .tests_import_contract import ImportTestMixin
from .import_contract import ImportProblem
from .import_files import prepare_bundle, read_bundle_image, staging_root


class ImportFileTests(ImportTestMixin, TestCase):
    def test_snapshot_ignores_later_source_change(self):
        job = self.job([self.raw(image_1='front.png')], ready=True)
        original = read_bundle_image(job, 'front.png')
        (self.incoming / 'front.png').write_bytes(b'changed source')
        self.assertEqual(read_bundle_image(job, 'front.png'), original)

    def test_changed_bundle_fails_hash(self):
        job = self.job([self.raw(image_1='front.png')], ready=True)
        meta = job.image_manifest['front.png']
        path = self.root / 'snapshots' / str(job.image_bundle_key) / (meta['sha256'] + meta['suffix'])
        path.chmod(0o600)
        path.write_bytes(b'changed')
        with self.assertRaisesMessage(ImportProblem, 'changed'):
            read_bundle_image(job, 'front.png')

    def test_private_root_is_required_even_without_images(self):
        public = self.root.parent / 'public'
        public.mkdir(mode=0o755)
        for root in ('', str(self.media), str(public)):
            with self.subTest(root=root), override_settings(CATALOG_IMPORT_ROOT=root), self.assertRaises(ImportProblem):
                staging_root()

    def test_symlink_source_rejected(self):
        (self.incoming / 'link.png').symlink_to(self.incoming / 'front.png')
        with self.assertRaises(ImportProblem):
            self.job([self.raw(image_1='front.png')], ready=True)

    def test_symlink_destination_cannot_write_outside_root(self):
        outside = self.root.parent / 'outside'
        outside.mkdir()
        (self.root / 'snapshots').symlink_to(outside)
        with self.assertRaises(ImportProblem):
            self.job([self.raw(image_1='front.png')], ready=True)
        self.assertEqual(list(outside.iterdir()), [])

    def test_case_mismatch_missing_content_and_size(self):
        for content, name in [(b'not an image', 'bad.png'), (b'x' * (5 * 1024 * 1024 + 1), 'large.png')]:
            (self.incoming / name).write_bytes(content)
            with self.subTest(name=name), self.assertRaises(ImportProblem):
                self.job([self.raw(external_sku=name, image_1=name)], ready=True)
        with self.assertRaises(ImportProblem):
            self.job([self.raw(image_1='FRONT.png')], ready=True)

    def test_identical_content_twice_in_product_invalid(self):
        (self.incoming / 'copy.png').write_bytes((self.incoming / 'front.png').read_bytes())
        job = self.job([self.raw(image_1='front.png', image_2='copy.png')], ready=True)
        self.assertEqual(job.status, 'INVALID')
        self.assertEqual(job.rows.get().errors[0]['code'], 'DUPLICATE_IMAGE')

    def test_bundle_size_bounded(self):
        with patch('catalog.import_files.MAX_BUNDLE_BYTES', 1), self.assertRaises(ImportProblem):
            self.job([self.raw(image_1='front.png')], ready=True)
