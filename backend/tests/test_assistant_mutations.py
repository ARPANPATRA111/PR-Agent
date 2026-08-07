"""Editing, status changes, goal progress, and settings by voice."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from assistant import ActorContext, BoundedAssistant
from domain.schemas import (
    GoalCreate,
    LedgerCreate,
    NoteCreate,
    ReminderCreate,
    WorkLogCreate,
)
from domain.services import DomainServices
from nutrition.providers import get_nutrition_provider
from public_models import (
    LedgerEntry,
    Note,
    PublicBase,
    Reminder,
    TrackedGoal,
    WorkLog,
)

ALICE = ActorContext(telegram_id=101, first_name="Alice")
BOB = ActorContext(telegram_id=202, first_name="Bob")


class FakeProvider:
    provider_name = "fake"
    model_name = "strict-test-model"

    def __init__(self, *outputs):
        self.outputs = list(outputs)

    def classify(self, text, *, context=None):
        output = self.outputs.pop(0)
        if isinstance(output, Exception):
            raise output
        return output


@pytest.fixture()
def assistant_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    PublicBase.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    engine.dispose()


def build_assistant(factory, provider):
    return BoundedAssistant(factory, provider, get_nutrition_provider("reference"))


def selector(**overrides) -> dict:
    return {"record_id": None, "search": None, "ordinal": None, **overrides}


def update_proposal(record_type: str, sel: dict, **fields) -> dict:
    action = {
        "kind": "update_record",
        "record_type": record_type,
        "selector": sel,
        "title": None,
        "text": None,
        "category": None,
        "tags": None,
        "amount": None,
        "currency": None,
        "target_value": None,
        "unit": None,
        "start_at_local": None,
        "timezone": None,
    }
    action.update(fields)
    return {"confidence": 0.95, "actions": [action]}


def status_proposal(record_type: str, sel: dict, status: str) -> dict:
    return {
        "confidence": 0.95,
        "actions": [
            {
                "kind": "set_record_status",
                "record_type": record_type,
                "selector": sel,
                "status": status,
            }
        ],
    }


def seed_owner(factory, actor: ActorContext) -> int:
    with factory() as session:
        owner = DomainServices(session).ensure_owner(
            telegram_id=actor.telegram_id,
            first_name=actor.first_name,
        )
        session.commit()
        return owner.id


def confirm_only_action(assistant, actor, reply):
    """Voice writes are reviewed; accept the review to apply them."""
    assert reply.status == "confirmation"
    return assistant.confirm(actor, reply.pending_id)


def test_editing_a_note_by_description(assistant_db):
    owner_id = seed_owner(assistant_db, ALICE)
    with assistant_db() as session:
        DomainServices(session).create_note(
            owner_id,
            NoteCreate(
                title="Relocation",
                body="Ask HR about relocation",
                capture_source="telegram_text",
                idempotency_key="seed-note-1",
            ),
        )
        session.commit()
    assistant = build_assistant(
        assistant_db,
        FakeProvider(
            update_proposal(
                "note",
                selector(search="relocation"),
                title="HR follow up",
            )
        ),
    )

    reply = assistant.handle(
        ALICE,
        "rename my relocation note to HR follow up",
        update_id=1,
        review_required=True,
    )
    done = confirm_only_action(assistant, ALICE, reply)

    assert done.status == "completed"
    with assistant_db() as session:
        assert session.query(Note).one().title == "HR follow up"


def test_editing_an_expense_amount(assistant_db):
    owner_id = seed_owner(assistant_db, ALICE)
    with assistant_db() as session:
        DomainServices(session).create_ledger_entry(
            owner_id,
            LedgerCreate(
                direction="expense",
                amount=450,
                currency="INR",
                description="Grocery run",
                capture_source="telegram_text",
                idempotency_key="seed-ledger-1",
            ),
        )
        session.commit()
    assistant = build_assistant(
        assistant_db,
        FakeProvider(
            update_proposal(
                "ledger_entry",
                selector(search="grocery"),
                amount="300",
                currency="INR",
            )
        ),
    )

    reply = assistant.handle(
        ALICE,
        "change my grocery expense to three hundred rupees",
        update_id=2,
        review_required=True,
    )
    done = confirm_only_action(assistant, ALICE, reply)

    assert done.status == "completed"
    with assistant_db() as session:
        assert session.query(LedgerEntry).one().amount_minor == 30000


def test_editing_a_work_log(assistant_db):
    owner_id = seed_owner(assistant_db, ALICE)
    with assistant_db() as session:
        DomainServices(session).create_work_log(
            owner_id,
            WorkLogCreate(
                original_text="Shipped the login screen",
                capture_source="telegram_text",
                idempotency_key="seed-worklog-1",
            ),
        )
        session.commit()
    assistant = build_assistant(
        assistant_db,
        FakeProvider(
            update_proposal(
                "work_log",
                selector(ordinal="latest"),
                category="engineering",
            )
        ),
    )

    reply = assistant.handle(
        ALICE,
        "set the category on my last log to engineering",
        update_id=3,
        review_required=True,
    )
    confirm_only_action(assistant, ALICE, reply)

    with assistant_db() as session:
        assert session.query(WorkLog).one().category == "engineering"


def test_pausing_and_resuming_a_reminder(assistant_db):
    owner_id = seed_owner(assistant_db, ALICE)
    with assistant_db() as session:
        DomainServices(session).create_reminder(
            owner_id,
            ReminderCreate(
                title="Drink water",
                schedule_type="daily",
                start_at_local="2026-08-06T09:00:00",
                timezone="Asia/Kolkata",
                idempotency_key="seed-reminder-1",
            ),
        )
        session.commit()
    assistant = build_assistant(
        assistant_db,
        FakeProvider(
            status_proposal("reminder", selector(search="water"), "disabled"),
            status_proposal("reminder", selector(search="water"), "enabled"),
        ),
    )

    paused = assistant.handle(
        ALICE, "pause my water reminder", update_id=4, review_required=True
    )
    confirm_only_action(assistant, ALICE, paused)
    with assistant_db() as session:
        assert session.query(Reminder).one().enabled is False

    resumed = assistant.handle(
        ALICE, "resume my water reminder", update_id=5, review_required=True
    )
    confirm_only_action(assistant, ALICE, resumed)
    with assistant_db() as session:
        assert session.query(Reminder).one().enabled is True


def test_completing_a_goal(assistant_db):
    owner_id = seed_owner(assistant_db, ALICE)
    with assistant_db() as session:
        DomainServices(session).create_goal(
            owner_id,
            GoalCreate(title="Read twelve books", idempotency_key="seed-goal-1"),
        )
        session.commit()
    assistant = build_assistant(
        assistant_db,
        FakeProvider(status_proposal("goal", selector(search="books"), "completed")),
    )

    reply = assistant.handle(
        ALICE, "mark my reading goal as done", update_id=6, review_required=True
    )
    confirm_only_action(assistant, ALICE, reply)

    with assistant_db() as session:
        assert session.query(TrackedGoal).one().status == "completed"


def test_pinning_a_note(assistant_db):
    owner_id = seed_owner(assistant_db, ALICE)
    with assistant_db() as session:
        DomainServices(session).create_note(
            owner_id,
            NoteCreate(
                title="Relocation",
                body="Ask HR about relocation",
                capture_source="telegram_text",
                idempotency_key="seed-note-1",
            ),
        )
        session.commit()
    assistant = build_assistant(
        assistant_db,
        FakeProvider(status_proposal("note", selector(search="relocation"), "pinned")),
    )

    reply = assistant.handle(
        ALICE, "pin my relocation note", update_id=7, review_required=True
    )
    confirm_only_action(assistant, ALICE, reply)

    with assistant_db() as session:
        assert session.query(Note).one().pinned is True


def test_adding_goal_progress(assistant_db):
    owner_id = seed_owner(assistant_db, ALICE)
    with assistant_db() as session:
        DomainServices(session).create_goal(
            owner_id,
            GoalCreate(
                title="Run a half marathon",
                target_value=Decimal("21"),
                unit="km",
                idempotency_key="seed-goal-1",
            ),
        )
        session.commit()
    assistant = build_assistant(
        assistant_db,
        FakeProvider(
            {
                "confidence": 0.95,
                "actions": [
                    {
                        "kind": "record_goal_progress",
                        "selector": selector(search="marathon"),
                        "value": "5",
                        "mode": "add",
                    }
                ],
            },
            {
                "confidence": 0.95,
                "actions": [
                    {
                        "kind": "record_goal_progress",
                        "selector": selector(search="marathon"),
                        "value": "3",
                        "mode": "add",
                    }
                ],
            },
        ),
    )

    first = assistant.handle(
        ALICE, "I ran five kilometres today", update_id=8, review_required=True
    )
    confirm_only_action(assistant, ALICE, first)
    second = assistant.handle(
        ALICE, "add three more kilometres", update_id=9, review_required=True
    )
    done = confirm_only_action(assistant, ALICE, second)

    assert done.status == "completed"
    with assistant_db() as session:
        assert Decimal(session.query(TrackedGoal).one().current_value) == Decimal("8")


def test_setting_goal_progress_absolutely(assistant_db):
    owner_id = seed_owner(assistant_db, ALICE)
    with assistant_db() as session:
        DomainServices(session).create_goal(
            owner_id,
            GoalCreate(
                title="Run a half marathon",
                target_value=Decimal("21"),
                unit="km",
                current_value=Decimal("5"),
                idempotency_key="seed-goal-1",
            ),
        )
        session.commit()
    assistant = build_assistant(
        assistant_db,
        FakeProvider(
            {
                "confidence": 0.95,
                "actions": [
                    {
                        "kind": "record_goal_progress",
                        "selector": selector(search="marathon"),
                        "value": "12",
                        "mode": "set",
                    }
                ],
            }
        ),
    )

    reply = assistant.handle(
        ALICE, "my total is now twelve kilometres", update_id=10, review_required=True
    )
    confirm_only_action(assistant, ALICE, reply)

    with assistant_db() as session:
        assert Decimal(session.query(TrackedGoal).one().current_value) == Decimal("12")


def test_changing_the_timezone_by_voice(assistant_db):
    seed_owner(assistant_db, ALICE)
    assistant = build_assistant(
        assistant_db,
        FakeProvider(
            {
                "confidence": 0.95,
                "actions": [
                    {
                        "kind": "update_settings",
                        "timezone": "Europe/London",
                        "sunday_digest_enabled": None,
                        "sunday_digest_time": None,
                    }
                ],
            }
        ),
    )

    reply = assistant.handle(
        ALICE,
        "change my timezone to Europe London",
        update_id=11,
        review_required=True,
    )
    done = confirm_only_action(assistant, ALICE, reply)

    assert done.status == "completed"
    assert "Europe/London" in done.text


def test_turning_off_the_sunday_summary(assistant_db):
    seed_owner(assistant_db, ALICE)
    assistant = build_assistant(
        assistant_db,
        FakeProvider(
            {
                "confidence": 0.95,
                "actions": [
                    {
                        "kind": "update_settings",
                        "timezone": None,
                        "sunday_digest_enabled": False,
                        "sunday_digest_time": None,
                    }
                ],
            }
        ),
    )

    reply = assistant.handle(
        ALICE, "turn off the Sunday summary", update_id=12, review_required=True
    )
    done = confirm_only_action(assistant, ALICE, reply)

    assert done.status == "completed"
    assert "off" in done.text


def test_an_update_never_reaches_another_tenants_record(assistant_db):
    alice_id = seed_owner(assistant_db, ALICE)
    seed_owner(assistant_db, BOB)
    with assistant_db() as session:
        DomainServices(session).create_note(
            alice_id,
            NoteCreate(
                title="Relocation",
                body="Ask HR about relocation",
                capture_source="telegram_text",
                idempotency_key="seed-note-1",
            ),
        )
        session.commit()
    assistant = build_assistant(
        assistant_db,
        FakeProvider(
            update_proposal("note", selector(search="relocation"), title="Hijacked")
        ),
    )

    reply = assistant.handle(
        BOB, "rename the relocation note", update_id=13, review_required=True
    )

    assert reply.status == "rejected"
    with assistant_db() as session:
        assert session.query(Note).one().title == "Relocation"


def test_an_ambiguous_edit_offers_a_choice_not_a_guess(assistant_db):
    owner_id = seed_owner(assistant_db, ALICE)
    with assistant_db() as session:
        service = DomainServices(session)
        for index in (1, 2):
            service.create_note(
                owner_id,
                NoteCreate(
                    title=f"Invoice {index}",
                    body=f"Invoice note {index}",
                    capture_source="telegram_text",
                    idempotency_key=f"seed-note-{index}",
                ),
            )
        session.commit()
    assistant = build_assistant(
        assistant_db,
        FakeProvider(
            update_proposal("note", selector(search="invoice"), title="Renamed")
        ),
    )

    reply = assistant.handle(
        ALICE, "rename my invoice note", update_id=14, review_required=True
    )

    assert reply.status == "disambiguation"
    assert len(reply.options) == 2
    with assistant_db() as session:
        titles = {row.title for row in session.query(Note).all()}
        assert titles == {"Invoice 1", "Invoice 2"}


def test_choosing_resumes_the_original_intent_not_a_deletion(assistant_db):
    """The chosen record must be edited, never deleted."""
    owner_id = seed_owner(assistant_db, ALICE)
    with assistant_db() as session:
        service = DomainServices(session)
        for index in (1, 2):
            service.create_note(
                owner_id,
                NoteCreate(
                    title=f"Invoice {index}",
                    body=f"Invoice note {index}",
                    capture_source="telegram_text",
                    idempotency_key=f"seed-note-{index}",
                ),
            )
        session.commit()
    assistant = build_assistant(
        assistant_db,
        FakeProvider(
            update_proposal("note", selector(search="invoice"), title="Renamed")
        ),
    )

    offered = assistant.handle(
        ALICE, "rename my invoice note", update_id=15, review_required=True
    )
    target = offered.options[0][0]
    chosen = assistant.choose(ALICE, offered.pending_id, target)
    done = assistant.confirm(ALICE, offered.pending_id)

    assert chosen.status == "confirmation"
    assert done.status == "completed"
    with assistant_db() as session:
        rows = {row.id: row.title for row in session.query(Note).all()}
        assert len(rows) == 2, "nothing may be deleted by an edit"
        assert rows[target] == "Renamed"


def test_an_update_with_no_changes_is_rejected_by_the_schema():
    from assistant.schemas import AgentProposal

    with pytest.raises(ValueError):
        AgentProposal.model_validate(
            {
                "confidence": 1,
                "action": {
                    "kind": "update_record",
                    "record_type": "note",
                    "selector": {"record_id": 1, "search": None, "ordinal": None},
                    "title": None,
                    "text": None,
                    "category": None,
                    "tags": None,
                    "amount": None,
                    "currency": None,
                    "target_value": None,
                    "unit": None,
                    "start_at_local": None,
                    "timezone": None,
                },
            }
        )


def test_a_selector_with_no_reference_is_rejected():
    from assistant.schemas import AgentProposal

    with pytest.raises(ValueError):
        AgentProposal.model_validate(
            {
                "confidence": 1,
                "action": {
                    "kind": "set_record_status",
                    "record_type": "goal",
                    "selector": {"record_id": None, "search": None, "ordinal": None},
                    "status": "completed",
                },
            }
        )


def test_a_status_that_does_not_apply_is_refused(assistant_db):
    owner_id = seed_owner(assistant_db, ALICE)
    with assistant_db() as session:
        DomainServices(session).create_goal(
            owner_id,
            GoalCreate(title="Read twelve books", idempotency_key="seed-goal-1"),
        )
        session.commit()
    assistant = build_assistant(
        assistant_db,
        FakeProvider(status_proposal("goal", selector(search="books"), "pinned")),
    )

    reply = assistant.handle(
        ALICE, "pin my reading goal", update_id=16, review_required=True
    )
    done = assistant.confirm(ALICE, reply.pending_id)

    assert done.status == "failed"
    with assistant_db() as session:
        assert session.query(TrackedGoal).one().status == "active"
