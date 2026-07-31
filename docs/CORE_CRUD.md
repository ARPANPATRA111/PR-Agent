# Deterministic Core CRUD

Public-v2 uses one synchronous SQLAlchemy domain layer for the Telegram bot and
the authenticated HTTP API. FastAPI endpoints are ordinary synchronous
handlers, so FastAPI runs database work in its thread pool. Telegram's async
handlers call the same services through `asyncio.to_thread`. AI providers are
not imported or called by these operations.

## Ownership

Every domain operation receives an internal `app_users.id` resolved on the
server from the authenticated Telegram identity. Request bodies do not accept
an owner field. Reads, updates, and deletes always filter by both record ID and
owner ID. A missing record and another user's record both return `404`.

The public-v2 API is under `/api/v2` and requires the Telegram Mini App session:

- `/api/v2/work-logs`
- `/api/v2/notes`
- `/api/v2/ledger`
- `/api/v2/goals`
- `/api/v2/reminders`

Each collection supports create and browse. Each record path supports view,
version-checked patch, and delete. Work logs support local-date, category, and
tag filters plus date-range aggregation. Notes support search, tag, and pinned
filters. Ledger summaries return one independent income/expense total per
currency.

## Retry and concurrency behavior

Create requests may carry an `idempotency_key` of 8–128 characters. The key is
unique within an owner and record type. Telegram commands derive it from the
chat, Telegram message ID, and operation, so webhook retries do not duplicate
records.

Mutable public records have an integer `version`. A patch must include the
version last read by the client. The update uses owner ID, record ID, and
version in one SQL statement and returns `409` when another write won the race.

## Time and money

User wall-clock timestamps require an IANA timezone. They are converted to UTC
for storage, with the user-local date stored for filtering. Nonexistent local
times during daylight-saving transitions are rejected. Ambiguous repeated
times use the first occurrence unless the client submits an already-aware
timestamp.

Ledger input uses `Decimal`; storage uses signed 64-bit minor units. Amounts
must be positive, use a recognized ISO 4217 code, and respect that currency's
decimal precision. Totals never combine or convert currencies.

## Output safety

The API returns JSON and preserves original user text. The Mini App must render
these values as text, never inject them with `dangerouslySetInnerHTML`.
Telegram command output escapes all user-controlled strings before using HTML
parse mode. Input containing null characters is rejected and all text/tag
fields have explicit limits.

## Telegram syntax

Use `/help` for the current command list. Reminder creation intentionally uses
a bounded form:

```text
/remind once|daily|weekly YYYY-MM-DD HH:MM TIMEZONE TITLE
```

Natural-language interpretation is not part of deterministic CRUD and may be
offered later only as a confirmed agent action.
