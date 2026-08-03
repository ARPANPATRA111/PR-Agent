# Deployment

PR-Agent Public Edition has a production-capable three-component topology:

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

Two Blueprints are intentionally maintained:

- `render.yaml` is the production-capable topology with an API, a dedicated
  durable worker, and a static Mini App. Its paid resources require explicit
  approval.
- `render.free.yaml` is an isolated free staging/demo topology with one free API
  and one free static Mini App. It uses a feature-flagged in-process delivery
  loop only while the API is awake. It must never manage the same services as
  `render.yaml`.

The free profile proposes the independently named resources
`pr-agent-r24-staging-api` and `pr-agent-r24-staging-web`. These names and their
resulting URLs are candidates until deployment is completed in the verified
correct Render account. The old mistaken-account site at
`https://pr-agent-staging-web.onrender.com` is not part of the free profile and
must not be used for the new Telegram bot.

For the free API, migrations run in the single container startup command before
Uvicorn starts. Keep one instance. The existing staging Neon project is supplied
only through Render's secret store. AI, voice transcription, external nutrition
estimation, message cleanup, and paid monitoring remain disabled initially.
Telegram is also disabled for the pre-bot deployment: the Blueprint sets
`TELEGRAM_INTEGRATION_ENABLED=false` and does not request a bot token. In this
state `/ready` reports `awaiting_telegram`, the webhook and Mini App
authentication return 503, and no delivery or cleanup client is constructed.

After deployment, verify the exact new URLs without Telegram credentials:

```powershell
python scripts/verify_staging_deployment.py `
  --api-url https://pr-agent-r24-staging-api.onrender.com `
  --frontend-url https://pr-agent-r24-staging-web.onrender.com
```

If the services are created separately with the Render CLI, its static-site
creation command does not expose header or rewrite flags. Before accepting the
deployment, add the three tracked `headers` rules and the `/* -> /index.html`
rewrite from `render.free.yaml` in the static site's dashboard. The verification
script fails closed when any of them is absent. The CLI also does not accept a
Docker Command override; copy the tracked `dockerCommand` into the free API's
dashboard settings so every deploy runs migrations before starting Uvicorn.

Do not add database write/delete cron jobs or self-pings as keep-alive
mechanisms. See [availability and scale-to-zero](docs/AVAILABILITY.md) and the
[staging environment matrix](docs/STAGING_ENV_MATRIX.md).
