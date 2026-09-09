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
