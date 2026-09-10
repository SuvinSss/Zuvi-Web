# Zuvi-Web
Zuvi Local Ecommerce Store

Demo mobile authentication is disabled. The mobile login, OTP verification,
resend, and signup-completion routes return a fixed HTTP 410 response when
reached; invalid CSRF submissions remain blocked with HTTP 403. This applies
regardless of DEBUG, with no configuration flag to re-enable demo authentication.
Password-based login and registration remain available. Visiting a disabled
route does not log out an authenticated user or change their account.

Customers who depend on demo mobile authentication and have unusable passwords
may require a separately approved identity-verification and account-recovery
process before production cutover. Their existence in production has not been
verified. This containment change does not reset passwords, recover accounts,
or introduce an authentication bypass.

Django admin permits user, AdminProfile, and Group mutations only for active
ZuuVi SUPER_ADMIN accounts with both is_staff=True and is_superuser=True.
Other valid management Admins require explicit view permissions for read-only
access; generic change permissions do not authorize user or permission changes.
Authentication accounts cannot be deleted through Django admin. Use deactivation
instead. A SUPER_ADMIN cannot remove their own active Super Admin capability or
disable their own password authentication; normal password changes remain allowed.
System-generated administrator, store, product, inventory, and order histories
are read-only in Django admin. Normal Django admin change logging is preserved.

For new Super Admin accounts, use Django's standard `python manage.py createsuperuser`
command. The custom User manager sets role=SUPER_ADMIN and requires is_staff=True
and is_superuser=True, rejecting explicitly contradictory arguments. Interactive
password entry retains Django's validation and hashing. For noninteractive use,
supply DJANGO_SUPERUSER_PASSWORD securely through the environment; without it,
Django normally creates an unusable password. Never put passwords in command
arguments or logs. Ordinary create_user behavior is unchanged.

The manager migration changes migration state only, not schema or existing data.
Existing accounts with inconsistent roles/flags are not repaired automatically
and may be denied sensitive admin operations. Whether such production accounts
exist is unverified; any review or correction requires separate approval.

Deployment foundation uses Railpack, Python 3.13 and Gunicorn's synchronous WSGI
workers. Configure these commands only during a separately approved Railway
setup. Do not rely on Railpack's inferred Django start command, which may run
migrations automatically.

```text
Build: python scripts/collectstatic.py
Start: gunicorn --config gunicorn.conf.py config.wsgi:application
```

Neither command runs migrations. Railway pre-deploy migration configuration is
separate work. Gunicorn requires the exported PORT variable, binds to
0.0.0.0:PORT, and defaults to WEB_CONCURRENCY=1. Worker count must be a positive
integer. No ASGI workers or additional timeout tuning are configured. Access
logging is disabled initially; Gunicorn errors and Django logs go to stderr.

Environment values consumed by this foundation:

| Variable | Contract |
| --- | --- |
| DJANGO_ENVIRONMENT | local (default), development, uat or production; unknown values fail. |
| DJANGO_DEBUG | Defaults False; True is rejected for all hosted environments. |
| DJANGO_SECRET_KEY | Required runtime secret; use a different secret per environment. |
| DJANGO_ALLOWED_HOSTS | Exact comma-separated hostnames, required for hosted environments; no wildcard, leading-dot patterns, schemes or ports. |
| DATABASE_URL | Required runtime database URL; DEV/UAT must use their own databases. |
| DB_CONN_MAX_AGE | Existing connection lifetime, default 0. |
| DB_SSL_REQUIRE | Existing database SSL requirement, default False. |
| DJANGO_CSRF_TRUSTED_ORIGINS | Exact comma-separated origins including scheme and optional port; default empty. Hosted origins require HTTPS. No wildcards, paths or credentials. |
| DJANGO_TRUST_PROXY_SSL_HEADER | Default False; explicit True trusts X-Forwarded-Proto=https. |
| DJANGO_SECURE_SSL_REDIRECT | Default False locally, True for hosted environments. |
| DJANGO_SESSION_COOKIE_SECURE | Default False locally, True for hosted environments. |
| DJANGO_CSRF_COOKIE_SECURE | Default False locally, True for hosted environments. |
| DJANGO_SECURE_HSTS_SECONDS | Nonnegative integer, default 0. |
| DJANGO_LOG_LEVEL | DEBUG, INFO (default), WARNING, ERROR or CRITICAL. Does not enable SQL debug logging. |
| DJANGO_STATIC_ROOT | Collected static destination; default staticfiles/ under the repository. Relative values resolve against the repository. |
| WEB_CONCURRENCY | Exported Gunicorn worker count; positive integer, default 1. |
| PORT | Exported Gunicorn port; required, integer 1–65535, no runtime fallback. |

