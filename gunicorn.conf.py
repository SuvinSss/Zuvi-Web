"""WSGI runtime contract; no migrations or static collection at startup."""

import os

import environ


if environ.Env().bool('DJANGO_STATIC_BUILD', default=False):
    raise RuntimeError('DJANGO_STATIC_BUILD must not be set for web startup.')


def positive_integer(name, default=None):
    value = os.environ.get(name, default)
    if value is None or not value.isascii() or not value.isdecimal() or int(value) < 1:
        raise RuntimeError(f'{name} must be a positive integer.')
    return int(value)


port = positive_integer('PORT')
if port > 65535:
    raise RuntimeError('PORT must be at most 65535.')
bind = f'0.0.0.0:{port}'
workers = positive_integer('WEB_CONCURRENCY', '1')
worker_class = 'sync'
accesslog = None
errorlog = '-'
loglevel = 'info'
# Django alone controls proxy SSL opt-in. No independent scheme/header trust.
secure_scheme_headers = {}
