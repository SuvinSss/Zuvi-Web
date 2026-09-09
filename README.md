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
