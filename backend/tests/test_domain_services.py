from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from domain.errors import ConcurrentUpdate, DomainError, RecordNotFound
from domain.schemas import (
    GoalCreate,
    GoalUpdate,
    LedgerCreate,
    LedgerUpdate,
    NoteCreate,
    NoteUpdate,
    ReminderCreate,
    ReminderUpdate,
    WorkLogCreate,
    WorkLogUpdate,
)
from domain.services import DomainServices, local_datetime_to_utc
from public_models import PublicBase


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, connection_record):
        del connection_record
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    PublicBase.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()


@pytest.fixture()
def services(session_factory):
    session = session_factory()
    service = DomainServices(session)
    owner_a = service.ensure_owner(
        telegram_id=1001,
        first_name="A",
        username="owner_a",
    )
    owner_b = service.ensure_owner(
        telegram_id=2002,
        first_name="B",
        username="owner_b",
    )
    session.commit()
    try:
        yield service, owner_a.id, owner_b.id
    finally:
        session.close()


def test_work_log_crud_filters_aggregation_and_idempotency(services):
    service, owner_a, owner_b = services
    payload = WorkLogCreate(
        original_text="Completed the authentication module",
        category="Coding",
        tags=["Backend", "backend"],
        logged_at_local=datetime(2026, 7, 31, 9, 30),
        timezone="Asia/Kolkata",
        idempotency_key="telegram:101",
    )
    created = service.create_work_log(owner_a, payload)
    duplicate = service.create_work_log(owner_a, payload)
    service.session.commit()

    assert duplicate.id == created.id
    assert created.tags == ["backend"]
    assert created.logged_at_utc.replace(tzinfo=timezone.utc) == datetime(
        2026, 7, 31, 4, 0, tzinfo=timezone.utc
    )
    assert service.get_work_log(owner_a, created.id).id == created.id
    assert (
        service.list_work_logs(
            owner_a,
            start_date=date(2026, 7, 31),
            end_date=date(2026, 7, 31),
            tag="backend",
        )[0].id
        == created.id
    )
    aggregate = service.aggregate_work_logs(
        owner_a, date(2026, 7, 28), date(2026, 8, 3)
    )
    assert aggregate["total"] == 1
    assert aggregate["daily"] == {"2026-07-31": 1}

    updated = service.update_work_log(
        owner_a,
        created.id,
        WorkLogUpdate(version=1, original_text="Completed secure CRUD"),
    )
    assert updated.version == 2
    assert updated.original_text == "Completed secure CRUD"

    with pytest.raises(RecordNotFound):
        service.get_work_log(owner_b, created.id)
    with pytest.raises(RecordNotFound):
        service.update_work_log(
            owner_b,
            created.id,
            WorkLogUpdate(version=2, original_text="stolen"),
        )
    with pytest.raises(RecordNotFound):
        service.delete_work_log(owner_b, created.id)

    service.delete_work_log(owner_a, created.id)
    with pytest.raises(RecordNotFound):
        service.delete_work_log(owner_a, created.id)


def test_note_crud_search_pin_and_cross_user_isolation(services):
    service, owner_a, owner_b = services
    note = service.create_note(
        owner_a,
        NoteCreate(
            body="Read about PostgreSQL composite indexes",
            tags=["database"],
            idempotency_key="telegram:note:1",
        ),
    )
    assert note.title.startswith("Read about")
    assert service.list_notes(owner_a, search="composite")[0].id == note.id
    assert service.list_notes(owner_a, tag="database")[0].id == note.id

    pinned = service.update_note(owner_a, note.id, NoteUpdate(version=1, pinned=True))
    assert pinned.pinned is True
    assert service.list_notes(owner_a, pinned=True)[0].id == note.id
    with pytest.raises(RecordNotFound):
        service.get_note(owner_b, note.id)
    service.delete_note(owner_a, note.id)


def test_ledger_precision_validation_filters_and_currency_separation(services):
    service, owner_a, _ = services
    expense = service.create_ledger_entry(
        owner_a,
        LedgerCreate(
            direction="expense",
            amount=Decimal("125.50"),
            currency="inr",
            category="Food",
            description="Dinner",
            idempotency_key="ledger-key-1",
        ),
    )
    income = service.create_ledger_entry(
        owner_a,
        LedgerCreate(
            direction="income",
            amount=Decimal("10.25"),
            currency="USD",
            description="Refund",
        ),
    )
    assert expense.amount_minor == 12550
    assert income.amount_minor == 1025
    assert (
        service.list_ledger_entries(owner_a, category="food", direction="expense")[0].id
        == expense.id
    )
    totals = service.summarize_ledger(owner_a)
    assert totals == [
        {"currency": "INR", "expense_minor": 12550, "income_minor": 0},
        {"currency": "USD", "expense_minor": 0, "income_minor": 1025},
    ]

    updated = service.update_ledger_entry(
        owner_a,
        expense.id,
        LedgerUpdate(version=1, amount=Decimal("130.00")),
    )
    assert updated.amount_minor == 13000
    service.delete_ledger_entry(owner_a, income.id)
    assert service.summarize_ledger(owner_a) == [
        {"currency": "INR", "expense_minor": 13000, "income_minor": 0}
    ]

    for amount in ("0", "-1", "999999999999999999999999"):
        with pytest.raises(ValidationError):
            LedgerCreate(
                direction="expense",
                amount=Decimal(amount),
                currency="INR",
                description="invalid",
            )
    with pytest.raises(ValidationError):
        LedgerCreate(
            direction="expense",
            amount=Decimal("1"),
            currency="ZZZ",
            description="invalid currency",
        )
    with pytest.raises(ValidationError):
        LedgerCreate(
            direction="expense",
            amount=Decimal("1.10"),
            currency="JPY",
            description="invalid precision",
        )


