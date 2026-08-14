"""Deleting by spoken reference instead of by record id."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from assistant import ActorContext, BoundedAssistant
from assistant.schemas import AgentProposal
from domain.schemas import LedgerCreate, NoteCreate
from domain.services import DomainServices
from nutrition.providers import get_nutrition_provider
from public_models import AgentPendingAction, LedgerEntry, Note, PublicBase

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


def delete_proposal(record_type: str, **overrides) -> dict:
    action = {
        "kind": "delete_record",
        "record_type": record_type,
        "record_id": None,
        "search": None,
        "ordinal": None,
    }
    action.update(overrides)
    return {"confidence": 0.95, "actions": [action]}


def delete_many_proposal(record_type: str) -> dict:
    return {
        "confidence": 0.99,
        "actions": [
            {
                "kind": "delete_many_records",
                "record_type": record_type,
                "scope": "all",
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


def seed_note(factory, owner_id: int, title: str, body: str, key: str) -> int:
    with factory() as session:
        row = DomainServices(session).create_note(
            owner_id,
            NoteCreate(
                title=title,
                body=body,
                capture_source="telegram_text",
                idempotency_key=key,
            ),
        )
        session.commit()
        return row.id


def test_schema_rejects_a_deletion_with_no_way_to_identify_it():
    with pytest.raises(ValueError):
        AgentProposal.model_validate(
            {
                "confidence": 1,
                "action": {
                    "kind": "delete_record",
                    "record_type": "note",
                    "record_id": None,
                    "search": None,
                    "ordinal": None,
                },
            }
        )


def test_delete_all_notes_snapshots_owned_rows_and_requires_confirmation(assistant_db):
    alice_id = seed_owner(assistant_db, ALICE)
    bob_id = seed_owner(assistant_db, BOB)
    seed_note(assistant_db, alice_id, "One", "Alice one", "alice-one")
    seed_note(assistant_db, alice_id, "Two", "Alice two", "alice-two")
    seed_note(assistant_db, bob_id, "Other", "Bob note", "bob-note-one")
    assistant = build_assistant(
        assistant_db,
        FakeProvider(delete_many_proposal("note")),
    )

    review = assistant.handle(ALICE, "delete all notes", update_id=901)
    assert review.status == "confirmation"
    assert "all 2 note records" in review.text
    with assistant_db() as session:
        assert session.query(Note).count() == 3

    done = assistant.confirm(ALICE, review.pending_id)
    assert done.status == "completed"
    assert "Deleted 2 note records" in done.text
    with assistant_db() as session:
        assert session.query(Note).filter(Note.owner_id == alice_id).count() == 0
        assert session.query(Note).filter(Note.owner_id == bob_id).count() == 1


def test_wrong_bulk_deletion_keeps_every_record(assistant_db):
    owner_id = seed_owner(assistant_db, ALICE)
    seed_note(assistant_db, owner_id, "Keep", "Keep me", "keep-one")
    assistant = build_assistant(
        assistant_db,
        FakeProvider(delete_many_proposal("note")),
    )

    review = assistant.handle(ALICE, "delete all notes", update_id=902)
    cancelled = assistant.cancel(ALICE, review.pending_id)

    assert cancelled.status == "cancelled"
    with assistant_db() as session:
        assert session.query(Note).filter(Note.owner_id == owner_id).count() == 1


def test_single_match_confirms_using_the_record_text(assistant_db):
    owner_id = seed_owner(assistant_db, ALICE)
    seed_note(
        assistant_db, owner_id, "Invoice", "Ravi needs the invoice", "seed-note-1"
    )
    assistant = build_assistant(
        assistant_db,
        FakeProvider(delete_proposal("note", search="invoice")),
    )

    reply = assistant.handle(ALICE, "delete my note about the invoice", update_id=1)

    assert reply.status == "confirmation"
    assert "Invoice" in reply.text
    assert "#" not in reply.text
    with assistant_db() as session:
        assert session.query(Note).count() == 1


def test_confirming_a_resolved_deletion_removes_the_record(assistant_db):
    owner_id = seed_owner(assistant_db, ALICE)
    seed_note(
        assistant_db, owner_id, "Invoice", "Ravi needs the invoice", "seed-note-1"
    )
    assistant = build_assistant(
        assistant_db,
        FakeProvider(delete_proposal("note", search="invoice")),
    )

    reply = assistant.handle(ALICE, "delete my note about the invoice", update_id=2)
    confirmed = assistant.confirm(ALICE, reply.pending_id)

    assert confirmed.status == "completed"
    with assistant_db() as session:
        assert session.query(Note).count() == 0


def test_no_match_explains_instead_of_asking_for_an_id(assistant_db):
    seed_owner(assistant_db, ALICE)
    assistant = build_assistant(
        assistant_db,
        FakeProvider(delete_proposal("note", search="mortgage")),
    )

    reply = assistant.handle(ALICE, "delete my note about the mortgage", update_id=3)

    assert reply.status == "rejected"
    assert "could not find" in reply.text
    assert "ID" not in reply.text


def test_several_matches_offer_choices_rather_than_deleting(assistant_db):
    owner_id = seed_owner(assistant_db, ALICE)
    first = seed_note(
        assistant_db, owner_id, "Invoice A", "Ravi invoice for June", "seed-note-1"
    )
    second = seed_note(
        assistant_db, owner_id, "Invoice B", "Priya invoice for July", "seed-note-2"
    )
    assistant = build_assistant(
        assistant_db,
        FakeProvider(delete_proposal("note", search="invoice")),
    )

    reply = assistant.handle(ALICE, "delete my invoice note", update_id=4)

    assert reply.status == "disambiguation"
    assert {record_id for record_id, _ in reply.options} == {first, second}
    with assistant_db() as session:
        assert session.query(Note).count() == 2


def test_choosing_a_candidate_then_confirming_deletes_only_that_record(assistant_db):
    owner_id = seed_owner(assistant_db, ALICE)
    keep = seed_note(
        assistant_db, owner_id, "Invoice A", "Ravi invoice for June", "seed-note-1"
    )
    remove = seed_note(
        assistant_db, owner_id, "Invoice B", "Priya invoice for July", "seed-note-2"
    )
    assistant = build_assistant(
        assistant_db,
        FakeProvider(delete_proposal("note", search="invoice")),
    )

    offered = assistant.handle(ALICE, "delete my invoice note", update_id=5)
    chosen = assistant.choose(ALICE, offered.pending_id, remove)
    confirmed = assistant.confirm(ALICE, offered.pending_id)

    assert chosen.status == "confirmation"
    assert "Invoice B" in chosen.text
    assert confirmed.status == "completed"
    with assistant_db() as session:
        remaining = session.query(Note).all()
        assert [row.id for row in remaining] == [keep]


def test_a_choice_outside_the_offered_candidates_is_refused(assistant_db):
    owner_id = seed_owner(assistant_db, ALICE)
    seed_note(assistant_db, owner_id, "Invoice A", "Ravi invoice June", "seed-note-1")
    seed_note(assistant_db, owner_id, "Invoice B", "Priya invoice July", "seed-note-2")
    unrelated = seed_note(
        assistant_db, owner_id, "Salary", "Salary review in March", "seed-note-3"
    )
    assistant = build_assistant(
        assistant_db,
        FakeProvider(delete_proposal("note", search="invoice")),
    )

    offered = assistant.handle(ALICE, "delete my invoice note", update_id=6)
    chosen = assistant.choose(ALICE, offered.pending_id, unrelated)

    assert chosen.status == "rejected"
    with assistant_db() as session:
        assert session.query(Note).count() == 3


def test_another_tenant_cannot_choose_from_someone_elses_candidates(assistant_db):
    owner_id = seed_owner(assistant_db, ALICE)
    seed_owner(assistant_db, BOB)
    seed_note(assistant_db, owner_id, "Invoice A", "Ravi invoice June", "seed-note-1")
    target = seed_note(
        assistant_db, owner_id, "Invoice B", "Priya invoice July", "seed-note-2"
    )
    assistant = build_assistant(
        assistant_db,
        FakeProvider(delete_proposal("note", search="invoice")),
    )

    offered = assistant.handle(ALICE, "delete my invoice note", update_id=7)
    hijacked = assistant.choose(BOB, offered.pending_id, target)

    assert hijacked.status == "rejected"
    with assistant_db() as session:
        assert session.query(Note).count() == 2


def test_deletion_never_resolves_against_another_tenants_records(assistant_db):
    alice_id = seed_owner(assistant_db, ALICE)
    seed_owner(assistant_db, BOB)
    seed_note(
        assistant_db, alice_id, "Invoice", "Ravi needs the invoice", "seed-note-1"
    )
    assistant = build_assistant(
        assistant_db,
        FakeProvider(delete_proposal("note", search="invoice")),
    )

    reply = assistant.handle(BOB, "delete the note about the invoice", update_id=8)

    assert reply.status == "rejected"
    with assistant_db() as session:
        assert session.query(Note).count() == 1


def test_latest_ordinal_targets_the_most_recent_record(assistant_db):
    owner_id = seed_owner(assistant_db, ALICE)
    with assistant_db() as session:
        service = DomainServices(session)
        service.create_ledger_entry(
            owner_id,
            LedgerCreate(
                direction="expense",
                amount=100,
                currency="INR",
                description="Older taxi ride",
                capture_source="telegram_text",
                idempotency_key="seed-ledger-1",
            ),
        )
        service.create_ledger_entry(
            owner_id,
            LedgerCreate(
                direction="expense",
                amount=250,
                currency="INR",
                description="Newer lunch",
                capture_source="telegram_text",
                idempotency_key="seed-ledger-2",
            ),
        )
        session.commit()
    assistant = build_assistant(
        assistant_db,
        FakeProvider(delete_proposal("ledger_entry", ordinal="latest")),
    )

    reply = assistant.handle(ALICE, "delete my last expense", update_id=9)
    assistant.confirm(ALICE, reply.pending_id)

    assert "Newer lunch" in reply.text
    with assistant_db() as session:
        remaining = session.query(LedgerEntry).all()
        assert [row.description for row in remaining] == ["Older taxi ride"]


def test_cancelling_a_choice_leaves_everything_intact(assistant_db):
    owner_id = seed_owner(assistant_db, ALICE)
    seed_note(assistant_db, owner_id, "Invoice A", "Ravi invoice June", "seed-note-1")
    seed_note(assistant_db, owner_id, "Invoice B", "Priya invoice July", "seed-note-2")
    assistant = build_assistant(
        assistant_db,
        FakeProvider(delete_proposal("note", search="invoice")),
    )

    offered = assistant.handle(ALICE, "delete my invoice note", update_id=10)
    cancelled = assistant.cancel(ALICE, offered.pending_id)

    assert cancelled.status == "cancelled"
    with assistant_db() as session:
        assert session.query(Note).count() == 2
        pending = session.query(AgentPendingAction).one()
        assert pending.state == "cancelled"


def test_an_explicit_record_id_still_works(assistant_db):
    owner_id = seed_owner(assistant_db, ALICE)
    note_id = seed_note(
        assistant_db, owner_id, "Invoice", "Ravi needs the invoice", "seed-note-1"
    )
    assistant = build_assistant(
        assistant_db,
        FakeProvider(delete_proposal("note", record_id=note_id)),
    )

    reply = assistant.handle(ALICE, f"delete note {note_id}", update_id=11)
    confirmed = assistant.confirm(ALICE, reply.pending_id)

    assert confirmed.status == "completed"
    with assistant_db() as session:
        assert session.query(Note).count() == 0
