"""Migration and public schema validation."""

import os
import subprocess
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from config import Settings
from public_models import (
    LedgerEntry,
    NutritionItem,
    NutritionLog,
    PublicUser,
    WorkerHeartbeat,
)

BACKEND_DIR = Path(__file__).resolve().parents[1]
PUBLIC_TABLES = {
    "account_deletion_audits",
    "account_export_requests",
    "agent_actions",
    "agent_pending_actions",
    "agent_runs",
    "api_rate_limit_buckets",
    "app_users",
    "digest_deliveries",
    "invite_codes",
    "ledger_entries",
    "notes",
    "nutrition_items",
    "nutrition_logs",
    "reminder_deliveries",
    "reminders",
    "scheduled_digests",
    "sessions",
    "telegram_messages",
    "telegram_update_receipts",
    "tracked_goals",
    "user_preferences",
    "work_logs",
}


def run_alembic(database_url: str, *arguments: str) -> subprocess.CompletedProcess:
    environment = os.environ.copy()
    environment.update(
        {
            "APP_ENV": "development",
            "DATABASE_URL": database_url,
            "DEBUG": "false",
        }
    )
    return subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=BACKEND_DIR,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def test_empty_database_upgrade_is_idempotent(tmp_path):
    database_url = sqlite_url(tmp_path / "empty.db")
    run_alembic(database_url, "upgrade", "head")
    run_alembic(database_url, "upgrade", "head")
    check = run_alembic(database_url, "check")

    tables = set(inspect(create_engine(database_url)).get_table_names())
    assert PUBLIC_TABLES <= tables
    assert "No new upgrade operations detected" in (check.stdout + check.stderr)


def test_representative_legacy_upgrade_preserves_rows_and_downgrade(tmp_path):
    database_url = sqlite_url(tmp_path / "legacy.db")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("""
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY,
                    telegram_id INTEGER NOT NULL UNIQUE,
                    username VARCHAR(255),
                    first_name VARCHAR(255) NOT NULL,
                    last_name VARCHAR(255),
                    created_at DATETIME,
                    last_active DATETIME,
                    streak INTEGER,
                    total_entries INTEGER,
                    preferences JSON
                )
                """))
        connection.execute(text("""
                CREATE TABLE raw_entries (
                    id INTEGER PRIMARY KEY,
                    telegram_id INTEGER NOT NULL,
                    telegram_message_id INTEGER NOT NULL,
                    timestamp DATETIME,
                    audio_file_id VARCHAR(255),
                    audio_duration INTEGER,
                    transcript TEXT
                )
                """))
        connection.execute(text("""
                INSERT INTO users (
                    id, telegram_id, first_name, streak, total_entries,
                    preferences
                ) VALUES (1, 101, 'Legacy', 3, 7, '{}')
                """))

    run_alembic(database_url, "upgrade", "head")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM users")).scalar_one() == 1
        assert "raw_entries" in inspect(connection).get_table_names()

    run_alembic(database_url, "downgrade", "base")
    remaining = set(inspect(engine).get_table_names())
    assert "users" in remaining
    assert "raw_entries" in remaining
    assert not PUBLIC_TABLES & remaining