def test_goal_crud_progress_status_and_dates(services):
    service, owner_a, _ = services
    goal = service.create_goal(
        owner_a,
        GoalCreate(
            title="Complete 100 Java DSA questions",
            target_value=100,
            unit="questions",
            start_date=date(2026, 7, 1),
            due_date=date(2026, 8, 31),
        ),
    )
    progressed = service.update_goal(
        owner_a,
        goal.id,
        GoalUpdate(version=1, current_value=25),
    )
    paused = service.update_goal(
        owner_a,
        goal.id,
        GoalUpdate(version=progressed.version, status="paused"),
    )
    completed = service.update_goal(
        owner_a,
        goal.id,
        GoalUpdate(version=paused.version, status="completed"),
    )
    assert completed.status == "completed"
    assert service.list_goals(owner_a, status="completed")[0].id == goal.id
    service.delete_goal(owner_a, goal.id)

    with pytest.raises(ValidationError):
        GoalCreate(
            title="bad dates",
            start_date=date(2026, 8, 1),
            due_date=date(2026, 7, 1),
        )


def test_reminder_crud_pause_resume_and_recurrence(services):
    service, owner_a, _ = services
    future = datetime.now(timezone.utc) + timedelta(days=2)
    reminder = service.create_reminder(
        owner_a,
        ReminderCreate(
            title="Review the week",
            schedule_type="weekly",
            start_at_local=future,
            timezone="UTC",
            weekday=future.weekday(),
            idempotency_key="reminder-key-1",
        ),
    )
    assert reminder.recurrence_rule["frequency"] == "weekly"
    paused = service.update_reminder(
        owner_a,
        reminder.id,
        ReminderUpdate(version=1, enabled=False),
    )
    resumed = service.update_reminder(
        owner_a,
        reminder.id,
        ReminderUpdate(version=paused.version, enabled=True),
    )
    assert resumed.enabled is True
    assert service.list_reminders(owner_a, enabled=True)[0].id == reminder.id
    service.delete_reminder(owner_a, reminder.id)

    with pytest.raises(DomainError):
        service.create_reminder(
            owner_a,
            ReminderCreate(
                title="Past reminder",
                schedule_type="once",
                start_at_local=datetime.now(timezone.utc) - timedelta(days=1),
                timezone="UTC",
            ),
        )


def test_strict_lengths_owner_override_and_timezone_transitions():
    with pytest.raises(ValidationError):
        NoteCreate(body="x" * 10_001)
    with pytest.raises(ValidationError):
        NoteCreate.model_validate({"body": "hello", "owner_id": 999})
    with pytest.raises(ValidationError):
        WorkLogCreate(original_text="ok", timezone="Mars/Olympus")

    converted = local_datetime_to_utc(
        datetime(2026, 7, 31, 9, 30),
        "Asia/Kolkata",
    )
    assert converted == datetime(2026, 7, 31, 4, 0, tzinfo=timezone.utc)
    with pytest.raises(DomainError):
        local_datetime_to_utc(
            datetime(2026, 3, 8, 2, 30),
            "America/New_York",
        )


def test_optimistic_concurrency_rejects_stale_update(session_factory):
    initial_session = session_factory()
    initial = DomainServices(initial_session)
    owner = initial.ensure_owner(telegram_id=8080, first_name="Concurrent")
    note = initial.create_note(owner.id, NoteCreate(body="original"))
    initial_session.commit()
    initial_session.close()

    session_one = session_factory()
    session_two = session_factory()
    service_one = DomainServices(session_one)
    service_two = DomainServices(session_two)
    service_one.get_note(owner.id, note.id)
    service_two.get_note(owner.id, note.id)

    service_one.update_note(owner.id, note.id, NoteUpdate(version=1, body="first"))
    session_one.commit()
    with pytest.raises(ConcurrentUpdate):
        service_two.update_note(owner.id, note.id, NoteUpdate(version=1, body="stale"))
    session_two.rollback()
    session_one.close()
    session_two.close()
