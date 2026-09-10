"""Offline storage contracts; all credentials and object URLs here are synthetic."""

import json
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, quote, urlsplit

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import Storage, default_storage
from django.test import SimpleTestCase, override_settings
from django.test.runner import DiscoverRunner

from config.test_runner import IsolatedMediaTestRunner
from config.tests_deployment import SETTINGS_PROBE, isolated_environment, run_python
from scripts.collectstatic import build_environment


class RemoteStorage(Storage):
    """Object-like fake: fresh streams on reads, no local path, no networking."""
    def __init__(self):
        self.objects = {}
        self.path_calls = 0

    def _save(self, name, content):
        self.objects[name] = b''.join(content.chunks())
        return name

    def _open(self, name, mode='rb'):
        return ContentFile(self.objects[name], name=name)

    def exists(self, name):
        return name in self.objects

    def size(self, name):
        return len(self.objects[name])

    def delete(self, name):
        del self.objects[name]

    def path(self, name):
        self.path_calls += 1
        raise NotImplementedError('Object storage has no local path.')

    def url(self, name):
        return f'https://media.example.test/{quote(name)}?signature=synthetic&expires=300'


class MediaSettingsTests(SimpleTestCase):
    def probe(self, **overrides):
        result = run_python(SETTINGS_PROBE, isolated_environment(**overrides))
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_local_filesystem_with_no_s3_configuration(self):
        env = isolated_environment(DJANGO_ENVIRONMENT='local', MEDIA_STORAGE_BACKEND='filesystem')
        for name in list(env):
            if name.startswith('MEDIA_') and name != 'MEDIA_STORAGE_BACKEND':
                del env[name]
        result = run_python(SETTINGS_PROBE, env)
        self.assertEqual(result.returncode, 0, result.stderr)
        parsed = json.loads(result.stdout)
        self.assertEqual(parsed['STORAGES']['default']['BACKEND'], 'django.core.files.storage.FileSystemStorage')
        self.assertEqual(parsed['MEDIA_URL'], '/media/')

    def test_local_rejects_s3_and_unknown_backends(self):
        for backend in ('s3', 'typo'):
            result = run_python(SETTINGS_PROBE, isolated_environment(DJANGO_ENVIRONMENT='local', MEDIA_STORAGE_BACKEND=backend))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('MEDIA_STORAGE_BACKEND=filesystem', result.stderr)

    def test_each_hosted_environment_requires_explicit_s3(self):
        for environment in ('development', 'uat', 'production'):
            for backend in (None, '', 'filesystem', 'typo'):
                with self.subTest(environment=environment, backend=backend):
                    env = isolated_environment(DJANGO_ENVIRONMENT=environment)
                    if backend is None:
                        del env['MEDIA_STORAGE_BACKEND']
                    else:
                        env['MEDIA_STORAGE_BACKEND'] = backend
                    result = run_python(SETTINGS_PROBE, env)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('explicit MEDIA_STORAGE_BACKEND=s3', result.stderr)

    def test_missing_or_blank_s3_values_fail_without_disclosing_credentials(self):
        for variable in ('MEDIA_BUCKET_NAME', 'MEDIA_REGION_NAME', 'MEDIA_ACCESS_KEY_ID', 'MEDIA_SECRET_ACCESS_KEY'):
            for value in (None, '', ' '):
                with self.subTest(variable=variable, value=value):
                    env = isolated_environment()
                    if value is None:
                        del env[variable]
                    else:
                        env[variable] = value
                    # Legacy AWS variables must not supply missing neutral values.
                    env.update(AWS_ACCESS_KEY_ID='legacy-key', AWS_SECRET_ACCESS_KEY='legacy-secret')
                    result = run_python(SETTINGS_PROBE, env)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(variable, result.stderr)
                    self.assertNotIn('legacy-secret', result.stderr)
                    self.assertNotIn('EXAMPLE_ONLY', result.stderr)

    def test_intended_region_is_required(self):
        result = run_python(SETTINGS_PROBE, isolated_environment(MEDIA_REGION_NAME='us-east-1'))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('MEDIA_REGION_NAME must be ap-south-1', result.stderr)

    def test_environment_values_are_used_without_sharing_or_rewriting(self):
        for environment in ('development', 'uat', 'production'):
            parsed = self.probe(
                DJANGO_ENVIRONMENT=environment,
                MEDIA_BUCKET_NAME=f'example-{environment}',
                MEDIA_ACCESS_KEY_ID=f'fake-{environment}-key',
                MEDIA_SECRET_ACCESS_KEY=f'fake-{environment}-secret',
            )
            media = parsed['STORAGES']['default']
            self.assertEqual(media['BACKEND'], 'storages.backends.s3.S3Storage')
            self.assertEqual(media['OPTIONS']['bucket_name'], f'example-{environment}')
            self.assertEqual(media['OPTIONS']['access_key'], f'fake-{environment}-key')
            self.assertEqual(media['OPTIONS']['secret_key'], f'fake-{environment}-secret')
            self.assertEqual(media['OPTIONS']['region_name'], 'ap-south-1')
            self.assertEqual(parsed['STORAGES']['staticfiles']['BACKEND'], 'whitenoise.storage.CompressedManifestStaticFilesStorage')

    def test_private_options_and_sdk_signing_without_http(self):
        code = """
import json
from unittest.mock import patch
from django.core.files.storage import storages
with patch('botocore.httpsession.URLLib3Session.send', side_effect=AssertionError('No HTTP')) as send:
    storage = storages['default']
    url = storage.url('products/images/example.jpg')
    print(json.dumps({
        'url': url, 'acl': storage.default_acl, 'auth': storage.querystring_auth,
        'overwrite': storage.file_overwrite, 'location': storage.location,
        'domain': storage.custom_domain, 'parameters': storage.object_parameters,
        'connect_timeout': storage.client_config.connect_timeout,
        'read_timeout': storage.client_config.read_timeout,
        'retries': storage.client_config.retries, 'http_calls': send.call_count,
    }))
"""
        result = run_python(code, isolated_environment(
            AWS_SESSION_TOKEN='ambient-token', AWS_S3_SESSION_PROFILE='ambient-profile',
            AWS_ENDPOINT_URL='https://wrong.example.test',
        ))
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        url = urlsplit(data['url'])
        query = parse_qs(url.query)
        self.assertEqual(url.scheme, 'https')
        self.assertIn('amazonaws.com', url.hostname)
        self.assertEqual(url.path, '/products/images/example.jpg')
        self.assertEqual(query['X-Amz-Expires'], ['300'])
        self.assertEqual(query['X-Amz-Algorithm'], ['AWS4-HMAC-SHA256'])
        self.assertIn('/ap-south-1/s3/aws4_request', query['X-Amz-Credential'][0])
        self.assertIn('X-Amz-Signature', query)
        self.assertNotIn('X-Amz-Security-Token', query)
        self.assertIsNone(data['acl'])
        self.assertTrue(data['auth'])
        self.assertFalse(data['overwrite'])
        self.assertEqual(data['location'], '')
        self.assertIsNone(data['domain'])
        self.assertEqual(data['parameters'], {'CacheControl': 'private, no-store'})
        self.assertEqual(data['connect_timeout'], 3)
        self.assertEqual(data['read_timeout'], 5)
        self.assertEqual(data['retries']['total_max_attempts'], 2)
        self.assertEqual(data['http_calls'], 0)

    def test_static_build_ignores_media_configuration_and_credentials(self):
        env = build_environment('/tmp/unused-static-destination')
        env['MEDIA_STORAGE_BACKEND'] = 's3'
        result = run_python(SETTINGS_PROBE, env, '--static-build')
        self.assertEqual(result.returncode, 0, result.stderr)
        parsed = json.loads(result.stdout)
        self.assertEqual(parsed['engine'], 'django.db.backends.dummy')
        self.assertEqual(parsed['STORAGES']['default']['BACKEND'], 'django.core.files.storage.FileSystemStorage')
        self.assertEqual(parsed['STORAGES']['staticfiles']['BACKEND'], 'whitenoise.storage.CompressedManifestStaticFilesStorage')

    def test_manage_test_ignores_ambient_s3_without_credentials(self):
        env = isolated_environment()
        for variable in ('MEDIA_BUCKET_NAME', 'MEDIA_REGION_NAME', 'MEDIA_ACCESS_KEY_ID', 'MEDIA_SECRET_ACCESS_KEY'):
            del env[variable]
        result = run_python("import sys; sys.argv=['manage.py', 'test'];\n" + SETTINGS_PROBE, env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['STORAGES']['default']['BACKEND'], 'django.core.files.storage.FileSystemStorage')


