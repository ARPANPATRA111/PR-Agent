"""PostgreSQL-only schema semantics."""

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from domain.schemas import ReminderCreate
from domain.services import DomainServices
from durable_worker import DurableDeliveryStore
from public_models import Reminder, ReminderDelivery

POSTGRES_TEST_URL = os.getenv("POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(
    not POSTGRES_TEST_URL,
    reason="POSTGRES_TEST_URL is required for PostgreSQL integration tests",
)


def test_00_postgres_legacy_upgrade_preserves_rows():
    backend_dir = Path(__file__).resolve().parents[1]
    subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "base"],
        cwd=backend_dir,
        check=True,
        capture_output=True,
        text=True,
    )
    engine = create_engine(POSTGRES_TEST_URL, pool_pre_ping=True)
    with engine.begin() as connection:
        connection.execute(text("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    telegram_id BIGINT NOT NULL UNIQUE,
                    username VARCHAR(255),
                    first_name VARCHAR(255) NOT NULL,
                    last_name VARCHAR(255),
                    created_at TIMESTAMP,
                    last_active TIMESTAMP,
                    streak INTEGER,
                    total_entries INTEGER,
                    preferences JSON
                )
                """))
        connection.execute(text("""
                CREATE TABLE IF NOT EXISTS raw_entries (
                    id SERIAL PRIMARY KEY,
                    telegram_id BIGINT NOT NULL,
                    telegram_message_id BIGINT NOT NULL,
                    timestamp TIMESTAMP,
                    audio_file_id VARCHAR(255),
                    audio_duration INTEGER,
                    transcript TEXT
                )
                """))
        connection.execute(text("DELETE FROM users WHERE telegram_id = 123456789"))
        connection.execute(text("""
                INSERT INTO users (telegram_id, first_name, preferences)
                VALUES (123456789, 'Legacy', '{}')
                """))

    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=backend_dir,
        check=True,
        capture_output=True,
        text=True,
    )
    with engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT COUNT(*) FROM users WHERE telegram_id = 123456789")
            ).scalar_one()
            == 1
        )
        assert {"users", "raw_entries", "app_users"} <= set(
            inspect(connection).get_table_names()
        )


def test_postgres_precision_timezone_constraints_and_indexes():
    engine = create_engine(POSTGRES_TEST_URL, pool_pre_ping=True)
    telegram_id = 9_876_543_210
    logged_at = datetime(2026, 7, 31, 5, 30, tzinfo=timezone.utc)

    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM app_users WHERE telegram_id = :telegram_id"),
            {"telegram_id": telegram_id},
        )
        owner_id = connection.execute(
            text("""
                INSERT INTO app_users (telegram_id, first_name)
                VALUES (:telegram_id, 'Migration Test')
                RETURNING id
                """),
            {"telegram_id": telegram_id},
        ).scalar_one()
        connection.execute(
            text("""
                INSERT INTO ledger_entries (
                    owner_id, direction, amount_minor, currency, description,
                    transaction_at_utc, user_local_date, timezone,
                    capture_source, idempotency_key
                ) VALUES (
                    :owner_id, 'expense', 12550, 'INR', 'Dinner',
                    :logged_at, DATE '2026-07-31', 'Asia/Kolkata',
                    'test', 'postgres-ledger-1'
                )
                """),
            {"owner_id": owner_id, "logged_at": logged_at},
        )
        nutrition_id = connection.execute(
            text("""
                INSERT INTO nutrition_logs (
                    owner_id, logged_at_utc, user_local_date, timezone,
                    original_text, total_calories, total_protein_grams,
                    estimation_source, overall_confidence
                ) VALUES (
                    :owner_id, :logged_at, DATE '2026-07-31', 'Asia/Kolkata',
                    '50 g paneer', 132.50, 9.375, 'test', 0.8750
                )
                RETURNING id
                """),
            {"owner_id": owner_id, "logged_at": logged_at},
        ).scalar_one()
        connection.execute(
            text("""
                INSERT INTO nutrition_items (
                    nutrition_log_id, owner_id, original_item_text,
                    normalized_name, quantity_value, quantity_unit, calories,
                    protein_grams, estimation_source, confidence
                ) VALUES (
                    :nutrition_id, :owner_id, '50 g paneer', 'paneer',
                    50.000, 'g', 132.50, 9.375, 'test', 0.8750
                )
                """),
            {"nutrition_id": nutrition_id, "owner_id": owner_id},
        )

        row = connection.execute(
            text("""
                SELECT total_calories, total_protein_grams, logged_at_utc,
                       timezone
                FROM nutrition_logs
                WHERE id = :nutrition_id
                """),
            {"nutrition_id": nutrition_id},
        ).one()
        assert row.total_calories == Decimal("132.50")
        assert row.total_protein_grams == Decimal("9.375")
        assert row.logged_at_utc.tzinfo is not None
        assert row.logged_at_utc.astimezone(timezone.utc) == logged_at
        assert row.timezone == "Asia/Kolkata"

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text("""
                    INSERT INTO ledger_entries (
                        owner_id, direction, amount_minor, currency,
                        description, transaction_at_utc, user_local_date,
                        timezone, capture_source, idempotency_key
                    ) VALUES (
                        :owner_id, 'expense', 1, 'INR', 'Duplicate', NOW(),
                        CURRENT_DATE, 'UTC', 'test', 'postgres-ledger-1'
                    )
                    """),
                {"owner_id": owner_id},
            )

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(text("""
                    INSERT INTO ledger_entries (
                        owner_id, direction, amount_minor, currency,
                        description, transaction_at_utc, user_local_date,
                        timezone, capture_source
                    ) VALUES (
                        -1, 'expense', 1, 'INR', 'No owner', NOW(),
                        CURRENT_DATE, 'UTC', 'test'
                    )
                    """))

    inspector = inspect(engine)
    for table_name in (
        "work_logs",
        "notes",
        "reminders",
        "ledger_entries",
        "nutrition_logs",
        "tracked_goals",
    ):
        assert any(
            index["column_names"][0] == "owner_id"
            for index in inspector.get_indexes(table_name)
            if index["column_names"]
        )


def test_two_postgres_workers_claim_one_occurrence():
    engine = create_engine(POSTGRES_TEST_URL, pool_pre_ping=True)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    telegram_id = 9_876_543_211
    now = datetime(2026, 8, 1, 10, tzinfo=timezone.utc)
    with factory() as session:
        session.execute(
            text("DELETE FROM app_users WHERE telegram_id = :telegram_id"),
            {"telegram_id": telegram_id},
        )
        owner = DomainServices(session).ensure_owner(
            telegram_id=telegram_id,
            first_name="Worker Test",
        )
        reminder = DomainServices(session).create_reminder(
            owner.id,
            ReminderCreate(
                title="One delivery",
                schedule_type="once",
                start_at_local=datetime(2026, 8, 2, 10),
                timezone="UTC",
                idempotency_key="postgres-worker-reminder",
            ),
        )
        session.commit()
        reminder.next_run_at_utc = now
        session.commit()
        owner_id = owner.id

    stores = [
        DurableDeliveryStore(factory, batch_size=1),
        DurableDeliveryStore(factory, batch_size=1),
    ]
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda store: store.claim_reminders(now), stores))
    assert sum(len(result) for result in results) == 1

    with factory() as session:
        assert (
            session.query(ReminderDelivery)
            .join(Reminder)
            .filter(Reminder.owner_id == owner_id)
            .count()
            == 1
        )
        owner = DomainServices(session).get_owner_by_telegram_id(telegram_id)
        session.delete(owner)
        session.commit()
    engine.dispose()
