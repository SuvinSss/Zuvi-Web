"""Unauthenticated probes with no application data or diagnostic responses."""

import psycopg
from django.db import connection
from django.http import HttpResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe


@never_cache
@require_safe
def live(request):
    return HttpResponse('ok\n', content_type='text/plain')


def database_ready():
    # Use Django's current database parameters (including the disposable test
    # database during tests), but do not alter/reuse its application connection.
    params = connection.get_connection_params()
    params['connect_timeout'] = 2
    params['options'] = (
        params.get('options', '')
        + ' -c default_transaction_read_only=on -c statement_timeout=1000'
    )
    with psycopg.connect(**params, autocommit=True) as probe:
        with probe.cursor() as cursor:
            cursor.execute('SELECT 1')
            return cursor.fetchone() == (1,)


@never_cache
@require_safe
def ready(request):
    try:
        available = database_ready()
    except (psycopg.Error, OSError):
        available = False
    return HttpResponse(
        'ok\n' if available else 'unavailable\n',
        status=200 if available else 503,
        content_type='text/plain',
    )
