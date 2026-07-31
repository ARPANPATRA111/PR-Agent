# Tenant Isolation

## Tenant key

The external tenant key is Telegram's numeric user ID, obtained only from
verified Mini App data or a verified webhook update. Browser requests are
resolved to an internal user ID and Telegram ID from the signed session.

## Enforcement rules

- Request payloads and query strings never choose the acting tenant.
- Collection queries filter by the authenticated Telegram ID.
- Object lookups, updates, publication actions, and deletes filter by both the
  object primary key and authenticated Telegram ID in the same database query.
- An object belonging to another user is reported as `404 Not Found`, not
  `403 Forbidden`, to avoid confirming that the object exists.
- Settings are read and written only for the session owner.
- Rate-limit subjects use authenticated internal user IDs rather than
  user-supplied identifiers.

The application layer is not allowed to retrieve an unscoped object and check
ownership afterward. Repository methods for posts accept the tenant key as a
required argument.

## Phase 1 verification

`backend/tests/test_security_boundary.py` creates two tenants in an isolated
database and verifies that tenant A cannot read, update, or delete tenant B's
post. It also verifies that adding tenant B's Telegram ID to tenant A's request
still returns tenant A's settings.

Every new public-v2 repository method must add the tenant predicate at query
time and add a two-user negative test before its phase can pass.
