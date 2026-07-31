# Public v2 Baseline Audit

Captured on 2026-07-31 before public-v2 application behavior was changed.
Secret values were not copied into this document.

## Recovery point

- Starting branch: `main`
- Starting commit: `026369114413c2eb82dc748d6bdf7fa513441299`
- Safety tag: `legacy-progress-agent-v1`
- Implementation branch: `public-v2`
- Owner files present but not modified:
  - `Weekly-Progress-Agent.md`
  - `Weekly-Progress-Agent-Interview-QA.md`
- Existing SQLite databases and Chroma data were not opened for content
  inspection, changed, migrated, or deleted.

## Toolchain

- Python: 3.12.0
- Node.js: 24.18.0
- pnpm: 10.11.0
- Git: 2.43.0.windows.1
- Frontend lockfile: `frontend/pnpm-lock.yaml`

The locally present CI file expects npm and `package-lock.json`, so it is not
reproducible against the current pnpm lockfile. This is a known legacy defect.

## Configuration names

The legacy environment exposes these names. Values were deliberately omitted:

```text
AUDIO_TEMP_DIR
BACKUP_DIR
BACKUP_HOUR
CHROMA_PERSIST_DIR
CORS_ORIGINS
CURRENT_WEEK_NUMBER
DAILY_REFLECTION_HOUR
DAILY_REFLECTION_MINUTE
DATABASE_URL
DEBUG
DISABLE_SSL_VERIFY
GITHUB_USERNAME
GROQ_API_KEY
GROQ_MODEL
JSON_LOGS
LINKEDIN_POST_START_YEAR
LLM_TEMPERATURE
LOG_FILE
LOG_LEVEL
MAX_BACKUPS
MORNING_NUDGE_HOUR
MORNING_NUDGE_MINUTE
NEXT_PUBLIC_API_URL
NUDGE_THRESHOLD_HOURS
SECRET_KEY
TELEGRAM_ADMIN_ID
TELEGRAM_BOT_TOKEN
TIMEZONE
WEBHOOK_URL
WEEKLY_SUMMARY_DAY
WEEKLY_SUMMARY_HOUR
WEEKLY_SUMMARY_MINUTE
WHISPER_LANGUAGE
WHISPER_MODEL
```

The local `DEBUG` value is not a valid boolean. Baseline tests therefore used a
process-only `DEBUG=false` override; the local `.env` was not edited.

## Persistence baseline

The legacy application uses SQLAlchemy `create_all` followed by ad-hoc column
checks. Alembic or an equivalent migration system is not configured.

Legacy tables:

- `users`
- `raw_entries`
- `structured_entries`
- `daily_summaries`
- `weekly_summaries`
- `linkedin_posts`
- `nudge_logs`
- `posted_reports`
- `searchable_entries`
- `searchable_posts`
- `goals`
- `report_feedback`

SQLite is the active local design. PostgreSQL connection handling exists, but
the application still relies on runtime schema creation and manual alterations.

## Scheduled work

The in-process APScheduler configures:

- Daily reflection
- Weekly summary and LinkedIn draft generation
- Morning nudge
- Four-hour inactivity analysis
- Evening summary
- Daily random-reminder scheduling

Jobs are process-local. Applying one user's schedule reschedules shared global
job IDs, and multiple web replicas would run duplicate jobs.

## HTTP and authentication baseline

Public Telegram/control routes:

- `POST /webhook`
- `POST /webhook/set`
- `GET /webhook/info`
- `POST /webhook/delete`
- `POST /api/admin/nudge`
- `POST /api/admin/daily-reflection`
- `POST /api/admin/weekly-summary`

The webhook does not validate a Telegram webhook secret and does not persist
`update_id` for replay protection.

JWT helpers and Telegram login-code endpoints exist, but private APIs generally
accept a caller-supplied `telegram_id`. Several post read/update/publish
operations do not scope by owner at all.

The frontend:

- Compares a `NEXT_PUBLIC_DASHBOARD_PASSWORD` in browser code.
- Allows access when that value is absent.
- Stores authentication state in `localStorage`.
- Stores a manually entered Telegram ID in `localStorage`.
- Appends that ID to API requests.

