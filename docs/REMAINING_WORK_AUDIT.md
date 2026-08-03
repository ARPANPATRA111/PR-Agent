# Remaining-work audit

Audit date: 2026-08-03. Scope: tracked source, tests, deployment manifests,
documentation, GitHub repository metadata, and issue #1 on `public-v2`.
Owner-authored untracked documents were excluded and left unchanged.

## Summary

| Classification | Count | Meaning |
|---|---:|---|
| Implemented in this deployment pass | 6 | Deterministic, free, and locally verifiable |
| Intentionally deferred | 5 | Requires a later privacy/provider/scale gate |
| Production-only | 3 | Not appropriate for the free staging profile |
| Obsolete/dead | 4 | Retained only for rollback/history or awaiting cleanup |
| False positive | 5 | Search hit is intentional code/test configuration |
| External activation | 5 | Requires an authenticated provider or owner-only action |
| **Total classified items** | **28** | No unclassified TODO/FIXME markers found |

## Implemented in this pass (6)

1. Telegram-independent staging configuration and fail-closed activation.
2. A pre-bot API lifespan that does not build Telegram delivery/cleanup clients
   or claim pending records.
3. Safe readiness component and Alembic revision reporting.
4. `scripts/verify_staging_deployment.py` for health, readiness, revision,
   disabled Telegram behavior, frontend, CORS, and optional protected delivery
   metrics checks.
5. `scripts/activate_staging_bot.py`, which reuses the command/webhook helpers,
   supports dry-run and status modes, restricts the destination, and does not
   print secrets.
6. The wrong Render CLI session was logged out; the CLI now verifies
   `ranjeetapatra24@gmail.com` and the expected `Ranjeeta's workspace`. No older
   Render services were listed or changed.

## Intentionally deferred (5)

1. AI provider activation: the bounded deterministic assistant remains behind
   `AI_AGENT_ENABLED`; a provider credential and failure drill are required.
2. Voice transcription: disabled for the free public beta until privacy,
   retention, quota, and provider-cost checks are accepted.
3. Telegram message cleanup: implemented but off until deletion timing and user
   expectations are validated end to end.
4. External nutrition estimation: manual nutrition works; the reference
   provider stays disabled in free staging.
5. Legacy schema removal: additive migrations and account deletion deliberately
   preserve/support legacy rows for rollback and migration safety.

## Production-only (3)

1. The dedicated durable Render worker in `render.yaml` requires a paid service;
   free staging uses the best-effort inline loop only while the API is awake.
2. Sentry activation requires an approved project/DSN and privacy review.
3. Always-on delivery and formal SLO monitoring require a paid topology; no
   artificial database churn or self-ping is used to evade free-tier sleeping.

## Obsolete/dead (4)

1. GitHub issue #1 (`ReVamp needed !!`) describes the old desired revamp. Its
   implementation is substantially present, but closure waits for live staging
   validation.
2. GitHub About still describes a personal progress-report agent and points to
   an old Vercel homepage; update only after the new frontend is live.
3. The private legacy scheduler/report path and `prompts/weekly_report.md` remain
   reachable only when `PUBLIC_V2_ENABLED=false`; public-v2 explicitly retires
   their routes and commands.
4. `render.yaml` contains the earlier paid topology and retired candidate URLs.
   It is not the free deployment input and must not manage the new resources.

## False positives (5)

1. `pass` in assistant/nutrition provider exception base classes is an ordinary
   empty exception body, not missing behavior.
2. `pass` in guarded Telegram/inline cleanup exception paths is best-effort
   cleanup behavior covered by tests.
3. `pytest.mark.skipif` in PostgreSQL schema tests is environment-gated coverage;
   it runs when `TEST_POSTGRES_DATABASE_URL` is supplied.
4. The single explicit legacy database-file skip in `test_all.py` is superseded
   by isolated migration/schema suites and is not production behavior.
5. TypeScript `skipLibCheck` and UI `disabled` attributes are compiler/accessibility
   settings, not disabled product features.

## External activation (5)

1. Create the free Blueprint resources from `render.free.yaml` and supply the
   existing staging Neon `DATABASE_URL` through Render's secret field.
2. Verify the live API and static site with the deployment diagnostic.
3. Create a distinct staging bot in BotFather, configure its Mini App URL, and
   store its token/secret in Render before enabling Telegram.
4. Create and privately deliver a short-lived beta invite after deployment.
5. Update GitHub About/homepage and close issue #1 only after live smoke tests.

## Blockers and credentials

- Render deployment is blocked at Blueprint creation. The authenticated CLI
  can validate Blueprints but cannot create them, and Render's validation API
  currently returns a Cloudflare 403 from this machine. The official flow
  therefore requires **Dashboard > New > Blueprint** in the already-confirmed
  workspace. No resource has been created yet.
- Render needs the existing staging Neon connection string as a masked
  `DATABASE_URL`; it must never be committed or pasted into chat.
- Telegram activation later needs a new staging-only bot token and a webhook
  secret of at least 16 characters. Neither is required for initial deployment.
- No paid Render service, Render cron, worker, database, KV, trial, or payment
  action is authorized by the free staging runbook.
