import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from domain.schemas import ReminderCreate, ReminderUpdate, WorkLogCreate
from domain.scheduling import next_reminder_occurrence
from domain.services import DomainServices
from durable_worker import (
    DeliveryFailure,
    DurableDeliveryStore,
    DurableWorker,
)
import worker as worker_entrypoint
from public_models import (
    DigestDelivery,
    PublicBase,
    Reminder,
    ReminderDelivery,
    ScheduledDigest,
)

UTC = timezone.utc


def future_clock() -> datetime:
    """Return a stable test clock that remains ahead of wall-clock validation."""
    return datetime.now(UTC).replace(microsecond=0) + timedelta(days=1)


class FakeGateway:
    def __init__(self, outcomes=None):
        self.outcomes = list(outcomes or [])
        self.messages = []

    async def send(self, chat_id, text):
        self.messages.append((chat_id, text))
        outcome = self.outcomes.pop(0) if self.outcomes else 900 + len(self.messages)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FailingNarrator:
    async def narrate(self, snapshot, fallback):
        raise RuntimeError("provider unavailable")


class Clock:
    def __init__(self, value):
        self.value = value

    def __call__(self):
        return self.value


@pytest.fixture()
def delivery_db(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'worker.db'}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    PublicBase.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        service = DomainServices(session)
        owner_a = service.ensure_owner(
            telegram_id=101,
            first_name="Alice",
        )
        owner_b = service.ensure_owner(
            telegram_id=202,
            first_name="Bob",
        )
        session.commit()
        ids = (owner_a.id, owner_b.id)
    yield factory, ids
    engine.dispose()


def create_reminder(factory, owner_id, now, key, schedule_type="once"):
    with factory() as session:
        reminder = DomainServices(session).create_reminder(
            owner_id,
            ReminderCreate(
                title=f"Reminder {key}",
                schedule_type=schedule_type,
                start_at_local=(now + timedelta(days=1)).replace(tzinfo=None),
                timezone="UTC",
                weekday=now.weekday() if schedule_type == "weekly" else None,
                idempotency_key=f"reminder-{key}",
            ),
        )
        session.commit()
        reminder.next_run_at_utc = now - timedelta(seconds=1)
        session.commit()
        return reminder.id


@pytest.mark.asyncio
async def test_disabled_worker_stays_idle(monkeypatch):
    monkeypatch.setattr(worker_entrypoint.settings, "public_v2_enabled", False)
    monkeypatch.setattr(worker_entrypoint.settings, "reminder_worker_enabled", False)
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(worker_entrypoint.main(), timeout=0.01)


def test_claim_lease_prevents_two_workers_and_recovers_after_restart(delivery_db):
    factory, (owner_a, _) = delivery_db
    now = future_clock()
    create_reminder(factory, owner_a, now, "lease")
    first = DurableDeliveryStore(factory, lease_seconds=30)
    second = DurableDeliveryStore(factory, lease_seconds=30)

    first_claim = first.claim_reminders(now)
    assert len(first_claim) == 1
    assert second.claim_reminders(now) == []

    recovered = second.claim_reminders(now + timedelta(seconds=31))
    assert len(recovered) == 1
    assert recovered[0].delivery_id == first_claim[0].delivery_id
    assert recovered[0].attempt_count == 2
    second.mark_reminder_success(recovered[0].delivery_id, now, 555)

    with factory() as session:
        deliveries = session.query(ReminderDelivery).all()
        assert len(deliveries) == 1
        assert deliveries[0].status == "sent"
        assert deliveries[0].telegram_message_id == 555


@pytest.mark.asyncio
async def test_transient_timeout_retries_with_backoff_and_then_succeeds(delivery_db):
    factory, (owner_a, _) = delivery_db
    now = future_clock()
    create_reminder(factory, owner_a, now, "retry")
    clock = Clock(now)
    gateway = FakeGateway([DeliveryFailure("telegram_timeout"), 777])
    store = DurableDeliveryStore(
        factory,
        lease_seconds=30,
        base_backoff_seconds=2,
    )
    worker = DurableWorker(store, gateway, clock=clock)

    assert await worker.run_once() == 1
    with factory() as session:
        delivery = session.query(ReminderDelivery).one()
        assert delivery.status == "failed"
        assert delivery.attempt_count == 1

    clock.value += timedelta(seconds=3)
    assert await worker.run_once() == 1
    with factory() as session:
        delivery = session.query(ReminderDelivery).one()
        assert delivery.status == "sent"
        assert delivery.attempt_count == 2
    assert len(gateway.messages) == 2


@pytest.mark.asyncio
async def test_permanent_telegram_error_is_dead_lettered(delivery_db):
    factory, (owner_a, _) = delivery_db
    now = future_clock()
    create_reminder(factory, owner_a, now, "blocked")
    gateway = FakeGateway([DeliveryFailure("telegram_403", permanent=True)])
    worker = DurableWorker(
        DurableDeliveryStore(factory),
        gateway,
        clock=lambda: now,
    )

    await worker.run_once()
    with factory() as session:
        delivery = session.query(ReminderDelivery).one()
        reminder = session.query(Reminder).one()
        assert delivery.status == "dead_letter"
        assert delivery.next_attempt_at_utc is None
        assert reminder.enabled is False


