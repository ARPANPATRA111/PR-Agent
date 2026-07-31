# Public v2 Scope

## Product

Public v2 is an invite-only Telegram personal assistant with a Telegram Mini
App. Each authenticated user privately manages:

- Work logs
- Notes
- One-time, daily, and weekly reminders
- Expenses and income, stored in minor currency units
- Food, calorie, protein, and optional macro estimates
- Personal goals with manual progress
- On-demand summaries
- An optional concise Sunday digest
- Data export and account deletion

PostgreSQL is the source of truth. A durable worker handles reminders, digests,
cleanup, exports, and deferred work.

## Security invariants

- Server-validated Telegram identity is the only user identity accepted.
- Request bodies, query parameters, usernames, `initDataUnsafe`, and
  `localStorage` never determine ownership.
- Every user-owned read and write is scoped by authenticated internal owner ID.
- Cross-tenant resource access returns `404`.
- Telegram webhooks require a configured secret and durable update
  deduplication.
- Administrative operations are CLI or protected internal operations, not
  public routes.
- Destructive and ambiguous operations require explicit confirmation.
- Model output is typed and validated before it can reach a domain service.
- The model never receives or chooses an owner ID.
- Explicit commands and Mini App CRUD work when AI providers are unavailable.
- No hidden model reasoning is stored or returned.

## Phased release gates

1. Baseline audit and recovery point.
2. Webhook security, Mini App sessions, and tenant isolation.
3. PostgreSQL migrations and additive public-v2 schema.
4. Deterministic work-log, note, ledger, goal, and reminder CRUD.
5. Editable nutrition estimation and safety behavior.
6. Authenticated, mobile-first Telegram Mini App.
7. Durable reminder and Sunday-digest worker.
8. Cascading deletion, export, message cleanup, and account lifecycle.
9. Optional bounded AI tools and evaluations.
10. Invite controls, quotas, observability, tracked CI, and deployment.
11. Invite-only beta release validation.

No phase starts until the previous phase's required tests and release criteria
have been inspected and recorded.

## Feature flags

New public behavior remains off by default until its phase passes:

```text
PUBLIC_V2_ENABLED
INVITE_ONLY
MESSAGE_CLEANUP_ENABLED
SUNDAY_DIGEST_ENABLED
AI_AGENT_ENABLED
NUTRITION_ENABLED
REMINDER_WORKER_ENABLED
```

Production configuration must fail closed. Development defaults may be
convenient but must never grant authentication or tenant access.

## Explicit exclusions

The initial public release does not include:

- LinkedIn or other social-media post generation
- Automatic publication
- Bank, UPI, or payment initiation
- Exchange-rate conversion
- Receipt OCR or statement imports
- Financial advice
- Medical or disease-specific nutrition advice
- Model-selected dietary targets
- Fully autonomous goal progress
- Arbitrary agent code or SQL execution
- Anonymous unrestricted access
- Unlimited AI usage

## Data preservation

Legacy tables and the owner's local databases are preserved through the beta
migration. Public-v2 tables are introduced additively. Backfills must be
explicit, repeatable, and verified; no legacy table or personal database is
deleted automatically.
