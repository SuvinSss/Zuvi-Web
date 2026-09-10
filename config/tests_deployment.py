"""Deployment contracts tested without hosted services or production credentials."""

import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

import psycopg
from django.conf import settings
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from scripts.collectstatic import build_environment

BASE_DIR = Path(__file__).resolve().parent.parent
LOCAL_PLACEHOLDER_URL = 'postgres://unused@127.0.0.1:1/unused'
SETTINGS_PROBE = """
import json, sys
if '--static-build' in sys.argv:
    sys.argv = ['manage.py', 'collectstatic', '--noinput']
from django.conf import settings
names = [
    'DEBUG', 'ALLOWED_HOSTS', 'CSRF_TRUSTED_ORIGINS',
    'SECURE_PROXY_SSL_HEADER', 'SECURE_SSL_REDIRECT',
    'SESSION_COOKIE_SECURE', 'CSRF_COOKIE_SECURE', 'CSRF_COOKIE_HTTPONLY',
    'SECURE_HSTS_SECONDS', 'SECURE_HSTS_PRELOAD', 'SECURE_HSTS_INCLUDE_SUBDOMAINS',
    'SECURE_REDIRECT_EXEMPT', 'STORAGES', 'MIDDLEWARE', 'STATIC_ROOT',
    'MEDIA_ROOT', 'MEDIA_URL', 'LOGGING',
]
result = {name: getattr(settings, name) for name in names}
result['engine'] = settings.DATABASES['default']['ENGINE']
print(json.dumps(result, default=str))
"""


def isolated_environment(**overrides):
    env = build_environment(BASE_DIR / 'staticfiles')
    env.pop('DJANGO_STATIC_BUILD')
    env['DATABASE_URL'] = LOCAL_PLACEHOLDER_URL
    env.update(overrides)
    return env


def run_python(code, env, *args):
    return subprocess.run(
        [sys.executable, '-B', '-c', code, *args], cwd=BASE_DIR, env=env,
        capture_output=True, text=True, timeout=60,
    )