@pytest.mark.asyncio
async def test_paused_edited_and_deleted_reminders_do_not_run(delivery_db):
    factory, (owner_a, _) = delivery_db
    now = future_clock()
    paused_id = create_reminder(factory, owner_a, now, "paused")
    edited_id = create_reminder(factory, owner_a, now, "edited")
    deleted_id = create_reminder(factory, owner_a, now, "deleted")
    with factory() as session:
        service = DomainServices(session)
        paused = service.get_reminder(owner_a, paused_id)
        service.update_reminder(
            owner_a,
            paused_id,
            ReminderUpdate(version=paused.version, enabled=False),
        )
        edited = service.get_reminder(owner_a, edited_id)
        service.update_reminder(
            owner_a,
            edited_id,
            ReminderUpdate(
                version=edited.version,
                start_at_local=(now + timedelta(days=2)).replace(tzinfo=None),
                timezone="UTC",
            ),
        )
        service.delete_reminder(owner_a, deleted_id)
        session.commit()

    gateway = FakeGateway()
    worker = DurableWorker(
        DurableDeliveryStore(factory),
        gateway,
        clock=lambda: now,
    )
    assert await worker.run_once() == 0
    assert gateway.messages == []


@pytest.mark.asyncio
async def test_pause_after_claim_cancels_delivery_before_network_send(delivery_db):
    factory, (owner_a, _) = delivery_db
    now = future_clock()
    reminder_id = create_reminder(factory, owner_a, now, "pause-race")
    store = DurableDeliveryStore(factory)
    claim = store.claim_reminders(now)[0]
    with factory() as session:
        reminder = DomainServices(session).get_reminder(owner_a, reminder_id)
        DomainServices(session).update_reminder(
            owner_a,
            reminder_id,
            ReminderUpdate(version=reminder.version, enabled=False),
        )
        session.commit()

    gateway = FakeGateway()
    worker = DurableWorker(store, gateway, clock=lambda: now)
    await worker._deliver_reminder(claim)
    assert gateway.messages == []
    with factory() as session:
        assert session.get(ReminderDelivery, claim.delivery_id).status == "cancelled"


@pytest.mark.asyncio
async def test_missed_recurring_reminder_catches_up_once_without_flood(delivery_db):
    factory, (owner_a, _) = delivery_db
    now = future_clock()
    reminder_id = create_reminder(
        factory,
        owner_a,
        now,
        "missed-daily",
        schedule_type="daily",
    )
    gateway = FakeGateway()
    worker = DurableWorker(
        DurableDeliveryStore(factory),
        gateway,
        clock=lambda: now,
    )

    assert await worker.run_once() == 1
    assert await worker.run_once() == 0
    assert len(gateway.messages) == 1
    with factory() as session:
        delivery = session.query(ReminderDelivery).one()
        reminder = session.get(Reminder, reminder_id)
        assert delivery.scheduled_occurrence_at_utc < now.replace(tzinfo=None)
        assert delivery.delivered_at_utc == now.replace(tzinfo=None)
        assert reminder.next_run_at_utc > now.replace(tzinfo=None)


def test_expired_final_attempt_is_dead_lettered_without_an_extra_send(delivery_db):
    factory, (owner_a, _) = delivery_db
    now = future_clock()
    create_reminder(factory, owner_a, now, "final-lease")
    store = DurableDeliveryStore(
        factory,
        lease_seconds=30,
        max_attempts=1,
    )
    claim = store.claim_reminders(now)
    assert len(claim) == 1
    assert store.claim_reminders(now + timedelta(seconds=31)) == []
    with factory() as session:
        delivery = session.query(ReminderDelivery).one()
        assert delivery.status == "dead_letter"
        assert delivery.last_error_category == "claim_lease_expired"


def test_timezone_and_weekly_recurrence_are_wall_clock_safe():
    reminder = SimpleNamespace(
        schedule_type="weekly",
        timezone="Asia/Kolkata",
        scheduled_local_time="20:00:00",
        recurrence_rule={"weekday": 6},
    )
    after = datetime(2026, 8, 2, 14, 31, tzinfo=UTC)
    following = next_reminder_occurrence(reminder, after)
    assert following == datetime(2026, 8, 9, 14, 30, tzinfo=UTC)


@pytest.mark.asyncio
async def test_sunday_digest_is_tenant_scoped_once_and_falls_back(delivery_db):
    factory, (owner_a, owner_b) = delivery_db
    now = datetime(2026, 8, 2, 14, 30, tzinfo=UTC)
    with factory() as session:
        service = DomainServices(session)
        service.create_work_log(
            owner_a,
            WorkLogCreate(
                original_text="Alice shipped the API",
                logged_at_local=datetime(2026, 7, 30, 12),
                timezone="UTC",
                idempotency_key="digest-work-a",
            ),
        )
        service.create_work_log(
            owner_b,
            WorkLogCreate(
                original_text="Bob private secret",
                logged_at_local=datetime(2026, 7, 30, 12),
                timezone="UTC",
                idempotency_key="digest-work-b",
            ),
        )
        schedule = (
            session.query(ScheduledDigest)
            .filter(ScheduledDigest.owner_id == owner_a)
            .one()
        )
        schedule.timezone = "Asia/Kolkata"
        schedule.enabled = True
        schedule.next_run_at_utc = now
        session.commit()

    gateway = FakeGateway()
    worker = DurableWorker(
        DurableDeliveryStore(factory),
        gateway,
        narrator=FailingNarrator(),
        clock=lambda: now,
    )
    assert await worker.run_once() == 1
    assert "Alice shipped the API" in gateway.messages[0][1]
    assert "Bob private secret" not in gateway.messages[0][1]

    with factory() as session:
        delivery = session.query(DigestDelivery).one()
        assert delivery.status == "sent"
        schedule = (
            session.query(ScheduledDigest)
            .filter(ScheduledDigest.owner_id == owner_a)
            .one()
        )
        schedule.next_run_at_utc = now
        session.commit()

    assert await worker.run_once() == 0
    assert len(gateway.messages) == 1
    with factory() as session:
        assert session.query(DigestDelivery).count() == 1
