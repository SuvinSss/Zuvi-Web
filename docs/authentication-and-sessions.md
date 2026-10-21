# Authentication and sessions

- Credentials are the existing Django users; only accounts that can access the management portal may sign in through the API.
- The browser holds **only** the HttpOnly `sessionid` cookie (database-backed Django session, SameSite=Lax, 14 days by default, persists across browser restarts). No tokens, passwords or user data are stored in `localStorage`.
- CSRF is enforced for every unsafe request. The SPA sends `X-CSRFToken` from the `csrftoken` cookie, or from the `csrf_token` returned by `/auth/session/` when the cookie is unreadable (cross-origin).
- On load the SPA calls `GET /auth/session/`; a refresh therefore restores the session from the server. A 401/403 from any API call marks the session expired and sends the user to the login page with a notice.
- Login is rate-limited (default 10/min per client). Each login rotates the CSRF token and session key (Django behaviour). Logout flushes the server session.
- Cross-origin deployment requires `DJANGO_CORS_ALLOWED_ORIGINS`, `DJANGO_CSRF_TRUSTED_ORIGINS` and cookies that the browser will send (same *site*, e.g. `app.example.com` + `api.example.com`, with `SameSite=Lax` and Secure). Third-party-cookie contexts are not supported.

Verified: login/logout, reload restoration, redirect of anonymous visitors, wrong-credentials handling (Playwright, unit and API tests), and that an existing session cookie is still accepted after the Django process is restarted (sessions live in the database). **Not verified:** cross-origin production hosting (SPA on a different host than the API) and S3-backed media in a hosted environment.
