# Durable reminder and Sunday-summary worker

Public-v2 does not run user schedules inside the FastAPI process. A standalone
worker polls PostgreSQL for due work and uses row locks, leases, and unique
occurrence keys so multiple replicas can safely compete for jobs.

## Delivery lifecycle

1. Select due schedules with `FOR UPDATE SKIP LOCKED`.
2. Insert a unique delivery occurrence.
3. Advance the durable schedule in the same transaction.
4. Commit and release database locks.
5. Send through Telegram without holding a transaction open.
6. Mark the delivery sent, failed with a future retry time, or dead-lettered.
7. Recover a claimed delivery when its lease expires after a worker crash.

Retries use bounded exponential backoff. Telegram 400/401/403/404 responses are
treated as permanent; timeouts, network errors, rate limits, and server errors
are retryable. One-time reminders are disabled after success or terminal
failure. Paused or deleted schedules cannot be reclaimed.

The database uniqueness constraints are:

- reminder ID plus scheduled occurrence
- owner ID plus digest week start
- a stable textual idempotency key for each delivery

Telegram's `sendMessage` API does not accept a caller idempotency key. Database
leases prevent concurrent sends and ordinary retries, but no system can prove
exactly-once delivery if Telegram accepts a request and the network drops the
response before the worker records success. Such ambiguous timeouts are
bounded, observable, and never cause an unbounded retry loop.

## Sunday summary

Sunday summaries are opt-in and configured per user with an IANA timezone and
local delivery time. The worker aggregates only rows with the delivery owner
ID, then formats a concise private summary of:

- work logs and selected highlights
- note and goal-update counts
- pending reminders
- income and expenses separated by currency
- approximate totals from confirmed nutrition logs

An optional narrator may rewrite the deterministic snapshot. Provider failure,
an empty response, or an oversized response always falls back to the local
template. The feature never creates a LinkedIn post or publishes content.

## Running locally

The worker fails closed unless all of these are set:

```text
PUBLIC_V2_ENABLED=true
REMINDER_WORKER_ENABLED=true
TELEGRAM_BOT_TOKEN=<development bot only>
DATABASE_URL=<development PostgreSQL URL>
```

Use an untracked Compose override containing a development-only bot token:

```powershell
docker compose --profile delivery up worker
```

Do not start this profile with a production bot token during development.

## Operational settings

```text
WORKER_POLL_INTERVAL_SECONDS=5
WORKER_BATCH_SIZE=25
WORKER_LEASE_SECONDS=120
WORKER_MAX_ATTEMPTS=5
WORKER_BASE_BACKOFF_SECONDS=30
```

The lease must exceed the maximum expected Telegram request duration. Monitor
dead-letter counts and oldest due-work age. Replaying dead letters should be an
explicit operator action after the underlying error is understood.

## Validation

SQLite tests cover deterministic state transitions and failure handling.
PostgreSQL integration tests prove that two concurrent stores claim only one
occurrence using real row locks.

```powershell
$env:DEBUG='false'
python -m pytest tests/test_durable_worker.py -q

$env:DATABASE_URL='postgresql://pr_agent_test:pr_agent_test_local@localhost:5433/pr_agent_test'
$env:POSTGRES_TEST_URL=$env:DATABASE_URL
python -m pytest tests/test_postgres_schema.py -q
```
