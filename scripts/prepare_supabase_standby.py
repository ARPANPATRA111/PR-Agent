"""Prepare an empty Supabase Postgres project as a PR-Agent standby.

This script intentionally performs a schema-only preparation. It never reads
from the active database and it never copies user data. Alembic remains the
single migration authority for the application schema.

Required environment variable:

    SUPABASE_DATABASE_URL=<direct or session-pooler Postgres URL>

Run without ``--apply`` for a safety preflight. Run with ``--apply`` only after
checking that the sanitized target printed by the preflight is correct.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.sql.compiler import IdentifierPreparer
from sqlalchemy.dialects import postgresql

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
IGNORED_EMPTY_SCHEMA_TABLES = {"spatial_ref_sys"}
EXPECTED_OWNER_TABLE = "app_users"


def normalized_url(value: str) -> str:
    return value.strip().replace("postgres://", "postgresql://", 1)


def sanitized_target(value: str) -> str:
    parsed = urlsplit(value)
    port = parsed.port or 5432
    return f"{parsed.hostname}:{port}{parsed.path or '/'}"


def validate_target(value: str) -> str:
    target = normalized_url(value)
    parsed = urlsplit(target)
    if parsed.scheme not in {"postgresql", "postgresql+psycopg2"}:
        raise RuntimeError("SUPABASE_DATABASE_URL must be a PostgreSQL URL.")
    hostname = (parsed.hostname or "").lower()
    if not (
        hostname.endswith(".supabase.co") or hostname.endswith(".pooler.supabase.com")
    ):
        raise RuntimeError(
            "Refusing target: hostname is not a Supabase database or pooler."
        )
    if parsed.port == 6543:
        raise RuntimeError(
            "Use the direct connection or session pooler on port 5432 for "
            "migrations; transaction pooling on port 6543 is not supported."
        )
    active = os.environ.get("DATABASE_URL", "").strip()
    if active and normalized_url(active) == target:
        raise RuntimeError(
            "Refusing target: SUPABASE_DATABASE_URL equals active DATABASE_URL."
        )
    return target


def current_public_tables(target: str) -> set[str]:
    engine = create_engine(target, pool_pre_ping=True)
    try:
        return set(inspect(engine).get_table_names(schema="public"))
    finally:
        engine.dispose()


def alembic_upgrade(target: str) -> None:
    environment = os.environ.copy()
    environment.update(
        {
            "APP_ENV": "development",
            "DEBUG": "false",
            "DATABASE_URL": target,
        }
    )
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND,
        env=environment,
        check=True,
    )


def harden_supabase_public_schema(target: str) -> None:
    """Keep the Supabase Data API away from application-owned tables.

    PR-Agent authenticates with Telegram and accesses Postgres through its
    trusted backend. It does not use Supabase Auth or expose PostgREST. Supabase
    projects include ``anon`` and ``authenticated`` roles, so their existing
    and default privileges are explicitly removed.
    """

    statements = (
        "REVOKE ALL ON SCHEMA public FROM anon, authenticated",
        "REVOKE ALL ON ALL TABLES IN SCHEMA public FROM anon, authenticated",
        "REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM anon, authenticated",
        "REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM anon, authenticated",
        (
            "ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public "
            "REVOKE ALL ON TABLES FROM anon, authenticated"
        ),
        (
            "ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public "
            "REVOKE ALL ON SEQUENCES FROM anon, authenticated"
        ),
        (
            "ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public "
            "REVOKE ALL ON FUNCTIONS FROM anon, authenticated"
        ),
    )
    engine = create_engine(target, pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            roles = {
                row[0]
                for row in connection.execute(
                    text(
                        "SELECT rolname FROM pg_roles "
                        "WHERE rolname IN ('anon', 'authenticated')"
                    )
                )
            }
            if roles != {"anon", "authenticated"}:
                raise RuntimeError(
                    "Supabase API roles were not found; target identity is unexpected."
                )
            for statement in statements:
                connection.execute(text(statement))
    finally:
        engine.dispose()


def enable_pg_cron_without_jobs(target: str) -> None:
    """Enable the scheduler extension but never create a keep-alive job."""
    engine = create_engine(target, pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS pg_cron"))
            job_count = connection.execute(
                text("SELECT COUNT(*) FROM cron.job")
            ).scalar_one()
            if int(job_count) != 0:
                raise RuntimeError(
                    "Supabase cron contains jobs; expected a clean scheduler configuration."
                )
    finally:
        engine.dispose()


def verify_standby(target: str) -> tuple[str, int, dict[str, int], bool, int]:
    engine = create_engine(target, pool_pre_ping=True)
    try:
        tables = set(inspect(engine).get_table_names(schema="public"))
        if "alembic_version" not in tables or EXPECTED_OWNER_TABLE not in tables:
            raise RuntimeError("Standby is missing the migrated application schema.")
        with engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            preparer = IdentifierPreparer(postgresql.dialect())
            nonempty_tables: dict[str, int] = {}
            for table_name in sorted(tables - {"alembic_version"}):
                quoted = preparer.quote(table_name)
                count = int(
                    connection.execute(
                        text(f"SELECT COUNT(*) FROM public.{quoted}")
                    ).scalar_one()
                )
                if count:
                    nonempty_tables[table_name] = count
            cron_enabled = bool(
                connection.execute(
                    text(
                        "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname='pg_cron')"
                    )
                ).scalar_one()
            )
            cron_jobs = connection.execute(
                text("SELECT COUNT(*) FROM cron.job")
            ).scalar_one()
        return str(revision), len(tables), nonempty_tables, cron_enabled, int(cron_jobs)
    finally:
        engine.dispose()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare an empty, hardened Supabase standby database."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply Alembic migrations and Supabase role hardening.",
    )
    parser.add_argument(
        "--allow-existing",
        action="store_true",
        help="Allow a resumed run when application tables already exist.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    raw_target = os.environ.get("SUPABASE_DATABASE_URL", "")
    if not raw_target:
        raise RuntimeError("SUPABASE_DATABASE_URL is required.")
    target = validate_target(raw_target)
    print(f"Supabase target: {sanitized_target(target)}")
    print("Migration mode: schema only; no source database will be read.")

    tables = current_public_tables(target)
    unexpected = tables - IGNORED_EMPTY_SCHEMA_TABLES
    if unexpected and not args.allow_existing:
        names = ", ".join(sorted(unexpected))
        raise RuntimeError(
            f"Target public schema is not empty ({names}). "
            "Use --allow-existing only to resume a reviewed preparation."
        )
    if not args.apply:
        print("Preflight passed. Re-run with --apply to prepare the standby.")
        return 0

    alembic_upgrade(target)
    enable_pg_cron_without_jobs(target)
    harden_supabase_public_schema(target)
    revision, table_count, nonempty_tables, cron_enabled, cron_jobs = verify_standby(
        target
    )
    if nonempty_tables:
        raise RuntimeError(
            "Standby contains application rows even though this workflow copies no data: "
            + ", ".join(f"{name}={count}" for name, count in nonempty_tables.items())
        )
    print(f"Standby ready: revision={revision}, public_tables={table_count}")
    print("Data check: every application table contains 0 rows")
    print(f"Cron check: enabled={cron_enabled}, scheduled_jobs={cron_jobs}")
    print("Supabase Data API roles: access revoked from application tables")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