class MediaTestIsolationTests(SimpleTestCase):
    def test_runner_is_configured(self):
        self.assertEqual(settings.TEST_RUNNER, 'config.test_runner.IsolatedMediaTestRunner')

    def test_runner_isolates_discovery_and_cleans_up_even_on_failure(self):
        for fail in (False, True):
            observed = []

            def exercise(runner, labels, **kwargs):
                from botocore.httpsession import URLLib3Session
                observed.append(Path(settings.MEDIA_ROOT))
                self.assertEqual(settings.STORAGES['default']['BACKEND'], 'django.core.files.storage.FileSystemStorage')
                default_storage.save('probe.txt', ContentFile(b'isolated'))
                self.assertTrue((observed[0] / 'probe.txt').is_file())
                with self.assertRaisesRegex(AssertionError, 'AWS HTTP requests are forbidden'):
                    URLLib3Session().send(None)
                if fail:
                    raise RuntimeError('synthetic runner failure')
                return 0

            ambient = {**settings.STORAGES, 'default': {'BACKEND': 'storages.backends.s3.S3Storage'}}
            original_root = settings.MEDIA_ROOT
            with override_settings(STORAGES=ambient), patch.object(DiscoverRunner, 'run_tests', exercise):
                runner = IsolatedMediaTestRunner(verbosity=0)
                if fail:
                    with self.assertRaisesRegex(RuntimeError, 'synthetic runner failure'):
                        runner.run_tests([])
                else:
                    self.assertEqual(runner.run_tests([]), 0)
                self.assertEqual(settings.STORAGES, ambient)
                self.assertEqual(settings.MEDIA_ROOT, original_root)
            self.assertFalse(observed[0].exists())
