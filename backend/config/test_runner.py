"""Temporary local media and an SDK network boundary for ordinary Django tests."""

from contextlib import ExitStack
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.conf import settings
from django.test import override_settings
from django.test.runner import DiscoverRunner


class IsolatedMediaTestRunner(DiscoverRunner):
    def run_tests(self, test_labels, **kwargs):
        # Cover discovery, setup, execution and teardown; unwind on failure too.
        with ExitStack() as stack:
            media_root = stack.enter_context(TemporaryDirectory(prefix='zuvi-test-media-'))
            storages = {
                **settings.STORAGES,
                'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
            }
            stack.enter_context(override_settings(MEDIA_ROOT=media_root, STORAGES=storages))
            stack.enter_context(patch(
                'botocore.httpsession.URLLib3Session.send',
                side_effect=AssertionError('AWS HTTP requests are forbidden in the normal test suite.'),
            ))
            return super().run_tests(test_labels, **kwargs)
