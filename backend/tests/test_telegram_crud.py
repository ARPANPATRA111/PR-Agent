from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from bot import BotHandler
from config import settings
from models import TelegramMessage
from public_models import (
    LedgerEntry,
    Note,
    NutritionLog,
    PublicBase,
    Reminder,
    TrackedGoal,
    WorkLog,
)


class FakeTelegramClient:
    def __init__(self):
        self.messages: list[str] = []

    async def send_message(self, chat_id, text, **kwargs):
        del chat_id, kwargs
        self.messages.append(text)
        return {"ok": True}

    async def send_typing_action(self, chat_id):
        del chat_id


class FakeMemory:
    def __init__(self, factory):
        self.factory = factory

    @contextmanager
    def get_session(self):
        session = self.factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


class FailingAgent:
    def __getattr__(self, name):
        raise AssertionError(f"AI provider must not be called: {name}")


def telegram_message(text: str, message_id: int = 1) -> TelegramMessage:
    return TelegramMessage.model_validate(
        {
            "message_id": message_id,
            "date": int(datetime.now(timezone.utc).timestamp()),
            "chat": {"id": 9001},
            "from": {
                "id": 1001,
                "first_name": "Public",
                "username": "public_user",
            },
            "text": text,
        }
    )


@pytest.fixture()
def bot_and_factory():
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
    bot = BotHandler.__new__(BotHandler)
    bot.telegram = FakeTelegramClient()
    bot.memory = FakeMemory(factory)
    bot.agent = FailingAgent()
    try:
        yield bot, factory
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_explicit_crud_commands_work_with_ai_provider_down(bot_and_factory):
    bot, factory = bot_and_factory
    future = datetime.now(timezone.utc) + timedelta(days=2)
    commands = [
        telegram_message("/log Completed deterministic CRUD", 1),
        telegram_message("/note Remember tenant isolation", 2),
        telegram_message("/expense 240.50 INR dinner", 3),
        telegram_message("/goal Ship public beta", 4),
        telegram_message(
            f"/remind once {future:%Y-%m-%d} {future:%H:%M} UTC Review beta",
            5,
        ),
    ]
    for command in commands:
        await bot._handle_command(command)

    session = factory()
    try:
        assert session.query(WorkLog).count() == 1
        assert session.query(Note).count() == 1
        assert session.query(LedgerEntry).one().amount_minor == 24050
        assert session.query(TrackedGoal).count() == 1
        assert session.query(Reminder).count() == 1
    finally:
        session.close()
    assert all("✅" in message for message in bot.telegram.messages)


@pytest.mark.asyncio
async def test_telegram_retry_is_idempotent_and_edit_delete_use_services(
    bot_and_factory,
):
    bot, factory = bot_and_factory
    create = telegram_message("/note First version", 20)
    await bot._handle_command(create)
    await bot._handle_command(create)
    await bot._handle_command(telegram_message("/editnote 1 Second version", 21))
    await bot._handle_command(telegram_message("/pin 1", 22))

    session = factory()
    try:
        note = session.query(Note).one()
        assert note.body == "Second version"
        assert note.pinned is True
        assert note.version == 3
    finally:
        session.close()

    await bot._handle_command(telegram_message("/deletenote 1", 23))
    session = factory()
    try:
        assert session.query(Note).count() == 0
    finally:
        session.close()


@pytest.mark.asyncio
async def test_command_output_escapes_user_html(bot_and_factory):
    bot, _ = bot_and_factory
    await bot._handle_command(telegram_message("/note <script>alert(1)</script>", 30))
    await bot._handle_command(telegram_message("/notes", 31))
    output = bot.telegram.messages[-1]
    assert "<script>" not in output
    assert "&lt;script&gt;" in output


@pytest.mark.asyncio
async def test_food_preview_confirm_edit_summary_and_delete(
    bot_and_factory,
    monkeypatch,
):
    bot, factory = bot_and_factory
    monkeypatch.setattr(settings, "nutrition_provider", "reference")
    await bot._handle_command(
        telegram_message(
            "/food 50 g paneer and one glass of milk",
            40,
        )
    )
    assert "approximately" in bot.telegram.messages[-1].lower()
    assert "/confirmfood 1" in bot.telegram.messages[-1]

    await bot._handle_command(telegram_message("/confirmfood 1", 41))
    await bot._handle_command(telegram_message("/editfood 1 1 100 g 300 20", 42))
    await bot._handle_command(telegram_message("/nutrition", 43))
    assert "approximately" in bot.telegram.messages[-1].lower()

    await bot._handle_command(telegram_message("/deletefood 1", 44))
    session = factory()
    try:
        assert session.query(NutritionLog).count() == 0
    finally:
        session.close()


@pytest.mark.asyncio
async def test_food_provider_outage_preserves_original_draft(
    bot_and_factory,
    monkeypatch,
):
    bot, factory = bot_and_factory
    monkeypatch.setattr(settings, "nutrition_provider", "disabled")
    await bot._handle_command(telegram_message("/food 100 g paneer", 50))
    assert "original entry preserved" in bot.telegram.messages[-1].lower()
    session = factory()
    try:
        draft = session.query(NutritionLog).one()
        assert draft.original_text == "100 g paneer"
        assert draft.estimation_source == "provider_unavailable"
    finally:
        session.close()
