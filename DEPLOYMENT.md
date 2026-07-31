# Deployment

PR-Agent Public Edition is three independently deployable components:

- FastAPI API/webhook service from `backend/Dockerfile`
- Durable reminder, digest, and cleanup worker from the same image with
  `python worker.py`
- Next.js Mini App from `frontend/Dockerfile`

PostgreSQL is mandatory in staging and production. The API is the only service
that runs `python -m alembic upgrade head`; start workers only after that
release step succeeds. The tracked Render blueprint is a template, not an
authorization to deploy or change a webhook.

Use [the staging runbook](docs/STAGING_RUNBOOK.md) first, then
[the production runbook](docs/PRODUCTION_RUNBOOK.md). Telegram setup and
rollback are documented in [TELEGRAM_SETUP.md](docs/TELEGRAM_SETUP.md).

No real credentials, URLs, service IDs, or database names belong in tracked
files. Supply them through the deployment platform's secret store.