class DeploymentSettingsTests(SimpleTestCase):
    def probe(self, **overrides):
        result = run_python(SETTINGS_PROBE, isolated_environment(**overrides))
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def reject(self, variable, value):
        result = run_python(SETTINGS_PROBE, isolated_environment(**{variable: value}))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('ImproperlyConfigured', result.stderr)
        self.assertIn(variable, result.stderr)

    def test_hosted_debug_true_is_rejected_for_each_environment(self):
        for environment in ('development', 'uat', 'production'):
            with self.subTest(environment=environment):
                result = run_python(SETTINGS_PROBE, isolated_environment(
                    DJANGO_ENVIRONMENT=environment, DJANGO_DEBUG='True',
                ))
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Hosted environments require DJANGO_DEBUG=False', result.stderr)

    def test_unknown_environment_is_rejected(self):
        self.reject('DJANGO_ENVIRONMENT', 'prod-typo')

    def test_allowed_host_wildcards_and_malformed_hosts_are_rejected(self):
        for host in ('*', '*.example.test', '.example.test', 'foo.*.test', 'https://example.test', 'example.test:443', ' example.test', ''):
            with self.subTest(host=host):
                self.reject('DJANGO_ALLOWED_HOSTS', host)

    def test_exact_allowed_hosts_are_preserved(self):
        hosts = 'app.example.test,healthcheck.railway.app,127.0.0.1'
        parsed = self.probe(DJANGO_ALLOWED_HOSTS=hosts)
        self.assertEqual(parsed['ALLOWED_HOSTS'], hosts.split(','))
        self.assertEqual(parsed['CSRF_TRUSTED_ORIGINS'], [])
        self.assertNotIn('healthcheck.railway.app', self.probe()['ALLOWED_HOSTS'])

    def test_csrf_wildcards_and_invalid_hosted_origins_are_rejected(self):
        for origin in ('*', 'https://*.example.test', 'https://.example.test', 'https://example.test/path', 'https://user:password@example.test', 'http://example.test', 'https://example.test:99999'):
            with self.subTest(origin=origin):
                self.reject('DJANGO_CSRF_TRUSTED_ORIGINS', origin)

    def test_trusted_origins_parse_without_rewriting(self):
        origins = 'https://app.example.test,https://uat.example.test:8443'
        parsed = self.probe(DJANGO_CSRF_TRUSTED_ORIGINS=origins)
        self.assertEqual(parsed['CSRF_TRUSTED_ORIGINS'], origins.split(','))

    def test_proxy_requires_explicit_opt_in(self):
        self.assertIsNone(self.probe()['SECURE_PROXY_SSL_HEADER'])
        self.assertIsNone(self.probe(DJANGO_TRUST_PROXY_SSL_HEADER='False')['SECURE_PROXY_SSL_HEADER'])
        self.assertEqual(self.probe(DJANGO_TRUST_PROXY_SSL_HEADER='True')['SECURE_PROXY_SSL_HEADER'], ['HTTP_X_FORWARDED_PROTO', 'https'])

    def test_hosted_secure_cookie_and_redirect_defaults(self):
        for environment in ('development', 'uat', 'production'):
            parsed = self.probe(DJANGO_ENVIRONMENT=environment)
            self.assertFalse(parsed['DEBUG'])
            for name in ('SECURE_SSL_REDIRECT', 'SESSION_COOKIE_SECURE', 'CSRF_COOKIE_SECURE'):
                self.assertTrue(parsed[name])
            self.assertFalse(parsed['CSRF_COOKIE_HTTPONLY'])
            self.assertEqual(parsed['SECURE_REDIRECT_EXEMPT'], [])

    def test_local_defaults_and_explicit_security_overrides(self):
        # Explicit overrides isolate parsing from the developer's local .env.
        parsed = self.probe(
            DJANGO_ENVIRONMENT='local', DJANGO_DEBUG='True',
            DJANGO_SECURE_SSL_REDIRECT='False', DJANGO_SESSION_COOKIE_SECURE='False',
            DJANGO_CSRF_COOKIE_SECURE='False', DJANGO_TRUST_PROXY_SSL_HEADER='False',
        )
        self.assertTrue(parsed['DEBUG'])
        self.assertFalse(parsed['SECURE_SSL_REDIRECT'])
        self.assertFalse(parsed['SESSION_COOKIE_SECURE'])
        self.assertFalse(parsed['CSRF_COOKIE_SECURE'])
        self.assertIsNone(parsed['SECURE_PROXY_SSL_HEADER'])
        self.assertEqual(parsed['STORAGES']['staticfiles']['BACKEND'], 'django.contrib.staticfiles.storage.StaticFilesStorage')
        parsed = self.probe(DJANGO_SECURE_SSL_REDIRECT='False', DJANGO_SESSION_COOKIE_SECURE='False', DJANGO_CSRF_COOKIE_SECURE='False')
        self.assertFalse(parsed['SECURE_SSL_REDIRECT'])
        self.assertFalse(parsed['SESSION_COOKIE_SECURE'])
        self.assertFalse(parsed['CSRF_COOKIE_SECURE'])

    def test_hsts_defaults_and_explicit_seconds(self):
        self.assertEqual(self.probe()['SECURE_HSTS_SECONDS'], 0)
        parsed = self.probe(DJANGO_SECURE_HSTS_SECONDS='300')
        self.assertEqual(parsed['SECURE_HSTS_SECONDS'], 300)
        self.assertFalse(parsed['SECURE_HSTS_PRELOAD'])
        self.assertFalse(parsed['SECURE_HSTS_INCLUDE_SUBDOMAINS'])
        self.reject('DJANGO_SECURE_HSTS_SECONDS', '-1')

    def test_hosted_static_settings_preserve_default_media_storage(self):
        with tempfile.TemporaryDirectory() as directory:
            parsed = self.probe(DJANGO_STATIC_ROOT=directory)
        self.assertEqual(parsed['STATIC_ROOT'], directory)
        self.assertEqual(parsed['STORAGES']['staticfiles']['BACKEND'], 'whitenoise.storage.CompressedManifestStaticFilesStorage')
        self.assertEqual(parsed['STORAGES']['default']['BACKEND'], 'django.core.files.storage.FileSystemStorage')
        self.assertEqual(parsed['MEDIA_ROOT'], str(BASE_DIR / 'media'))
        self.assertEqual(parsed['MEDIA_URL'], '/media/')
        self.assertEqual(parsed['MIDDLEWARE'][:2], ['django.middleware.security.SecurityMiddleware', 'whitenoise.middleware.WhiteNoiseMiddleware'])

    def test_runtime_requires_database_url_and_uses_postgresql(self):
        env = isolated_environment(DJANGO_STATIC_BUILD='False')
        env.pop('DATABASE_URL')
        result = run_python(SETTINGS_PROBE, env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('DATABASE_URL', result.stderr)
        self.assertEqual(self.probe()['engine'], 'django.db.backends.postgresql')
        self.assertEqual(self.probe(DJANGO_STATIC_BUILD='False')['engine'], 'django.db.backends.postgresql')

    def test_logging_is_standard_console_with_configurable_level(self):
        parsed = self.probe()
        logging_config = parsed['LOGGING']
        self.assertEqual(logging_config['root']['level'], 'INFO')
        self.assertEqual(logging_config['handlers']['console']['class'], 'logging.StreamHandler')
        self.assertEqual(logging_config['handlers']['console']['stream'], 'ext://sys.stderr')
        self.assertNotIn('filters', logging_config)
        self.assertEqual(self.probe(DJANGO_LOG_LEVEL='WARNING')['LOGGING']['root']['level'], 'WARNING')
        self.reject('DJANGO_LOG_LEVEL', 'invalid')

    def test_console_formatter_retains_exception_traceback(self):
        formatter = logging.Formatter('{levelname} {name} {message}', style='{')
        try:
            raise ValueError('synthetic test failure')
        except ValueError:
            record = logging.LogRecord('deployment.test', logging.ERROR, __file__, 1, 'Failure', (), sys.exc_info())
        output = formatter.format(record)
        self.assertIn('Traceback', output)
        self.assertIn('ValueError: synthetic test failure', output)


class StaticBuildTests(SimpleTestCase):
    def test_child_environment_is_private_and_parent_is_unchanged(self):
        with patch.dict(os.environ, {
            'DATABASE_URL': LOCAL_PLACEHOLDER_URL, 'DJANGO_SECRET_KEY': 'parent-test-secret',
            'PGPASSWORD': 'parent-test-password', 'DJANGO_STATIC_BUILD': 'False',
        }):
            before = dict(os.environ)
            child = build_environment('/tmp/static-build-test')
            self.assertEqual(dict(os.environ), before)
        self.assertNotIn('DATABASE_URL', child)
        self.assertNotIn('PGPASSWORD', child)
        self.assertNotEqual(child['DJANGO_SECRET_KEY'], 'parent-test-secret')
        self.assertEqual(child['DJANGO_STATIC_BUILD'], 'True')
        self.assertEqual(child['DJANGO_ENVIRONMENT'], 'production')
        self.assertEqual(child['DJANGO_DEBUG'], 'False')
        self.assertNotEqual(child['DJANGO_SECRET_KEY'], build_environment('/tmp/static-build-test')['DJANGO_SECRET_KEY'])

    def test_static_build_selects_dummy_without_database_url(self):
        result = run_python(SETTINGS_PROBE, build_environment('/tmp/static-build-test'), '--static-build')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['engine'], 'django.db.backends.dummy')

    def test_static_build_cannot_start_wsgi_asgi_or_runserver(self):
        for code in (
            'import config.wsgi', 'import config.asgi',
            "import sys; sys.argv=['manage.py', 'runserver']; from django.conf import settings; print(settings.DATABASES)",
        ):
            result = run_python(code, build_environment('/tmp/static-build-test'))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('DJANGO_STATIC_BUILD is restricted to collectstatic tooling', result.stderr)
        self.assertNotIn('DJANGO_STATIC_BUILD', (BASE_DIR / '.env.example').read_text())

    def test_collectstatic_succeeds_without_database_url_and_serves_only_static(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'staticfiles'
            env = build_environment(root)
            # The public wrapper generates its own private child environment.
            result = subprocess.run(
                [sys.executable, '-B', 'scripts/collectstatic.py'], cwd=BASE_DIR,
                env=env, capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            manifest = json.loads((root / 'staticfiles.json').read_text())
            for asset in ('css/responsive.css', 'cart/js/cart.js', 'locations/js/location_picker.js', 'admin/css/base.css'):
                self.assertIn(asset, manifest['paths'])
                self.assertTrue((root / manifest['paths'][asset]).is_file())
            media = Path(directory) / 'media'
            media.mkdir()
            (media / 'private-test.txt').write_text('media-must-not-be-served')
            env = isolated_environment(DJANGO_STATIC_ROOT=str(root))
            code = """
import sys
from django.conf import settings
settings.MEDIA_ROOT = sys.argv[1]
from config.wsgi import application
from django.test import Client
client = Client(HTTP_HOST='localhost')
response = client.get('/static/css/responsive.css', secure=True)
assert response.status_code == 200, response.status_code
response.close()
response = client.get('/media/private-test.txt', secure=True)
assert response.status_code == 404, response.status_code
assert b'media-must-not-be-served' not in response.content
"""
            result = run_python(code, env, str(media))
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_collectstatic_database_cursor_attempt_fails_naturally(self):
        code = """
import sys
sys.argv = ['manage.py', 'collectstatic', '--noinput']
import django
django.setup()
from django.db import connection
from django.contrib.staticfiles.management.commands.collectstatic import Command
from django.core.management import execute_from_command_line
# Inject a database-dependent collection step, without patching any connection.
def needs_database(self):
    with connection.cursor() as cursor:
        cursor.execute('SELECT 1')
Command.collect = needs_database
execute_from_command_line(sys.argv)
"""
        with tempfile.TemporaryDirectory() as directory:
            result = run_python(code, build_environment(directory))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('django/db/backends/dummy/base.py', result.stderr)
        self.assertIn('ImproperlyConfigured', result.stderr)


class GunicornContractTests(SimpleTestCase):
    def probe(self, **overrides):
        env = isolated_environment(**overrides)
        return run_python("import json, runpy; c=runpy.run_path('gunicorn.conf.py'); print(json.dumps({key:c[key] for key in ('bind','workers','worker_class','secure_scheme_headers','accesslog','errorlog')}))", env)

    def test_port_is_required_and_worker_default_is_conservative(self):
        missing = self.probe()
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn('PORT must be a positive integer', missing.stderr)
        result = self.probe(PORT='8765')
        self.assertEqual(result.returncode, 0, result.stderr)
        parsed = json.loads(result.stdout)
        self.assertEqual(parsed, {
            'bind': '0.0.0.0:8765', 'workers': 1, 'worker_class': 'sync',
            'secure_scheme_headers': {}, 'accesslog': None, 'errorlog': '-',
        })
        self.assertEqual(json.loads(self.probe(PORT='8765', WEB_CONCURRENCY='2').stdout)['workers'], 2)

    def test_invalid_port_or_worker_count_is_rejected(self):
        for port in ('0', '-1', '65536', 'abc', '80.5'):
            with self.subTest(port=port):
                self.assertNotEqual(self.probe(PORT=port).returncode, 0)
        for workers in ('0', '-1', '', '1.5', 'abc'):
            with self.subTest(workers=workers):
                result = self.probe(PORT='8765', WEB_CONCURRENCY=workers)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('WEB_CONCURRENCY', result.stderr)

    def test_gunicorn_rejects_static_build_mode(self):
        result = self.probe(PORT='8765', DJANGO_STATIC_BUILD='True')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('DJANGO_STATIC_BUILD must not be set for web startup', result.stderr)

    def test_gunicorn_accepts_actual_wsgi_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, '-B', '-m', 'gunicorn', '--check-config', '--config', 'gunicorn.conf.py', 'config.wsgi:application'],
                cwd=BASE_DIR, env=isolated_environment(PORT='8765', DJANGO_STATIC_ROOT=directory),
                capture_output=True, text=True, timeout=30,
            )
        self.assertEqual(result.returncode, 0, result.stderr)