@pytest.fixture
def migrated_engine(tmp_path):
    database_url = sqlite_url(tmp_path / "constraints.db")
    run_alembic(database_url, "upgrade", "head")
    engine = create_engine(database_url)

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def test_unique_foreign_keys_precision_timezone_and_indexes(migrated_engine):
    logged_at = datetime(2026, 7, 31, 5, 30, tzinfo=timezone.utc)
    with Session(migrated_engine) as session:
        owner = PublicUser(
            telegram_id=101,
            first_name="Alice",
        )
        session.add(owner)
        session.flush()
        session.add(
            LedgerEntry(
                owner_id=owner.id,
                direction="expense",
                amount_minor=12550,
                currency="INR",
                description="Dinner",
                transaction_at_utc=logged_at,
                user_local_date=date(2026, 7, 31),
                timezone="Asia/Kolkata",
                capture_source="test",
                idempotency_key="ledger-1",
            )
        )
        nutrition = NutritionLog(
            owner_id=owner.id,
            logged_at_utc=logged_at,
            user_local_date=date(2026, 7, 31),
            timezone="Asia/Kolkata",
            original_text="50 g paneer",
            total_calories=Decimal("132.50"),
            total_protein_grams=Decimal("9.375"),
            estimation_source="test",
            overall_confidence=Decimal("0.8750"),
            idempotency_key="nutrition-1",
        )
        nutrition.items.append(
            NutritionItem(
                owner_id=owner.id,
                original_item_text="50 g paneer",
                normalized_name="paneer",
                quantity_value=Decimal("50.000"),
                quantity_unit="g",
                calories=Decimal("132.50"),
                protein_grams=Decimal("9.375"),
                estimation_source="test",
                confidence=Decimal("0.8750"),
            )
        )
        session.add(nutrition)
        session.commit()

        stored_ledger = session.query(LedgerEntry).one()
        stored_nutrition = session.query(NutritionLog).one()
        assert stored_ledger.amount_minor == 12550
        assert stored_ledger.timezone == "Asia/Kolkata"
        assert stored_nutrition.total_calories == Decimal("132.50")
        assert stored_nutrition.total_protein_grams == Decimal("9.375")
        assert stored_nutrition.items[0].confidence == Decimal("0.8750")

        session.add(
            LedgerEntry(
                owner_id=owner.id,
                direction="expense",
                amount_minor=1,
                currency="INR",
                description="Duplicate",
                transaction_at_utc=logged_at,
                user_local_date=date(2026, 7, 31),
                timezone="Asia/Kolkata",
                capture_source="test",
                idempotency_key="ledger-1",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        session.add(
            LedgerEntry(
                owner_id=999999,
                direction="expense",
                amount_minor=1,
                currency="INR",
                description="No owner",
                transaction_at_utc=logged_at,
                user_local_date=date(2026, 7, 31),
                timezone="UTC",
                capture_source="test",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()

    inspector = inspect(migrated_engine)
    for table_name in (
        "work_logs",
        "notes",
        "reminders",
        "ledger_entries",
        "nutrition_logs",
        "tracked_goals",
    ):
        indexes = inspector.get_indexes(table_name)
        assert any(
            index["column_names"] and index["column_names"][0] == "owner_id"
            for index in indexes
        ), table_name


def test_worker_heartbeat_accepts_stopped_state(migrated_engine):
    with Session(migrated_engine) as session:
        session.add(
            WorkerHeartbeat(
                worker_name="test-worker",
                instance_id="test-instance",
                status="stopped",
            )
        )
        session.commit()


def test_test_and_application_databases_must_differ():
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            app_env="test",
            database_url="postgresql://example/app",
            test_database_url="postgresql://example/app",
        )


def test_production_agent_fails_closed_without_provider_credentials():
    with pytest.raises(ValidationError, match="AI_PROVIDER"):
        Settings(
            _env_file=None,
            app_env="production",
            app_base_url="https://api.example.test",
            frontend_base_url="https://app.example.test",
            database_url="postgresql://service:password@db.example.test/app",
            session_signing_secret="s" * 64,
            telegram_bot_token="123456:production-test-token",
            telegram_webhook_secret="w" * 32,
            telegram_webhook_url="https://api.example.test/webhook",
            telegram_mini_app_url="https://app.example.test",
            cors_origins="https://app.example.test",
            ai_agent_enabled=True,
            ai_provider="disabled",
        )


def test_production_rejects_debug_mode():
    with pytest.raises(ValidationError, match="DEBUG must be false"):
        Settings(
            _env_file=None,
            app_env="production",
            app_base_url="https://api.example.test",
            frontend_base_url="https://app.example.test",
            database_url="postgresql://service:password@db.example.test/app",
            session_signing_secret="s" * 64,
            telegram_bot_token="123456:production-test-token",
            telegram_webhook_secret="w" * 32,
            telegram_webhook_url="https://api.example.test/webhook",
            telegram_mini_app_url="https://app.example.test",
            cors_origins="https://app.example.test",
            debug=True,
        )


def test_backfill_is_dry_run_first_and_idempotent(tmp_path):
    database_url = sqlite_url(tmp_path / "backfill.db")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("""
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY,
                    telegram_id INTEGER NOT NULL UNIQUE,
                    username VARCHAR(255),
                    first_name VARCHAR(255) NOT NULL,
                    last_name VARCHAR(255),
                    created_at DATETIME,
                    last_active DATETIME,
                    streak INTEGER,
                    total_entries INTEGER,
                    preferences JSON
                )
                """))
        connection.execute(text("""
                CREATE TABLE raw_entries (
                    id INTEGER PRIMARY KEY,
                    telegram_id INTEGER NOT NULL,
                    telegram_message_id INTEGER NOT NULL,
                    timestamp DATETIME NOT NULL,
                    audio_file_id VARCHAR(255),
                    audio_duration INTEGER,
                    transcript TEXT
                )
                """))
        connection.execute(text("""
                INSERT INTO users (
                    id, telegram_id, first_name, preferences
                ) VALUES (
                    1, 101, 'Legacy', '{"timezone": "Asia/Kolkata"}'
                )
                """))
        connection.execute(text("""
                INSERT INTO raw_entries (
                    id, telegram_id, telegram_message_id, timestamp,
                    audio_file_id, audio_duration, transcript
                ) VALUES (
                    7, 101, 99, '2026-07-31 05:30:00',
                    'legacy-file', 12, 'Completed migration tests'
                )
                """))

    run_alembic(database_url, "upgrade", "head")
    environment = os.environ.copy()
    environment.update(
        {
            "APP_ENV": "development",
            "DATABASE_URL": database_url,
            "DEBUG": "false",
        }
    )
    command = [
        sys.executable,
        str(BACKEND_DIR.parent / "scripts" / "backfill_legacy_to_public_v2.py"),
    ]
    dry_run = subprocess.run(
        command,
        cwd=BACKEND_DIR,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "DRY RUN (rolled back)" in dry_run.stdout
    with engine.connect() as connection:
        assert (
            connection.execute(text("SELECT COUNT(*) FROM app_users")).scalar_one() == 0
        )
        assert (
            connection.execute(text("SELECT COUNT(*) FROM work_logs")).scalar_one() == 0
        )

    first_apply = subprocess.run(
        [*command, "--apply"],
        cwd=BACKEND_DIR,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    second_apply = subprocess.run(
        [*command, "--apply"],
        cwd=BACKEND_DIR,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "work_logs_created: 1" in first_apply.stdout
    assert "sample: raw_entries:7 -> work_logs:new" in first_apply.stdout
    assert "work_logs_created: 0" in second_apply.stdout
    assert "work_logs_existing: 1" in second_apply.stdout
    with engine.connect() as connection:
        assert (
            connection.execute(text("SELECT COUNT(*) FROM app_users")).scalar_one() == 1
        )
        assert (
            connection.execute(text("SELECT COUNT(*) FROM work_logs")).scalar_one() == 1
        )
