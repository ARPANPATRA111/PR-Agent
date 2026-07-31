# Invite-only beta release checklist

This checklist maps the mandatory release gates to repeatable evidence. “Code
verified” does not authorize production deployment. External gates must be
completed in the isolated staging environment for the exact candidate commit.

| # | Gate | Evidence | Status |
|---:|---|---|---|
| 1–5 | Cross-tenant reads, edits, and deletes fail for work, notes, ledger, nutrition, and all record types | `test_domain_services.py`, `test_public_v2_api.py`, `test_bounded_assistant.py`, browser test | Code verified |
| 6–7 | Forged and expired Telegram Mini App data fail | `test_security_boundary.py` | Code verified |
| 8–9 | Missing and invalid webhook secret fail | `test_security_boundary.py` | Code verified |
| 10–13 | Duplicate update, expense, food, and reminder create once | persisted update receipt plus domain/assistant idempotency tests | Code verified |
| 14–15 | Two workers send once; restart recovers pending reminders | `test_durable_worker.py` | Code verified |
| 16–18 | AI outage leaves commands working; nutrition outage is safe; invalid model JSON cannot write | `test_telegram_crud.py`, `test_nutrition.py`, `test_bounded_assistant.py` | Code verified |
| 19–20 | Ten INR 0.10 entries equal INR 1.00; currencies stay separate | `test_domain_services.py`, PostgreSQL schema tests | Code verified |
| 21–22 | Food edit/delete recalculates meal and day totals | `test_nutrition.py`, browser test | Code verified |
| 23–24 | Deletion clears search/agent copies and live summaries | `test_privacy.py`, `test_bounded_assistant.py`, deterministic aggregate tests | Code verified |
| 25 | Telegram deletion failure cannot roll back data | `test_privacy.py` | Code verified |
| 26 | Export is tenant-only | `test_privacy.py`, `test_public_v2_api.py` | Code verified |
| 27–28 | Account deletion stops reminders and revokes sessions | `test_privacy.py`, `test_security_boundary.py` | Code verified |
| 29 | Staging and production credentials are distinct | Compare platform secret identifiers without exposing values | External blocker |
| 30 | Backup restoration works | Perform and record isolated restore per `BACKUP_AND_RESTORE.md` | External blocker |
| 31–34 | Frontend build, backend, frontend, and browser suites pass | CI and local release transcript | Code verified |
| 35–36 | Clean and representative upgraded migrations pass | PostgreSQL upgrade/check/downgrade/re-upgrade and schema tests | Code verified |
| 37 | No live credentials are tracked | gitleaks plus dependency audits | Code verified |
| 38 | No personal historical progress data is in the public product | personal examples/import prompt removed; tracked-file review | Code verified |
| 39 | LinkedIn/report generation is absent from public mode | public-v2 legacy-route 404 regression test; legacy scheduler disabled | Code verified |
| 40 | No hidden reasoning is public | strict proposal schema and retired legacy agent endpoints | Code verified |

Before invitations are sent, also verify `/ready`, worker heartbeat, due-job
lag, failed deliveries, authentication rejection, duplicate update, provider
failure, export failure, and deletion failure monitoring. Begin with 10–30
trusted users. Do not open unrestricted access until beta findings are fixed.