@override_settings(SECURE_SSL_REDIRECT=False, ALLOWED_HOSTS=['testserver'])
class HealthEndpointTests(SimpleTestCase):
    def assert_uncached(self, response):
        for directive in ('no-cache', 'no-store', 'must-revalidate', 'max-age=0', 'private'):
            self.assertIn(directive, response.headers['Cache-Control'])
        self.assertIn('Expires', response.headers)

    def test_live_get_is_fixed_and_requires_no_database(self):
        response = self.client.get(reverse('health_live'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b'ok\n')
        self.assert_uncached(response)
        self.assertNotIn('sessionid', response.cookies)

    def test_live_head_is_empty_and_uncached(self):
        response = self.client.head(reverse('health_live'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b'')
        self.assert_uncached(response)

    def test_only_get_and_head_are_allowed(self):
        for route in ('health_live', 'health_ready'):
            for method in ('post', 'put', 'patch', 'delete', 'options'):
                response = getattr(self.client, method)(reverse(route))
                self.assertEqual(response.status_code, 405)
                self.assertEqual(response.headers['Allow'], 'GET, HEAD')
                self.assert_uncached(response)

    def test_ready_failure_has_no_sensitive_diagnostics(self):
        diagnostic = 'secret-user secret-password secret-host secret-db postgres://secret-user@secret-host/secret-db'
        for error in (psycopg.OperationalError(diagnostic), psycopg.DatabaseError(diagnostic), OSError(diagnostic), TimeoutError(diagnostic)):
            with self.subTest(error=type(error).__name__), patch('config.health.database_ready', side_effect=error):
                response = self.client.get(reverse('health_ready'))
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.content, b'unavailable\n')
                self.assertNotIn(diagnostic.encode(), response.content)
                self.assertNotIn(b'Traceback', response.content)
                self.assert_uncached(response)
                self.assertEqual(self.client.head(reverse('health_ready')).content, b'')

    def test_unexpected_programming_errors_are_not_swallowed(self):
        with patch('config.health.database_ready', side_effect=ValueError('programming error')):
            with self.assertRaises(ValueError):
                self.client.get(reverse('health_ready'))

    @override_settings(SECURE_SSL_REDIRECT=True, SECURE_PROXY_SSL_HEADER=None)
    def test_health_uses_normal_https_redirect_when_proxy_trust_is_off(self):
        for route in ('health_live', 'health_ready'):
            response = self.client.get(reverse(route), HTTP_X_FORWARDED_PROTO='https')
            self.assertEqual(response.status_code, 301)
            self.assertEqual(response.headers['Location'], f'https://testserver{reverse(route)}')

    @override_settings(SECURE_SSL_REDIRECT=True, SECURE_PROXY_SSL_HEADER=('HTTP_X_FORWARDED_PROTO', 'https'))
    def test_health_respects_explicit_proxy_trust(self):
        with patch('config.health.database_ready', return_value=True):
            for route in ('health_live', 'health_ready'):
                self.assertEqual(self.client.get(reverse(route), HTTP_X_FORWARDED_PROTO='https').status_code, 200)

    def test_railway_health_hostname_must_be_explicitly_allowed(self):
        client = Client(HTTP_HOST='healthcheck.railway.app')
        self.assertEqual(client.get(reverse('health_live')).status_code, 400)
        with override_settings(ALLOWED_HOSTS=['healthcheck.railway.app']):
            self.assertEqual(client.get(reverse('health_live')).status_code, 200)


@override_settings(SECURE_SSL_REDIRECT=False, ALLOWED_HOSTS=['testserver'])
class PostgreSQLReadinessTests(TestCase):
    def test_ready_get_and_head_against_disposable_postgresql(self):
        self.assertEqual(settings.DATABASES['default']['ENGINE'], 'django.db.backends.postgresql')
        for method in ('get', 'head'):
            response = getattr(self.client, method)(reverse('health_ready'))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content, b'ok\n' if method == 'get' else b'')
            self.assertIn('no-store', response.headers['Cache-Control'])

    def test_probe_selects_one_with_timeouts_and_readonly_connection(self):
        from config.health import database_ready
        from django.db import connection

        before = connection.settings_dict.copy()
        with patch('config.health.psycopg.connect') as connect:
            cursor = connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
            cursor.fetchone.return_value = (1,)
            self.assertTrue(database_ready())
            cursor.execute.assert_called_once_with('SELECT 1')
            kwargs = connect.call_args.kwargs
            self.assertEqual(kwargs['dbname'], connection.settings_dict['NAME'])
            self.assertEqual(kwargs['connect_timeout'], 2)
            self.assertTrue(kwargs['autocommit'])
            self.assertIn('default_transaction_read_only=on', kwargs['options'])
            self.assertIn('statement_timeout=1000', kwargs['options'])
        self.assertEqual(connection.settings_dict, before)
