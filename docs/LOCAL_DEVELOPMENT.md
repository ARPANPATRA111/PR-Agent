# Local Development

## PostgreSQL development database

The repeatable development database is PostgreSQL 16:

```powershell
docker compose up -d postgres
$env:APP_ENV = "development"
$env:DATABASE_URL = "postgresql://pr_agent:pr_agent_local@localhost:5434/pr_agent_dev"
$env:DEBUG = "false"
Set-Location backend
python -m alembic upgrade head
python -m uvicorn main:app --reload
```

In a second terminal:

```powershell
Set-Location frontend
corepack enable
pnpm install --frozen-lockfile
$env:NEXT_PUBLIC_API_URL = "http://localhost:8000"
pnpm dev
```

Telegram Mini App authentication needs signed `initData`; a normal copied
browser URL intentionally cannot authenticate. Backend tests generate signed
test payloads without contacting Telegram.

## Isolated test database

```powershell
docker compose --profile test up -d postgres_test
$env:APP_ENV = "test"
$env:DATABASE_URL = "postgresql://unused:unused@localhost:5432/not_used"
$env:TEST_DATABASE_URL = "postgresql://pr_agent_test:pr_agent_test_local@localhost:5433/pr_agent_test"
Set-Location backend
python -m alembic upgrade head
pytest -q
```

Local unit tests may also use their temporary SQLite fixtures. PostgreSQL
migration and precision checks are mandatory before a phase or release passes.

## Stop services

```powershell
docker compose --profile test stop postgres postgres_test
```

Do not use `docker compose down -v` unless intentionally deleting the local
development database volume. The test database uses `tmpfs` and is disposable.
