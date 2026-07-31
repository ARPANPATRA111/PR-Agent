# Public-v2 Security Model

## Trust boundaries

The browser is untrusted. It may supply display input, filters, record IDs, and
Telegram Mini App `initData`, but it never supplies the tenant identity used by
the data layer. Telegram is the identity provider. The backend, database, and
worker are trusted only after their deployment configuration has passed startup
validation.

The only unauthenticated application endpoints are:

- `GET /api/health`
- `POST /api/auth/telegram`
- `POST /webhook`

The webhook is outside the browser API boundary but requires Telegram's
`X-Telegram-Bot-Api-Secret-Token` header.

## Browser authentication

The Mini App sends Telegram's signed `initData` to the backend. The backend:

1. Rejects duplicate fields, malformed users, bot users, stale timestamps, and
   future timestamps.
2. Reconstructs Telegram's data-check string and verifies its HMAC with a
   constant-time comparison.
3. Creates or refreshes the local user.
4. Issues a short-lived, signed, HTTP-only session cookie and a separate CSRF
   token.

Cookie-authenticated mutations must present the matching `X-CSRF-Token`.
Bearer sessions are supported for non-browser clients and tests, but no browser
credential or Telegram ID is persisted in local storage. Production cookies are
`Secure`; cross-origin production deployments use `SameSite=None` and an exact
CORS allowlist.

## Telegram webhook

Webhook requests have four controls:

- A configured secret header checked before parsing the request.
- A request-body limit.
- A database-backed per-Telegram-user rate limit.
- A unique persisted Telegram `update_id` record that prevents replay and
  duplicate processing across processes.

Webhook-management and scheduler-trigger routes are not exposed by the public
application. Webhook setup is an operator CLI action.

## Abuse and failure controls

Authentication is rate-limited by a one-way hash of the source address. Private
API traffic is rate-limited by the authenticated internal user ID. Buckets are
stored in the database, so adding web processes does not create independent
limits.

Unexpected errors return a generic production message. Raw model reasoning is
not returned by the agent-analysis endpoint. Production startup fails when
required secrets, PostgreSQL, HTTPS URLs, exact CORS origins, or TLS verification
are missing or unsafe.

## Secrets

Repository history was scanned in Phase 0. No committed credential was found.
The ignored local `.env` contains redacted live-looking values, so Telegram and
AI credentials must still be rotated before any public deployment. Follow
`docs/SECRET_ROTATION_CHECKLIST.md`; do not enable the public-v2 feature gate
until rotation and webhook-secret registration are confirmed.

## Known transitional boundary

Several legacy read endpoints still declare a `telegram_id` query parameter.
The security middleware removes every caller-supplied value and replaces it
with the verified session identity before route validation. Later CRUD phases
will remove these parameters from the route signatures entirely. Tests cover
arbitrary-ID injection during this transition.
