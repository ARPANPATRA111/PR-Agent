# Staging runbook

Staging must use a separate bot token, webhook secret, signing secret, database,
frontend origin, provider credentials, and monitoring token. Never point it at
production.

1. Create PostgreSQL and take an initial provider snapshot.
2. Configure every required variable from `.env.example`; keep
   `PUBLIC_V2_ENABLED=false`, `AI_AGENT_ENABLED=false`,
   `REMINDER_WORKER_ENABLED=false`, and `MESSAGE_CLEANUP_ENABLED=false`.
3. Build the backend and frontend from the candidate commit.
4. Run `cd backend && python -m alembic upgrade head`, then
   `python -m alembic check`.
5. Start the API. Verify `/health`, `/ready`, and authenticated
   `/internal/metrics`.
6. Create a short-lived invite with
   `cd backend && python -m admin_cli create-invite --expires-days 2`.
7. Enable `PUBLIC_V2_ENABLED=true` on the API and worker. Enable
   `REMINDER_WORKER_ENABLED=true` only on the worker.
8. Configure the staging webhook using the command in `TELEGRAM_SETUP.md`.
9. Execute `docs/BETA_RELEASE_CHECKLIST.md`, including a reminder delivery,
   export, account deletion, and provider-failure drill.
10. Enable AI, cleanup, or nutrition independently only after their tests pass.

Rollback: delete or restore the previous webhook, disable public feature flags,
stop the worker, deploy the previous saved application version, and restore the
database only when the migration rollback plan explicitly requires it.
