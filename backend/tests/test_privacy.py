import io
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
import zipfile

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from domain.schemas import LedgerCreate, NoteCreate, WorkLogCreate
from domain.services import DomainServices
from durable_worker import DeliveryFailure
from bot import TelegramClient
import bot as bot_module
from memory import (
    Base as LegacyBase,
    RawEntryDB,
    SearchableEntryDB,
    StructuredEntryDB,
    UserDB,
)
from privacy import PrivacyService, prune_operational_metadata
from public_models import (
    AccountDeletionAudit,
    AccountExportRequest,
    AgentAction,
    AgentPendingAction,
    AgentRun,
    ApplicationSession,
    InviteCode,
    Note,
    PublicBase,
    PublicUser,
    PrivateFact,
    PrivateFactAudit,
    RateLimitBucket,
    TelegramMessage,
    WorkLog,
)
from telegram_cleanup import (
    protect_pinned_telegram_message,
    TelegramCleanupStore,
    TelegramCleanupWorker,
    queue_telegram_message,
)

UTC = timezone.utc


class CleanupGateway:
    def __init__(self, failures=None):
        self.failures = list(failures or [])
        self.deleted = []

    async def delete(self, chat_id, message_id):
        self.deleted.append((chat_id, message_id))
        if self.failures:
            raise self.failures.pop(0)


@pytest.fixture()
def privacy_db(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'privacy.db'}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    LegacyBase.metadata.create_all(engine)
    PublicBase.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        alice = DomainServices(session).ensure_owner(
            telegram_id=101,
            first_name="Alice",
        )
        bob = DomainServices(session).ensure_owner(
            telegram_id=202,
            first_name="Bob",
        )
        session.add_all(
            [
                UserDB(telegram_id=101, first_name="Alice"),
                UserDB(telegram_id=202, first_name="Bob"),
            ]
        )
        session.commit()
        owner_ids = (alice.id, bob.id)
    yield factory, owner_ids
    engine.dispose()


def seed_owned_records(factory, owner_id, label):
    with factory() as session:
        service = DomainServices(session)
        service.create_work_log(
            owner_id,
            WorkLogCreate(
                original_text=f"{label} work",
                idempotency_key=f"work-{label.lower()}",
            ),
        )
        service.create_note(
            owner_id,
            NoteCreate(
                body=f"{label} note",
                idempotency_key=f"note-{label.lower()}",
            ),
        )
        service.create_ledger_entry(
            owner_id,
            LedgerCreate(
                direction="expense",
                amount="12.50",
                currency="INR",
                description=f"{label} expense",
                idempotency_key=f"ledger-{label.lower()}",
            ),
        )
        session.commit()


def test_export_contains_all_sections_and_excludes_other_tenant(privacy_db):
    factory, (alice_id, bob_id) = privacy_db
    seed_owned_records(factory, alice_id, "Alice")
    seed_owned_records(factory, bob_id, "Bob")
    with factory() as session:
        privacy = PrivacyService(session)
        payload = privacy.export_owner_data(alice_id)
        session.commit()
        assert payload["profile"]["telegram_id"] == 101
        assert payload["work_logs"][0]["original_text"] == "Alice work"
        assert payload["notes"][0]["body"] == "Alice note"
        assert payload["ledger_entries"][0]["description"] == "Alice expense"
        assert "Bob" not in privacy.json_bytes(payload).decode("utf-8")
        assert {
            "work_logs",
            "notes",
            "reminders",
            "ledger_entries",
            "nutrition_logs",
            "nutrition_items",
            "goals",
            "preferences",
            "summary_metadata",
        } <= payload.keys()
        serialized = privacy.json_bytes(payload).decode("utf-8")
        for forbidden in (
            "token_hash",
            "session_signing_secret",
            "idempotency_key",
            "provider_metadata",
            "input_hash",
            "proposed_arguments",
            "agent_runs",
            "private_facts",
            "ciphertext",
        ):
            assert forbidden not in serialized

        archive = zipfile.ZipFile(io.BytesIO(privacy.csv_zip_bytes(payload)))
        assert {
            "work_logs.csv",
            "notes.csv",
            "ledger_entries.csv",
            "profile.csv",
        } <= set(archive.namelist())


