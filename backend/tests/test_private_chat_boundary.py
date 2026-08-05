"""A personal record must never be read or written from a shared chat."""

from __future__ import annotations

import pytest

from config import settings
from models import TelegramMessage, TelegramUpdate


@pytest.fixture()
def bot(monkeypatch):
    import bot as bot_module

    handler = bot_module.BotHandler.__new__(bot_module.BotHandler)
    handler.telegram = RecordingTelegram()
    handler.bounded_assistant = ExplodingAssistant()
    handler.agent = None
    handler.memory = None
    monkeypatch.setattr(settings, "public_v2_enabled", True)
    monkeypatch.setattr(settings, "invite_only", False)
    monkeypatch.setattr(settings, "ai_agent_enabled", True)
    return handler


class RecordingTelegram:
    def __init__(self):
        self.messages: list[str] = []
        self.callback_answers: list[str] = []

    async def send_message(self, chat_id, text, **kwargs):
        self.messages.append(text)
        return {"result": {"message_id": 1}}

    async def answer_callback_query(self, callback_query_id, text=None, **kwargs):
        self.callback_answers.append(text or "")

    async def send_typing_action(self, chat_id):
        return None

    async def delete_message(self, chat_id, message_id):
        return None


class ExplodingAssistant:
    """Any call means a shared chat reached the tenant-scoped code path."""

    def open_clarification_id(self, telegram_id):
        raise AssertionError("assistant reached from a non-private chat")

    def handle(self, *args, **kwargs):
        raise AssertionError("assistant reached from a non-private chat")

    def confirm(self, *args, **kwargs):
        raise AssertionError("assistant reached from a non-private chat")

    def cancel(self, *args, **kwargs):
        raise AssertionError("assistant reached from a non-private chat")

    def choose(self, *args, **kwargs):
        raise AssertionError("assistant reached from a non-private chat")


def message_in(chat_type: str, text: str = "show me all my notes") -> TelegramUpdate:
    return TelegramUpdate(
        update_id=900,
        message=TelegramMessage(
            message_id=5,
            date=1_760_000_000,
            chat={"id": -1001234567890, "type": chat_type},
            **{"from": {"id": 1001, "first_name": "Alice"}},
            text=text,
        ),
    )


@pytest.mark.parametrize(
    "chat_type",
    ["group", "supergroup", "channel", "", "unknown"],
)
@pytest.mark.asyncio
async def test_shared_chats_are_refused_before_any_record_is_touched(bot, chat_type):
    await bot.handle_update(message_in(chat_type))

    assert len(bot.telegram.messages) == 1
    assert "direct message" in bot.telegram.messages[0]


@pytest.mark.asyncio
async def test_a_command_in_a_group_is_refused_too(bot):
    await bot.handle_update(message_in("supergroup", text="/notes"))

    assert len(bot.telegram.messages) == 1
    assert "direct message" in bot.telegram.messages[0]


@pytest.mark.asyncio
async def test_a_group_refusal_is_not_queued_for_delayed_cleanup(bot, monkeypatch):
    captured = {}

    async def capture(chat_id, text, **kwargs):
        captured.update(kwargs)
        return {"result": {"message_id": 1}}

    monkeypatch.setattr(bot.telegram, "send_message", capture)
    await bot.handle_update(message_in("group"))

    assert captured.get("queue_cleanup") is False


@pytest.mark.asyncio
async def test_a_button_tapped_in_a_group_resolves_nothing(bot):
    update = TelegramUpdate(
        update_id=901,
        callback_query={
            "id": "cb-1",
            "from": {"id": 1001, "first_name": "Alice"},
            "data": "agent:confirm:7",
            "message": {
                "message_id": 6,
                "date": 1_760_000_000,
                "chat": {"id": -1001234567890, "type": "supergroup"},
            },
        },
    )

    await bot.handle_update(update)

    assert bot.telegram.callback_answers == ["This only works in a direct message."]
    assert bot.telegram.messages == []


def test_private_chat_is_still_allowed(bot):
    assert bot._is_private_chat({"id": 1001, "type": "private"}) is True
    assert bot._is_private_chat({"id": -100, "type": "group"}) is False
    assert bot._is_private_chat({}) is False
    assert bot._is_private_chat(None) is False
