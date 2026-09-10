# Zuvi-Web
Zuvi Local Ecommerce Store

Demo mobile authentication is disabled. The mobile login, OTP verification,
resend, and signup-completion routes return a fixed HTTP 410 response when
reached; invalid CSRF submissions remain blocked with HTTP 403. This applies
regardless of DEBUG, with no configuration flag to re-enable demo authentication.
Password-based login and registration remain available. Visiting a disabled
route does not log out an authenticated user or change their account.

The new deployment starts with fresh accounts and data. No old-account recovery,
session preservation or authentication bypass is part of this deployment plan.

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
DEBUG=True runserver behavior remains available. Uploaded media uses the separate
default storage contract below and is never served by WhiteNoise. Local media/
remains available for local development only.

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

Remaining deployment work includes provisioning isolated UAT/PROD media buckets,
verifying proxy/HTTPS behavior, separate fresh databases/secrets/domains, and
approved bootstrap, backup, rollback and domain-switch procedures.
This foundation alone is not approval to deploy or change Railway.

Uploaded media uses django-storages with AWS S3 in Mumbai (ap-south-1) for hosted
runtime. ProductImage.image and Store.image retain their existing fields and
UUID upload paths: products/images/ and stores/images/. No model migration or
existing-object copy is performed by enabling this code.

| Variable | Media contract |
| --- | --- |
| MEDIA_STORAGE_BACKEND | filesystem locally (default); hosted development/uat/production require explicit s3. Other combinations fail. |
| MEDIA_BUCKET_NAME | Required for S3: the current environment's dedicated private bucket. |
| MEDIA_REGION_NAME | Required for S3: ap-south-1. |
| MEDIA_ACCESS_KEY_ID | Required for S3: the current environment's dedicated credential. |
| MEDIA_SECRET_ACCESS_KEY | Required for S3: its matching secret. Never commit or log it. |

Missing/blank S3 configuration fails at startup rather than falling back to disk
or ambient AWS credentials. No bucket is created or checked during settings
loading. Use a dedicated bucket and credential pair for each environment:
develop/development -> DEV, uat/uat -> UAT, main/production -> PROD. Configuration
parsing alone cannot prove isolation: separately verify IAM policies before
deployment. DEV/UAT principals must have no access to the PROD bucket. Avoid
shared project-wide production credentials; provision and rotate each environment
independently. No credentials, bucket configuration or provider access is included
in this repository batch.

Before deployment, enable bucket/account Block Public Access and bucket-owner
enforced ownership with ACLs disabled. Require HTTPS and scope runtime GetObject,
PutObject and ListBucket permissions to that environment's bucket. ListBucket is
needed for reliable missing-key checks with overwrite prevention. Do not grant
runtime bucket administration, object deletion or version deletion. Provisioning,
versioning/recovery policy and any cleanup credentials require separate approval.
The backend requests no ACL (default_acl=None); it cannot make an incorrectly
provisioned bucket private on its own.

Media URLs use HTTPS Signature V4 with a 300-second lifetime. Query-string
authentication is always enabled, custom domains are disabled, and no public-read
ACL is sent. Existing keys are not overwritten and no extra location prefix is
added. Objects use Cache-Control: private, no-store. SDK connections have a
3-second connect timeout, 5-second read timeout and at most two attempts per
request; these are not a total upload deadline. SDK debug logging stays disabled
even if application logging is DEBUG, because it can include signed requests.
Do not log full signed URLs: they are temporary bearer capabilities.

Existing public catalogue visibility and management/store permission checks
remain responsible for deciding which images may have URLs rendered. The storage
backend itself does not know the current user. Never add an arbitrary-key signing
endpoint. Unpublishing prevents new public URL issuance but does not revoke an
already issued URL before expiry or a downloaded copy. CloudFront, public buckets
and direct-to-bucket browser uploads are not introduced.

Static builds always select local filesystem media storage before checking S3
configuration; the private build child still requires no media credentials or
database. Collected static storage remains WhiteNoise. Run:

```text
.venv/bin/python manage.py test
```

The supported manage.py test command ignores ambient media backend/credentials.
The configured IsolatedMediaTestRunner overrides default storage with a temporary
filesystem directory across discovery, setup, tests and teardown, then cleans it
up even on failure. It also rejects SDK HTTP calls. Database selection is not
changed by this runner: verify local PostgreSQL 127.0.0.1:5432/zuvi_dev before
running, use Django's disposable test_zuvi_dev, and do not run tests concurrently
from another worktree. Configuration probes use synthetic credentials and
isolated child environments; signing is checked offline. Compatibility tests use
an object-storage fake whose .path is unsupported. There are no real-bucket tests
in the normal suite. Custom runners/direct test invocation must preserve the same
isolation; bypassing the configured runner is not a supported storage-test path.

Product image changes use the authoritative batch service in catalog/services.py.
It locks Product rows in primary-key order before checking the final image count:
at most five images, and at least one remaining when removing images from an
APPROVED product. Other statuses may have zero images. A successful image addition,
binary replacement or removal returns an APPROVED product to PENDING through the
normal status service, with approval metadata cleared and history/audit recorded.
It is no longer public until reapproved. Alt text, order and primary-flag edits do
not require reapproval. Pricing approval rules are unchanged.

Management/store portals and standalone/inline/bulk Django admin image operations
use these services. Existing image records cannot be reassigned to another product
in admin. Arbitrary ORM writes outside these supported paths do not enforce the
service contract; future writers must use the service, not direct save/delete.

Multi-image product creation and image batches roll back database references and
related database changes together on failure. Expected storage errors receive a
generic message; server logs retain tracebacks. Store replacement failure preserves
the old image reference and rolls back related edits. Image changes do not change
store status. Replacement, clearing and deletion never physically delete the old
stored object. SQL rollback cannot undo an upload: already-written objects remain
orphan candidates. Delayed cleanup, grace periods and object recovery/versioning
policy require a separate approved batch; no cleanup job is implemented here.

Deployment is a fresh start in the owner's new Railway workspace. Development is
local Mac/PostgreSQL plus GitHub Actions; no permanent Railway DEV is required.
UAT uses branch uat, a fresh database and dedicated private S3 bucket/credentials.
Production uses branch main, a separate fresh database and private S3 bucket with
separate credentials. UAT credentials must have no production-media access.
No old production database, migration ledger, users, sessions, media or volumes
will be copied or reconciled. Apply normal schema migrations to the new empty
databases and create new accounts through supported bootstrap/registration paths.

The old deployment stays online temporarily and must not be accessed or changed
during repository preparation. After UAT and new-production smoke tests pass,
moving zuuvi.in, verifying the domain and shutting down the old project each need
separate approval. Establish backups and rollback for new data before accepting
live writes; reverting application code does not roll back database or object
writes. This repository patch does not provision buckets, migrate media or deploy.