def test_account_deletion_removes_public_legacy_search_and_sessions(privacy_db):
    factory, (alice_id, _) = privacy_db
    seed_owned_records(factory, alice_id, "Alice")
    with factory() as session:
        raw = RawEntryDB(
            telegram_id=101,
            telegram_message_id=10,
            audio_file_id="legacy-file",
            audio_duration=3,
            transcript="legacy transcript",
        )
        session.add(raw)
        session.flush()
        session.add(
            StructuredEntryDB(
                raw_entry_id=raw.id,
                category="coding",
                summary="legacy summary",
            )
        )
        session.add(
            SearchableEntryDB(
                entry_id=raw.id,
                telegram_id=101,
                content="search copy",
            )
        )
        session.add(
            ApplicationSession(
                id="session-a",
                owner_id=alice_id,
                token_hash="a" * 64,
                expires_at_utc=datetime.now(UTC) + timedelta(minutes=5),
            )
        )
        private_fact = PrivateFact(
            owner_id=alice_id,
            record_uuid="11111111-1111-1111-1111-111111111111",
            fact_type="academic_score",
            label="Semester 4 CGPA",
            masked_value="Stored score",
            ciphertext=b"ciphertext-only",
            nonce=b"twelve-bytes",
            key_id="test",
        )
        session.add(private_fact)
        session.add(
            PrivateFactAudit(
                owner_id=alice_id,
                record_uuid=private_fact.record_uuid,
                action="create",
                channel="mini_app",
            )
        )
        run = AgentRun(
            owner_id=alice_id,
            provider="fake",
            model="test",
            status="confirmation",
            input_hash="d" * 64,
            original_update_id=90,
        )
        session.add(run)
        session.flush()
        session.add(
            AgentAction(
                run_id=run.id,
                owner_id=alice_id,
                action_type="delete_record",
                status="confirmation_required",
                idempotency_key="agent:101:90",
                argument_fields=["kind", "record_id", "record_type"],
            )
        )
        session.add(
            AgentPendingAction(
                owner_id=alice_id,
                run_id=run.id,
                action_type="delete_record",
                state="confirmation",
                proposed_arguments={
                    "kind": "delete_record",
                    "record_type": "note",
                    "record_id": 1,
                },
                missing_fields=[],
                prompt="Confirm deletion",
                original_update_id=90,
                idempotency_key="agent:101:90",
                expires_at_utc=datetime.now(UTC) + timedelta(minutes=5),
            )
        )
        session.commit()

    with factory() as session:
        service = PrivacyService(session)
        assert service.delete_account(
            alice_id,
            101,
            audit_secret="test-audit-secret-at-least-32-characters",
        )
        session.commit()

    with factory() as session:
        assert session.get(PublicUser, alice_id) is None
        assert session.query(WorkLog).filter(WorkLog.owner_id == alice_id).count() == 0
        assert session.query(ApplicationSession).count() == 0
        assert session.query(AgentRun).count() == 0
        assert session.query(AgentAction).count() == 0
        assert session.query(AgentPendingAction).count() == 0
        assert session.query(PrivateFact).count() == 0
        assert session.query(PrivateFactAudit).count() == 0
        assert session.query(UserDB).filter(UserDB.telegram_id == 101).count() == 0
        assert (
            session.query(SearchableEntryDB)
            .filter(SearchableEntryDB.telegram_id == 101)
            .count()
            == 0
        )
        assert session.query(AccountDeletionAudit).count() == 1
        assert (
            PrivacyService(session).delete_account(
                alice_id,
                101,
                audit_secret="test-audit-secret-at-least-32-characters",
            )
            is False
        )


def test_account_deletion_does_not_depend_on_database_cascades(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'no-fk-cascade.db'}")
    PublicBase.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        owner = DomainServices(session).ensure_owner(
            telegram_id=303,
            first_name="Cascade-independent",
        )
        DomainServices(session).create_note(
            owner.id,
            NoteCreate(body="must disappear", idempotency_key="delete-me"),
        )
        session.add(
            RateLimitBucket(
                subject_key=f"owner:{owner.id}",
                scope="ai_classifications",
                window_start=datetime.now(UTC),
                request_count=1,
            )
        )
        session.add(
            InviteCode(
                code_hash="a" * 64,
                created_by_owner_id=owner.id,
                claimed_by_owner_id=owner.id,
            )
        )
        session.commit()
        owner_id = owner.id

    with factory() as session:
        assert PrivacyService(session).delete_account(
            owner_id,
            303,
            audit_secret="test-audit-secret-at-least-32-characters",
        )
        session.commit()

    with factory() as session:
        assert session.get(PublicUser, owner_id) is None
        assert session.query(Note).filter(Note.owner_id == owner_id).count() == 0
        assert (
            session.query(RateLimitBucket)
            .filter(RateLimitBucket.subject_key == f"owner:{owner_id}")
            .count()
            == 0
        )
        invite = session.query(InviteCode).one()
        assert invite.created_by_owner_id is None
        assert invite.claimed_by_owner_id is None
    engine.dispose()


