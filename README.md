# PR-Agent Public Edition

PR-Agent is a multi-user Telegram bot and Mini App for privately tracking work,
notes, reminders, money, goals, and nutrition. The public-v2 architecture uses
Telegram identity, strict tenant isolation, PostgreSQL, and editable records.

The legacy LinkedIn/progress-report workflow is intentionally retired from the
public product. Users receive concise summaries of their own data; the bot does
not create public posts or progress-report artifacts.

## Current public-v2 capabilities

- Telegram HMAC authentication with secure, HTTP-only sessions and CSRF
  protection
- Secret-protected, deduplicated Telegram webhook ingestion
- Tenant-scoped CRUD APIs and Telegram commands
- Work logs, notes, reminders, income/expenses, goals, and nutrition records
- Draft-first nutrition estimates with visible assumptions and manual editing
- Mobile-first Telegram Mini App with light/dark theme support
- Optimistic concurrency, idempotency keys, UTC storage, and minor-unit money
- Additive Alembic migrations that preserve the legacy schema

Production scheduling, exports/account deletion, agent orchestration, and final
deployment hardening are being completed in later public-v2 phases.

## Architecture

```text
Telegram bot / Mini App
          |
          v
FastAPI API + webhook
          |
          +-- deterministic domain services
          |
          +-- PostgreSQL (tenant-owned records)
```

AI is advisory only. Deterministic services own validation, authorization,
money arithmetic, dates, and all writes.

## Local development

Requirements:

- Python 3.11+
- Node.js 20+
- pnpm
- Docker with Compose

Copy the environment template and use local-only values:

```powershell
Copy-Item .env.example .env
docker compose up --build
```

Run database migrations:

```powershell
Set-Location backend
alembic upgrade head
```

Run the backend directly:

```powershell
Set-Location backend
python -m pip install -r requirements-dev.txt
uvicorn main:app --reload --port 8000
```

Run the Mini App:

```powershell
Set-Location frontend
pnpm install --frozen-lockfile
pnpm dev
```

The Mini App must be opened by Telegram in normal use. It intentionally does
not accept a typed Telegram ID or dashboard password.

## Validation

```powershell
Set-Location backend
pytest

Set-Location ..\frontend
pnpm typecheck
pnpm lint
pnpm test
pnpm test:e2e
pnpm build
```

PostgreSQL integration tests use the development Compose stack described in
[Local development](docs/LOCAL_DEVELOPMENT.md).

## Documentation

- [Public-v2 scope](docs/PUBLIC_V2_SCOPE.md)
- [Security model](docs/SECURITY_MODEL.md)
- [Tenant isolation](docs/TENANT_ISOLATION.md)
- [Database migrations](docs/DATABASE_MIGRATIONS.md)
- [Core CRUD](docs/CORE_CRUD.md)
- [Nutrition](docs/NUTRITION.md)
- [Mini App](docs/MINI_APP.md)
- [Deployment](DEPLOYMENT.md)
- [Secret rotation checklist](docs/SECRET_ROTATION_CHECKLIST.md)

## Security

Never commit `.env` files, tokens, database URLs, session secrets, or user
exports. Rotate any credential that may have appeared in source control before
deploying. Report suspected vulnerabilities privately to the repository owner;
do not include secrets or personal data in a public issue.

## License

MIT
