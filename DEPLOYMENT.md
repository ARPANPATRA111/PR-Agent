# Deployment

PR-Agent Public Edition is three independently deployable components:

- FastAPI API/webhook service from `backend/Dockerfile`
- Durable reminder, digest, and cleanup worker from the same image with
  `python worker.py`
- statically exported Next.js Mini App (also reproducible with
  `frontend/Dockerfile`)

PostgreSQL is mandatory in staging and production. The API is the only service
that runs `python -m alembic upgrade head`; start workers only after that
release step succeeds. The tracked Render blueprint is a template, not an
authorization to deploy or change a webhook.

Use [the staging runbook](docs/STAGING_RUNBOOK.md) first, then
[the production runbook](docs/PRODUCTION_RUNBOOK.md). Telegram setup and
rollback are documented in [TELEGRAM_SETUP.md](docs/TELEGRAM_SETUP.md).

No real credentials, URLs, service IDs, or database names belong in tracked
files. Supply them through the deployment platform's secret store.

The staging Blueprint is pinned to `public-v2`, uses Singapore resources, and
keeps public and worker feature gates disabled for phased activation. Its API
and background worker are paid Starter resources and must not be provisioned
before the operator accepts Render's displayed cost. The static Mini App has no
always-running compute charge.

Do not add database write/delete cron jobs or self-pings as keep-alive
mechanisms. See [availability and scale-to-zero](docs/AVAILABILITY.md) and the
[staging environment matrix](docs/STAGING_ENV_MATRIX.md).