@pytest.mark.asyncio
async def test_cleanup_failure_never_rolls_back_stored_record(privacy_db):
    factory, (alice_id, _) = privacy_db
    seed_owned_records(factory, alice_id, "Alice")
    now = datetime(2026, 8, 1, 10, tzinfo=UTC)
    with factory() as session:
        queue_telegram_message(
            session,
            telegram_id=101,
            chat_id=101,
            message_id=99,
            direction="inbound",
            purpose="processed_input",
            processed_at=now,
            delete_after=now,
        )
        session.commit()

    gateway = CleanupGateway([DeliveryFailure("telegram_cleanup_timeout")])
    store = TelegramCleanupStore(
        factory,
        base_backoff_seconds=1,
    )
    worker = TelegramCleanupWorker(store, gateway, clock=lambda: now)
    assert await worker.run_once() == 1
    with factory() as session:
        message = session.query(TelegramMessage).one()
        assert message.cleanup_status == "failed"
        assert session.query(WorkLog).filter(WorkLog.owner_id == alice_id).count() == 1
        message.next_cleanup_attempt_at_utc = now
        session.commit()

    assert await worker.run_once() == 1
    with factory() as session:
        message = session.query(TelegramMessage).one()
        assert message.cleanup_status == "deleted"
        assert message.deleted_at_utc is not None


@pytest.mark.asyncio
async def test_pinned_message_is_excluded_from_cleanup(privacy_db):
    factory, _ = privacy_db
    now = datetime(2026, 8, 1, 10, tzinfo=UTC)
    with factory() as session:
        queue_telegram_message(
            session,
            telegram_id=101,
            chat_id=101,
            message_id=77,
            direction="outbound",
            purpose="bot_response",
            processed_at=now,
            delete_after=now,
        )
        assert protect_pinned_telegram_message(
            session,
            chat_id=101,
            message_id=77,
        )
        session.commit()

    gateway = CleanupGateway()
    worker = TelegramCleanupWorker(
        TelegramCleanupStore(factory),
        gateway,
        clock=lambda: now,
    )
    assert await worker.run_once() == 0
    assert gateway.deleted == []
    with factory() as session:
        assert session.query(TelegramMessage).one().cleanup_status == "cancelled"


@pytest.mark.asyncio
async def test_successful_outbound_message_queues_identifier_only_cleanup(
    privacy_db,
    monkeypatch,
):
    factory, _ = privacy_db

    class Memory:
        @contextmanager
        def get_session(self):
            session = factory()
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

    monkeypatch.setattr(bot_module, "get_memory_manager", lambda: Memory())
    monkeypatch.setattr(bot_module.settings, "message_cleanup_enabled", True)
    monkeypatch.setattr(bot_module.settings, "message_cleanup_delay_seconds", 0)
    client = TelegramClient("test-token")
    client._request_with_retry = AsyncMock(
        return_value={"ok": True, "result": {"message_id": 501}}
    )

    response = await client.send_message(101, "private confirmation")
    assert response["ok"] is True
    with factory() as session:
        cleanup = session.query(TelegramMessage).one()
        assert cleanup.telegram_message_id == 501
        assert cleanup.direction == "outbound"
        assert not hasattr(cleanup, "content")
        assert not hasattr(cleanup, "text")


def test_retention_prunes_only_expired_operational_metadata(privacy_db):
    factory, (alice_id, _) = privacy_db
    now = datetime(2026, 8, 1, 10, tzinfo=UTC)
    with factory() as session:
        session.add(
            ApplicationSession(
                id="expired-session",
                owner_id=alice_id,
                token_hash="b" * 64,
                expires_at_utc=now - timedelta(minutes=1),
            )
        )
        session.add(
            AccountExportRequest(
                owner_id=alice_id,
                status="completed",
                requested_at_utc=now - timedelta(hours=1),
                expires_at_utc=now - timedelta(minutes=1),
            )
        )
        old_run = AgentRun(
            owner_id=alice_id,
            provider="fake",
            model="test",
            status="completed",
            input_hash="e" * 64,
            original_update_id=91,
            completed_at_utc=now - timedelta(days=31),
        )
        session.add(old_run)
        session.flush()
        session.add(
            AgentAction(
                run_id=old_run.id,
                owner_id=alice_id,
                action_type="query",
                status="executed",
                idempotency_key="agent:101:91",
                argument_fields=["kind", "query_type"],
            )
        )
        session.commit()
        assert (
            prune_operational_metadata(
                session,
                now=now,
                retention_days=30,
            )
            == 3
        )
        session.commit()
        assert session.query(PublicUser).filter(PublicUser.id == alice_id).count() == 1
        assert session.query(AgentRun).count() == 0
        assert session.query(AgentAction).count() == 0
