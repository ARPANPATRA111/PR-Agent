# Production runbook

Production promotion requires a passing candidate commit, a completed staging
checklist, a tested backup restore, and explicit approval from the operator.

1. Confirm staging and production credentials and databases are different.
2. Take and verify a database backup. Record its provider snapshot identifier
   outside the repository.
3. Deploy the API with all public and worker flags disabled.
4. Run `cd backend && python -m alembic upgrade head`; verify `/ready`.
5. Deploy the Mini App and verify its exact HTTPS origin matches
   `CORS_ORIGINS` and Telegram configuration.
6. Deploy the worker with `REMINDER_WORKER_ENABLED=false`.
7. Create 10–30 expiring beta invites through `python -m admin_cli`.
8. Set `PUBLIC_V2_ENABLED=true` on API and worker, then set
   `REMINDER_WORKER_ENABLED=true` on the worker.
9. Change the Telegram webhook only after the API and worker metrics are
   healthy.
10. Keep AI and message cleanup disabled for the first deterministic smoke
    test; enable each separately.

Monitor authentication rejection, duplicate update, failed delivery, due-job
lag, worker heartbeat, provider failure, export, deletion, and usage counters.

Rollback order: restore the prior webhook or delete it, disable public flags,
stop the worker, deploy the prior saved versions, and follow the migration's
documented downgrade or restore decision. Never downgrade a live database
without a verified backup.