Only local Django settings load .env. Hosted processes must receive their
configuration explicitly. Gunicorn configuration reads exported process
variables and does not load .env. Host and origin entries are validated, not
rewritten. healthcheck.railway.app must be explicitly included in
DJANGO_ALLOWED_HOSTS when Railway healthchecks are enabled; it is never added
automatically and does not belong in CSRF trusted origins.

Railway DEV/UAT/PROD must not be deployed until the proxy's control of
X-Forwarded-Proto is verified. Once verified, deliberately set
DJANGO_TRUST_PROXY_SSL_HEADER=True. With hosted SSL redirects enabled by default,
missing or incorrect proxy configuration can cause redirect loops and failed
healthchecks. Gunicorn's independent secure-scheme header interpretation is
disabled so Django controls this opt-in. No client-IP trust behavior is added.

Keep HSTS at 0 throughout initial DEV/UAT HTTPS validation. After validation,
intentionally increase it to a conservative value such as 300 seconds. HSTS
preload and includeSubDomains remain disabled. CSRF_COOKIE_HTTPONLY remains
False because cart and location JavaScript read the csrftoken cookie.

GET/HEAD /health/live/ returns a fixed process response without accessing the
database. GET/HEAD /health/ready/ uses a separate read-only PostgreSQL connection
to execute SELECT 1, with a two-second connection timeout and a one-second
statement timeout. The probe connection closes after each request. Success is
200; expected database/connectivity failure is 503. Responses are minimal and
non-cacheable, contain no database diagnostics, and require no authentication.
Unexpected programming errors are not swallowed. These routes follow normal
HTTPS/proxy behavior with no redirect exemptions. Railway's later deployment
healthcheck path is /health/ready/. If DEV probes fail due to redirects, record
the exact request, headers, response status and platform behavior for review
before proposing an exemption.

WhiteNoise immediately follows SecurityMiddleware and serves collected static
files only. Hosted settings use CompressedManifestStaticFilesStorage for hashed,
compressed assets. Local/test settings retain Django's normal static backend;
DEBUG=True runserver behavior remains available. Default/media storage is
unchanged. Uploaded images still depend on local media/ and are not served by
WhiteNoise; durable media storage remains a deployment blocker.

The static-build script starts a fresh child using the same Python executable.
It passes only OS execution/locale/temp variables plus explicit build settings:
production mode, DEBUG=False, a generated temporary secret, localhost as the
placeholder allowed host, and the requested static output directory. It does
not forward DATABASE_URL, PostgreSQL credentials or runtime secrets, and does
not mutate the parent process environment. The child runs the ordinary command
python manage.py collectstatic --noinput.

DJANGO_STATIC_BUILD=True is a private flag set only in that build child. It
selects Django's dummy database backend directly during settings loading,
before django.setup(), without parsing or requiring DATABASE_URL. Unexpected
database cursor/connection use fails naturally and the child failure propagates.
There is no connection monkeypatching. This flag must never be configured in
Railway runtime or a developer's .env. Settings reject it outside the collectstatic
management command, and Gunicorn explicitly rejects it at startup. Normal runtime
still requires DATABASE_URL and uses its configured PostgreSQL database.

Validate with the worktree's virtual environment and a verified local PostgreSQL
test database, with isolated temporary media and static destinations. Run focused
deployment tests, manage.py check, hosted manage.py check --deploy, the isolated
static build, and the full PostgreSQL suite. Never suppress deployment warnings:
HSTS disabled (security.W004) is intentional before HTTPS validation; enabling
HSTS while keeping includeSubDomains/preload disabled may also report
security.W005/security.W021. Report each actual warning separately.

Console logging uses standard Python/Django handlers and formatters, with useful
server exception tracebacks retained. No request-body/header/cookie logging,
environment dumps, custom redaction framework or external logging provider is
introduced. Database AdminAuditLog behavior is independent and unchanged.

Remaining deployment work includes durable uploaded-media storage, verified
proxy/HTTPS behavior, separate environment databases/secrets/domains, and an
approved migration/backup/rollback and production repository-cutover procedure.
This foundation alone is not approval to deploy or change Railway.
