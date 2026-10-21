# Store onboarding guide

## Creating a store (React Admin → Stores → Add store)
Six steps: basics, address and location, business and documents, hours and ordering, owner, commercial and review. *Save draft* works with only a name and category; missing address details are listed as missing requirements instead of blocking the save. Status is decided by the server (see [admin-approval-and-import-workflows.md](admin-approval-and-import-workflows.md)).

## Owner account options
1. **New owner with setup link (default, recommended).** The owner account is created with no usable password. The API returns a one-time link `/setup-account?token=…`. If e-mail is configured (`EMAIL_HOST`), the same link is e-mailed and `email_sent` is `true` only if the mail backend accepted the message; otherwise the admin sees "No e-mail was sent" and passes the link on.
2. **Assign an existing store user.** Search by username, name or e-mail. Only active accounts with the Store User role qualify; customers, admins, delivery partners and the acting administrator are refused.
3. **New owner with a password the admin chooses.** Allowed but discouraged; validated by Django's password validators and hashed. It is never returned or logged.
4. **Add the owner later.** The store is marked Needs Information.

## The setup link
* Signed and time-limited (3 days), single use: it embeds part of the current password hash, so it stops working once a password is set.
* Shown to the admin once, never stored, logged or audited. A new link can be issued from the store's *Owner & staff* tab (only for people who have no password yet).
* The owner opens it, picks a password (validated), then signs in. Tokens that are expired, altered or already used are rejected.

## Roles and boundaries
Owners have the Store User role and are linked to their store through a membership; the store portal only returns that store's data, and the management APIs refuse store users. Creating the store, the owner and the membership happens in one transaction: a duplicate username or weak password rolls back the whole store.

## Audit
Store creation, status changes, verification and invite re-issue are recorded. Passwords and setup links are not.

## Limits
No SMS delivery, no automatic e-mail retry, and no way to revoke an unused link other than setting a password or letting it expire.