This design is not safe for public access.

## Legacy and personal material

Tracked material that must not appear in the final public product:

- `OldProgress.txt` — personal progress history; removed from public-v2
  tracking while retained locally and in the safety tag.
- `backend/historical_examples.py` — personal LinkedIn examples imported by the
  current report generator.
- `prompts/weekly_report.md` — legacy public-report prompt.
- `scripts/import_historical_posts.py` — personal report import path.
- `frontend/src/app/posted-reports/page.tsx`
- `frontend/src/components/posted-reports/posted-reports-view.tsx`
- LinkedIn/report code in `backend/bot.py`, `backend/main.py`,
  `backend/llm_agent.py`, `backend/memory.py`, `backend/models.py`, and
  `backend/scheduler.py`.
- `main.excalidraw` and older project documentation require review before reuse.

The report-generation code remains present during Phase 0 to avoid changing
legacy runtime behavior. It must be disabled and removed in later gated phases.

Ignored local material identified:

- `.env`
- SQLite, Chroma, log, audio, and backup data
- `.github/workflows/ci.yml`
- `docker-compose.yml`
- `render.yaml`
- `DEPLOYMENT.md`
- Legacy files under `docs/`

Phase 0 changes tracking rules so the public-v2 audit documents and selected
infrastructure templates can be versioned. Legacy local documentation remains
ignored pending content review.

## Security findings

- A redacted workspace scan found live-looking Telegram and Groq credentials in
  the ignored local `.env`. They were not printed or committed.
- The same workspace scan flagged generated Next.js signing material under
  ignored `.next` output. These are generated build artifacts.
- A redacted Git scan checked 22 commits and found no committed leaks.
- No obvious live token pattern was found in tracked files during the earlier
  targeted scan.
- Existing public APIs have authorization gaps and public administrative
  controls.
- CORS is hardcoded rather than consistently derived from validated
  configuration.
- Login codes, rate limits, pending clarification state, and jobs are held in
  process memory.
- Deleting an entry does not remove its searchable copy or invalidate derived
  summaries.
- Hidden-style `thinking` text can be returned by an agent-analysis API.

Credential rotation is mandatory before any staging or production deployment.

## Validation evidence

Commands executed:

```powershell
$env:DEBUG='false'; python -m pytest -q
mypy . --ignore-missing-imports
pnpm install --frozen-lockfile
$env:CI='1'; pnpm run lint
pnpm exec tsc --noEmit
pnpm run build
python -m pip check
python -m pip_audit -r requirements.txt
pnpm audit --prod --audit-level high
gitleaks detect --source . --no-git --redact --no-banner
gitleaks detect --source . --redact --no-banner
```

Results:

- Backend tests: 34 passed, 1 skipped.
- Frontend dependency installation: passed with frozen lockfile.
- Frontend type check: passed.
- Frontend production build: passed; Webpack reported non-fatal Windows cache
  rename warnings.
- Python dependency integrity: passed.
- Python dependency vulnerability audit: no known vulnerabilities found.
- Git-history secret scan: passed; 22 commits scanned, no leaks found.
- Backend mypy: failed with 191 pre-existing errors across 9 files.
- Frontend lint: failed because no ESLint configuration exists and `next lint`
  opens an interactive setup prompt.
- Frontend production dependency audit: failed with 31 advisories
  (2 low, 15 moderate, 14 high, 0 critical).
- Workspace secret scan: failed due to ignored local credentials and generated
  `.next` keys; no finding is being committed.

The test suite and production build establish the recoverable legacy baseline.
Quality-gate and dependency findings are recorded as required remediation, not
misrepresented as passing.

## Phase 0 boundaries

Phase 0 changes repository tracking and documentation only. It does not:

- Contact Telegram.
- Register or delete a webhook.
- Send or delete Telegram messages.
- Contact the deployed Render service.
- Use a production database.
- Change the existing application feature behavior.
- Migrate or delete legacy data.
