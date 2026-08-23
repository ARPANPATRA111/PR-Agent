"""Retrieval, conversational replies, and review-free read paths."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from assistant import ActorContext, BoundedAssistant
from domain.schemas import GoalCreate, LedgerCreate, NoteCreate, WorkLogCreate
from domain.services import DomainServices
from nutrition.providers import get_nutrition_provider
from public_models import AgentPendingAction, Note, NutritionLog, PublicBase, WorkLog

UTC = timezone.utc

ALICE = ActorContext(telegram_id=101, first_name="Alice")
BOB = ActorContext(telegram_id=202, first_name="Bob")


class FakeProvider:
    provider_name = "fake"
    model_name = "strict-test-model"

    def __init__(self, *outputs):
        self.outputs = list(outputs)
        self.contexts = []

    def classify(self, text, *, context=None):
        self.contexts.append((text, context))
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


def build_assistant(factory, provider, **kwargs):
    return BoundedAssistant(
        factory,
        provider,
        get_nutrition_provider("reference"),
        **kwargs,
    )


def list_proposal(record_type: str, **overrides) -> dict:
    action = {
        "kind": "list_records",
        "record_type": record_type,
        "search": None,
        "tag": None,
        "status": None,
        "start_date": None,
        "end_date": None,
        "limit": 10,
        "timezone": "Asia/Kolkata",
    }
    action.update(overrides)
    return {"confidence": 0.95, "actions": [action]}


def seed_owner(factory, actor: ActorContext) -> int:
    with factory() as session:
        owner = DomainServices(session).ensure_owner(
            telegram_id=actor.telegram_id,
            first_name=actor.first_name,
        )
        session.commit()
        return owner.id


def seed_note(factory, owner_id: int, title: str, body: str, key: str) -> None:
    with factory() as session:
        DomainServices(session).create_note(
            owner_id,
            NoteCreate(
                title=title,
                body=body,
                capture_source="telegram_text",
                idempotency_key=key,
            ),
        )
        session.commit()


def test_listing_notes_returns_them_without_a_review(assistant_db):
    owner_id = seed_owner(assistant_db, ALICE)
    seed_note(
        assistant_db, owner_id, "Relocation", "Ask HR about relocation", "seed-note-1"
    )
    seed_note(
        assistant_db, owner_id, "Invoice", "Ravi needs the invoice", "seed-note-2"
    )
    assistant = build_assistant(assistant_db, FakeProvider(list_proposal("note")))

    reply = assistant.handle(ALICE, "show me all my notes", update_id=1)

    assert reply.status == "completed"
    assert reply.pending_id is None
    assert "Ask HR about relocation" in reply.text
    assert "Ravi needs the invoice" in reply.text


def test_listing_stays_review_free_even_for_voice(assistant_db):
    """A retrieval changes nothing, so a Correct/Wrong tap only adds friction."""
    owner_id = seed_owner(assistant_db, ALICE)
    seed_note(
        assistant_db, owner_id, "Relocation", "Ask HR about relocation", "seed-note-1"
    )
    assistant = build_assistant(assistant_db, FakeProvider(list_proposal("note")))

    reply = assistant.handle(
        ALICE,
        "show me all my notes",
        update_id=2,
        review_required=True,
    )

    assert reply.status == "completed"
    assert "Ask HR about relocation" in reply.text
    with assistant_db() as session:
        assert session.query(AgentPendingAction).count() == 0


def test_listing_searches_within_the_owner_records(assistant_db):
    owner_id = seed_owner(assistant_db, ALICE)
    seed_note(
        assistant_db, owner_id, "Relocation", "Ask HR about relocation", "seed-note-1"
    )
    seed_note(
        assistant_db, owner_id, "Invoice", "Ravi needs the invoice", "seed-note-2"
    )
    assistant = build_assistant(
        assistant_db,
        FakeProvider(list_proposal("note", search="invoice")),
    )

    reply = assistant.handle(ALICE, "find my note about the invoice", update_id=3)

    assert "Ravi needs the invoice" in reply.text
    assert "relocation" not in reply.text.lower()


def test_listing_never_crosses_tenants(assistant_db):
    alice_id = seed_owner(assistant_db, ALICE)
    seed_owner(assistant_db, BOB)
    seed_note(
        assistant_db, alice_id, "Salary", "Alice private salary note", "seed-note-1"
    )
    assistant = build_assistant(
        assistant_db,
        FakeProvider(list_proposal("note"), list_proposal("note")),
    )

    alice_reply = assistant.handle(ALICE, "show my notes", update_id=4)
    bob_reply = assistant.handle(BOB, "show my notes", update_id=5)

    assert "Alice private salary note" in alice_reply.text
    assert "Alice private salary note" not in bob_reply.text
    assert "No notes matched that." in bob_reply.text


def test_empty_result_is_stated_plainly(assistant_db):
    seed_owner(assistant_db, ALICE)
    assistant = build_assistant(assistant_db, FakeProvider(list_proposal("reminder")))

    reply = assistant.handle(ALICE, "what reminders do I have", update_id=6)

    assert reply.status == "completed"
    assert "No reminders matched that." in reply.text


def test_listing_ledger_renders_major_units(assistant_db):
    owner_id = seed_owner(assistant_db, ALICE)
    with assistant_db() as session:
        DomainServices(session).create_ledger_entry(
            owner_id,
            LedgerCreate(
                direction="expense",
                amount=450,
                currency="INR",
                description="Transport to the airport",
                capture_source="telegram_text",
                idempotency_key="seed-ledger-1",
            ),
        )
        session.commit()
    assistant = build_assistant(
        assistant_db,
        FakeProvider(list_proposal("ledger_entry")),
    )

    reply = assistant.handle(ALICE, "show my expenses", update_id=7)

    assert "INR 450.00" in reply.text
    assert "45000" not in reply.text


def test_listing_goals_can_filter_by_status(assistant_db):
    owner_id = seed_owner(assistant_db, ALICE)
    with assistant_db() as session:
        service = DomainServices(session)
        service.create_goal(
            owner_id,
            GoalCreate(title="Run a half marathon", idempotency_key="seed-goal-1"),
        )
        service.create_goal(
            owner_id,
            GoalCreate(title="Read twelve books", idempotency_key="seed-goal-2"),
        )
        session.commit()
    assistant = build_assistant(
        assistant_db,
        FakeProvider(list_proposal("goal", status="active")),
    )

    reply = assistant.handle(ALICE, "which goals are active", update_id=8)

    assert "Run a half marathon" in reply.text
    assert "Read twelve books" in reply.text


def test_goal_progress_does_not_expose_database_decimal_scale(assistant_db):
    owner_id = seed_owner(assistant_db, ALICE)
    with assistant_db() as session:
        DomainServices(session).create_goal(
            owner_id,
            GoalCreate(
                title="Capability Test Voice coverage",
                target_value=20,
                unit="scenarios",
                idempotency_key="seed-goal-format",
            ),
        )
        session.commit()
    assistant = build_assistant(
        assistant_db,
        FakeProvider(list_proposal("goal", status="active")),
    )

    reply = assistant.handle(ALICE, "which goals are active", update_id=81)

    assert "0/20 scenarios" in reply.text
    assert "0.000" not in reply.text


def seed_expense(
    factory,
    owner_id: int,
    *,
    amount: str,
    description: str,
    category: str,
    occurred_at: datetime,
    key: str,
) -> None:
    with factory() as session:
        DomainServices(session).create_ledger_entry(
            owner_id,
            LedgerCreate(
                direction="expense",
                amount=amount,
                currency="INR",
                description=description,
                category=category,
                transaction_at_local=occurred_at,
                timezone="Asia/Kolkata",
                capture_source="telegram_text",
                idempotency_key=key,
            ),
        )
        session.commit()


def test_spending_queries_honor_period_search_and_category_ranking(assistant_db):
    owner_id = seed_owner(assistant_db, ALICE)
    seed_expense(
        assistant_db,
        owner_id,
        amount="299",
        description="mobile data recharge",
        category="bills",
        occurred_at=datetime(2026, 7, 5, 10, 0),
        key="july-mobile",
    )
    seed_expense(
        assistant_db,
        owner_id,
        amount="1200",
        description="monthly groceries",
        category="food",
        occurred_at=datetime(2026, 7, 8, 10, 0),
        key="july-groceries",
    )
    seed_expense(
        assistant_db,
        owner_id,
        amount="999",
        description="mobile data current month",
        category="bills",
        occurred_at=datetime(2026, 8, 3, 10, 0),
        key="august-mobile",
    )
    provider = FakeProvider(
        {
            "confidence": 0.99,
            "action": {
                "kind": "query",
                "query_type": "spending",
                "timezone": "Asia/Kolkata",
                "start_date": None,
                "end_date": None,
                "search": None,
                "ranking": None,
            },
        },
        {
            "confidence": 0.99,
            "action": {
                "kind": "query",
                "query_type": "spending",
                "timezone": "Asia/Kolkata",
                "start_date": None,
                "end_date": None,
                "search": None,
                "ranking": "highest",
            },
        },
        {
            "confidence": 0.99,
            "action": {
                "kind": "query",
                "query_type": "spending",
                "timezone": "Asia/Kolkata",
                "start_date": "2026-06-01",
                "end_date": "2026-06-30",
                "search": None,
                "ranking": None,
            },
        },
    )
    assistant = build_assistant(
        assistant_db,
        provider,
        clock=lambda: datetime(2026, 8, 22, 12, tzinfo=UTC),
    )

    mobile = assistant.handle(
        ALICE,
        "how much did I spend on mobile data last month",
        update_id=201,
    )
    highest = assistant.handle(
        ALICE,
        "where did I spend the most last month",
        update_id=202,
    )
    empty = assistant.handle(ALICE, "spending in June", update_id=203)

    assert "299.00" in mobile.text
    assert "999.00" not in mobile.text
    assert "food" in highest.text
    assert "1200.00" in highest.text
    assert empty.text == "No expenses recorded for 2026-06-01 to 2026-06-30."


def test_listing_work_logs_respects_a_date_window(assistant_db):
    owner_id = seed_owner(assistant_db, ALICE)
    with assistant_db() as session:
        service = DomainServices(session)
        service.create_work_log(
            owner_id,
            WorkLogCreate(
                original_text="Shipped the tenant isolation tests",
                capture_source="telegram_text",
                idempotency_key="seed-worklog-1",
            ),
        )
        session.commit()
    today = datetime.now(UTC).date()
    assistant = build_assistant(
        assistant_db,
        FakeProvider(
            list_proposal(
                "work_log",
                start_date=str(today),
                end_date=str(today),
            )
        ),
    )

    reply = assistant.handle(ALICE, "what did I log today", update_id=9)

    assert "Shipped the tenant isolation tests" in reply.text


def test_last_week_work_query_uses_the_complete_previous_week(assistant_db):
    owner_id = seed_owner(assistant_db, ALICE)
    with assistant_db() as session:
        session.add_all(
            [
                WorkLog(
                    owner_id=owner_id,
                    public_id=1,
                    original_text="Completed the previous-week launch review",
                    logged_at_utc=datetime(2026, 8, 12, 10, tzinfo=UTC),
                    user_local_date=datetime(2026, 8, 12).date(),
                    timezone="Asia/Kolkata",
                    capture_source="test",
                ),
                WorkLog(
                    owner_id=owner_id,
                    public_id=2,
                    original_text="Current-week task must stay out",
                    logged_at_utc=datetime(2026, 8, 19, 10, tzinfo=UTC),
                    user_local_date=datetime(2026, 8, 19).date(),
                    timezone="Asia/Kolkata",
                    capture_source="test",
                ),
            ]
        )
        session.commit()
    assistant = build_assistant(
        assistant_db,
        FakeProvider(
            {
                "confidence": 0.99,
                "actions": [
                    {
                        "kind": "query",
                        "query_type": "week",
                        "timezone": "Asia/Kolkata",
                        "start_date": None,
                        "end_date": None,
                        "lookback_hours": None,
                        "search": None,
                        "ranking": None,
                    }
                ],
            }
        ),
        clock=lambda: datetime(2026, 8, 23, 12, tzinfo=UTC),
    )

    reply = assistant.handle(ALICE, "tell me what I did last week", update_id=91)

    assert "previous-week launch review" in reply.text
    assert "Current-week task" not in reply.text
    assert "2026-08-10 to 2026-08-16" in reply.text


def test_nutrition_advice_reads_only_the_requested_last_48_hours(assistant_db):
    owner_id = seed_owner(assistant_db, ALICE)
    with assistant_db() as session:
        preference = DomainServices(session).get_nutrition_preferences(owner_id)
        preference.protein_target_grams = Decimal("90")
        preference.calorie_target = Decimal("2200")
        session.add_all(
            [
                NutritionLog(
                    owner_id=owner_id,
                    public_id=1,
                    meal_name="Recent paneer lunch",
                    logged_at_utc=datetime(2026, 8, 22, 12, tzinfo=UTC),
                    user_local_date=datetime(2026, 8, 22).date(),
                    timezone="Asia/Kolkata",
                    original_text="paneer lunch",
                    status="confirmed",
                    total_calories=Decimal("700"),
                    total_protein_grams=Decimal("35"),
                    estimation_source="test",
                    confirmed_by_user=True,
                ),
                NutritionLog(
                    owner_id=owner_id,
                    public_id=2,
                    meal_name="Old meal outside range",
                    logged_at_utc=datetime(2026, 8, 20, 10, tzinfo=UTC),
                    user_local_date=datetime(2026, 8, 20).date(),
                    timezone="Asia/Kolkata",
                    original_text="old meal",
                    status="confirmed",
                    total_calories=Decimal("2000"),
                    total_protein_grams=Decimal("100"),
                    estimation_source="test",
                    confirmed_by_user=True,
                ),
            ]
        )
        session.commit()
    assistant = build_assistant(
        assistant_db,
        FakeProvider(
            {
                "confidence": 0.99,
                "actions": [
                    {
                        "kind": "query",
                        "query_type": "nutrition",
                        "timezone": "Asia/Kolkata",
                        "start_date": None,
                        "end_date": None,
                        "lookback_hours": 48,
                        "search": None,
                        "ranking": None,
                    }
                ],
            }
        ),
        clock=lambda: datetime(2026, 8, 23, 12, tzinfo=UTC),
    )

    reply = assistant.handle(
        ALICE,
        "Based on what I ate in the last 48 hours, what should I improve?",
        update_id=92,
    )

    assert "Recent paneer lunch" in reply.text
    assert "Old meal outside range" not in reply.text
    assert "700" in reply.text
    assert "Suggestions based on those logs" in reply.text
    assert "protein" in reply.text.lower()


def test_listing_limit_is_capped_by_the_schema(assistant_db):
    seed_owner(assistant_db, ALICE)
    assistant = build_assistant(
        assistant_db,
        FakeProvider(list_proposal("note", limit=500)),
    )

    reply = assistant.handle(ALICE, "show me everything", update_id=10)

    assert reply.status == "failed"


def test_smalltalk_answers_briefly_without_touching_records(assistant_db):
    seed_owner(assistant_db, ALICE)
    assistant = build_assistant(
        assistant_db,
        FakeProvider(
            {
                "confidence": 0.95,
                "actions": [
                    {
                        "kind": "smalltalk",
                        "answer": "In Agra, Uttar Pradesh, India.",
                    }
                ],
            }
        ),
    )

    reply = assistant.handle(ALICE, "where is the Taj Mahal", update_id=11)

    assert reply.status == "completed"
    assert reply.text == "In Agra, Uttar Pradesh, India."
    with assistant_db() as session:
        assert session.query(Note).count() == 0
        assert session.query(AgentPendingAction).count() == 0


def test_smalltalk_length_cap_is_enforced(assistant_db):
    seed_owner(assistant_db, ALICE)
    assistant = build_assistant(
        assistant_db,
        FakeProvider(
            {
                "confidence": 0.95,
                "actions": [{"kind": "smalltalk", "answer": "word " * 200}],
            }
        ),
    )

    reply = assistant.handle(ALICE, "explain everything", update_id=12)

    assert reply.status == "failed"


def test_smalltalk_output_is_escaped(assistant_db):
    seed_owner(assistant_db, ALICE)
    assistant = build_assistant(
        assistant_db,
        FakeProvider(
            {
                "confidence": 0.95,
                "actions": [
                    {"kind": "smalltalk", "answer": "<script>alert(1)</script>"}
                ],
            }
        ),
    )

    reply = assistant.handle(ALICE, "say something", update_id=13)

    assert "<script>" not in reply.text
    assert "&lt;script&gt;" in reply.text


def test_unsupported_reply_preserves_the_safe_redirect(assistant_db):
    seed_owner(assistant_db, ALICE)
    assistant = build_assistant(
        assistant_db,
        FakeProvider(
            {
                "confidence": 0.99,
                "actions": [
                    {
                        "kind": "unsupported",
                        "reason": (
                            "I cannot book a cab, but I can set a reminder for "
                            "you to book one."
                        ),
                    }
                ],
            }
        ),
    )

    reply = assistant.handle(ALICE, "book me a cab", update_id=131)

    assert "cannot book a cab" in reply.text
    assert "set a reminder" in reply.text


def test_low_confidence_retrieval_still_answers(assistant_db):
    """The confidence floor guards writes; refusing a read helps nobody."""
    owner_id = seed_owner(assistant_db, ALICE)
    seed_note(
        assistant_db, owner_id, "Relocation", "Ask HR about relocation", "seed-note-1"
    )
    proposal = list_proposal("note")
    proposal["confidence"] = 0.35
    assistant = build_assistant(assistant_db, FakeProvider(proposal))

    reply = assistant.handle(ALICE, "uh show notes maybe", update_id=14)

    assert reply.status == "completed"
    assert "Ask HR about relocation" in reply.text


def test_low_confidence_voice_write_is_reviewed_instead_of_refused(assistant_db):
    seed_owner(assistant_db, ALICE)
    assistant = build_assistant(
        assistant_db,
        FakeProvider(
            {
                "confidence": 0.4,
                "actions": [
                    {
                        "kind": "create_note",
                        "body": "Ask HR about relocation",
                        "title": None,
                        "tags": [],
                    }
                ],
            }
        ),
    )

    reply = assistant.handle(
        ALICE,
        "note ask HR about relocation",
        update_id=15,
        review_required=True,
    )

    assert reply.status == "confirmation"
    assert "not fully sure" in reply.text
    with assistant_db() as session:
        assert session.query(Note).count() == 0


def test_low_confidence_text_write_still_asks_to_restate(assistant_db):
    seed_owner(assistant_db, ALICE)
    assistant = build_assistant(
        assistant_db,
        FakeProvider(
            {
                "confidence": 0.4,
                "actions": [
                    {
                        "kind": "create_note",
                        "body": "unclear",
                        "title": None,
                        "tags": [],
                    }
                ],
            }
        ),
    )

    reply = assistant.handle(ALICE, "mumble", update_id=16)

    assert reply.status == "clarification"
    with assistant_db() as session:
        assert session.query(Note).count() == 0


def test_mixed_read_and_write_still_requires_review(assistant_db):
    seed_owner(assistant_db, ALICE)
    assistant = build_assistant(
        assistant_db,
        FakeProvider(
            {
                "confidence": 0.95,
                "actions": [
                    {
                        "kind": "create_note",
                        "body": "Ravi needs the invoice",
                        "title": None,
                        "tags": [],
                    },
                    {
                        "kind": "list_records",
                        "record_type": "note",
                        "search": None,
                        "tag": None,
                        "status": None,
                        "start_date": None,
                        "end_date": None,
                        "limit": 10,
                        "timezone": "Asia/Kolkata",
                    },
                ],
            }
        ),
    )

    reply = assistant.handle(
        ALICE,
        "note that Ravi needs the invoice and show my notes",
        update_id=17,
        review_required=True,
    )

    assert reply.status == "confirmation"
    with assistant_db() as session:
        assert session.query(Note).count() == 0


def test_several_reads_are_answered_in_one_turn(assistant_db):
    owner_id = seed_owner(assistant_db, ALICE)
    seed_note(
        assistant_db, owner_id, "Relocation", "Ask HR about relocation", "seed-note-1"
    )
    assistant = build_assistant(
        assistant_db,
        FakeProvider(
            {
                "confidence": 0.95,
                "actions": [
                    {
                        "kind": "list_records",
                        "record_type": "note",
                        "search": None,
                        "tag": None,
                        "status": None,
                        "start_date": None,
                        "end_date": None,
                        "limit": 10,
                        "timezone": "Asia/Kolkata",
                    },
                    {
                        "kind": "list_records",
                        "record_type": "goal",
                        "search": None,
                        "tag": None,
                        "status": None,
                        "start_date": None,
                        "end_date": None,
                        "limit": 10,
                        "timezone": "Asia/Kolkata",
                    },
                ],
            }
        ),
    )

    reply = assistant.handle(
        ALICE,
        "show my notes and my goals",
        update_id=18,
        review_required=True,
    )

    assert reply.status == "completed"
    assert "Ask HR about relocation" in reply.text
    assert "No goals matched that." in reply.text


def test_retrieval_consumes_the_summary_quota(assistant_db):
    seed_owner(assistant_db, ALICE)
    assistant = build_assistant(
        assistant_db,
        FakeProvider(list_proposal("note"), list_proposal("note")),
        daily_summary_limit=1,
    )

    first = assistant.handle(ALICE, "show my notes", update_id=19)
    second = assistant.handle(ALICE, "show my notes again", update_id=20)

    assert first.status == "completed"
    assert second.status == "failed"


def test_a_plain_reply_continues_an_open_question(assistant_db):
    """The follow-up binds to the pending action without a slash command."""
    seed_owner(assistant_db, ALICE)
    assistant = build_assistant(
        assistant_db,
        FakeProvider(
            {
                "confidence": 0.95,
                "actions": [
                    {
                        "kind": "clarification",
                        "intended_kind": "create_ledger_entry",
                        "question": "Which currency was that?",
                        "missing_fields": ["currency"],
                        "known_arguments": {},
                    }
                ],
            },
            {
                "confidence": 0.95,
                "actions": [
                    {
                        "kind": "create_ledger_entry",
                        "direction": "expense",
                        "amount": "500",
                        "currency": "INR",
                        "description": "Lunch",
                        "category": None,
                    }
                ],
            },
        ),
    )

    asked = assistant.handle(ALICE, "I spent 500", update_id=30)
    open_id = assistant.open_clarification_id(ALICE.telegram_id)
    answered = assistant.answer_clarification(ALICE, open_id, "rupees")

    assert asked.status == "clarification"
    assert open_id == asked.pending_id
    assert answered.status == "completed"


def test_no_open_question_means_no_pending_id(assistant_db):
    seed_owner(assistant_db, ALICE)
    assistant = build_assistant(assistant_db, FakeProvider())

    assert assistant.open_clarification_id(ALICE.telegram_id) is None


def test_an_open_question_is_not_visible_to_another_tenant(assistant_db):
    seed_owner(assistant_db, ALICE)
    seed_owner(assistant_db, BOB)
    assistant = build_assistant(
        assistant_db,
        FakeProvider(
            {
                "confidence": 0.95,
                "actions": [
                    {
                        "kind": "clarification",
                        "intended_kind": "create_ledger_entry",
                        "question": "Which currency was that?",
                        "missing_fields": ["currency"],
                        "known_arguments": {},
                    }
                ],
            }
        ),
    )

    assistant.handle(ALICE, "I spent 500", update_id=31)

    assert assistant.open_clarification_id(BOB.telegram_id) is None


def test_an_expired_question_is_not_continued(assistant_db):
    seed_owner(assistant_db, ALICE)
    assistant = build_assistant(
        assistant_db,
        FakeProvider(
            {
                "confidence": 0.95,
                "actions": [
                    {
                        "kind": "clarification",
                        "intended_kind": "create_ledger_entry",
                        "question": "Which currency was that?",
                        "missing_fields": ["currency"],
                        "known_arguments": {},
                    }
                ],
            }
        ),
        pending_ttl_minutes=5,
    )

    assistant.handle(ALICE, "I spent 500", update_id=32)
    assistant.clock = lambda: datetime.now(UTC) + timedelta(minutes=10)

    assert assistant.open_clarification_id(ALICE.telegram_id) is None


def test_the_global_ceiling_degrades_gracefully_for_everyone(assistant_db):
    """At capacity the bot says so plainly instead of failing obscurely."""
    seed_owner(assistant_db, ALICE)
    seed_owner(assistant_db, BOB)
    assistant = build_assistant(
        assistant_db,
        FakeProvider(list_proposal("note"), list_proposal("note")),
        global_daily_ai_limit=1,
    )

    first = assistant.handle(ALICE, "show my notes", update_id=40)
    second = assistant.handle(BOB, "show my notes", update_id=41)

    assert first.status == "completed"
    assert second.status == "rejected"
    assert "at capacity" in second.text


def test_no_global_ceiling_by_default(assistant_db):
    seed_owner(assistant_db, ALICE)
    assistant = build_assistant(
        assistant_db,
        FakeProvider(list_proposal("note"), list_proposal("note")),
    )

    first = assistant.handle(ALICE, "show my notes", update_id=42)
    second = assistant.handle(ALICE, "show my notes", update_id=43)

    assert first.status == "completed"
    assert second.status == "completed"


def clarification_proposal(question: str, kind: str = "create_ledger_entry") -> dict:
    return {
        "confidence": 0.95,
        "actions": [
            {
                "kind": "clarification",
                "intended_kind": kind,
                "question": question,
                "missing_fields": ["currency"],
                "known_arguments": {},
            }
        ],
    }


def test_a_question_loop_is_cut_off_instead_of_repeating(assistant_db):
    """The screenshot failure: ask, answer, ask again, forever."""
    seed_owner(assistant_db, ALICE)
    assistant = build_assistant(
        assistant_db,
        FakeProvider(
            clarification_proposal("Which currency?"),
            clarification_proposal("Which currency exactly?"),
            clarification_proposal("Sorry, which currency?"),
            clarification_proposal("Please state the currency."),
        ),
    )

    first = assistant.handle(ALICE, "I spent 500", update_id=50)
    pending_id = first.pending_id
    second = assistant.answer_clarification(ALICE, pending_id, "rupees")
    third = assistant.answer_clarification(ALICE, pending_id, "rupees again")

    assert first.status == "clarification"
    assert second.status == "clarification"
    # The third round must stop rather than ask a fourth time.
    assert third.status == "cancelled"
    assert "stopped asking" in third.text


def test_an_abandoned_question_does_not_stay_open(assistant_db):
    seed_owner(assistant_db, ALICE)
    assistant = build_assistant(
        assistant_db,
        FakeProvider(
            clarification_proposal("Which currency?"),
            clarification_proposal("Which currency exactly?"),
            clarification_proposal("Sorry, which currency?"),
        ),
    )

    first = assistant.handle(ALICE, "I spent 500", update_id=51)
    assistant.answer_clarification(ALICE, first.pending_id, "rupees")
    assistant.answer_clarification(ALICE, first.pending_id, "rupees again")

    # A dead question must not capture the user's next unrelated request.
    assert assistant.open_clarification_id(ALICE.telegram_id) is None


def test_the_provider_is_told_when_it_is_the_final_round(assistant_db):
    seed_owner(assistant_db, ALICE)
    provider = FakeProvider(
        clarification_proposal("Which currency?"),
        clarification_proposal("Which currency exactly?"),
    )
    assistant = build_assistant(assistant_db, provider)

    first = assistant.handle(ALICE, "I spent 500", update_id=52)
    assistant.answer_clarification(ALICE, first.pending_id, "rupees")

    _, context = provider.contexts[-1]
    assert context["clarification_round"] == 1
    assert context["final_round"] is False
    assert context["clarification_question"] == "Which currency?"


def test_a_successful_answer_still_completes_normally(assistant_db):
    seed_owner(assistant_db, ALICE)
    assistant = build_assistant(
        assistant_db,
        FakeProvider(
            clarification_proposal("Which currency?"),
            {
                "confidence": 0.95,
                "actions": [
                    {
                        "kind": "create_ledger_entry",
                        "direction": "expense",
                        "amount": "500",
                        "currency": "INR",
                        "description": "Transport",
                        "category": None,
                    }
                ],
            },
        ),
    )

    first = assistant.handle(ALICE, "I spent 500", update_id=53)
    answered = assistant.answer_clarification(ALICE, first.pending_id, "rupees")

    assert answered.status == "completed"
