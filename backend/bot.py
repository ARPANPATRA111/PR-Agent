import logging
import asyncio
from math import ceil
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, List

import httpx

from assistant import ActorContext, AssistantReply, BoundedAssistant
from assistant.providers import ProviderUnavailable, get_intent_provider
from abuse_controls import (
    BetaAccessRequired,
    InviteService,
    QuotaExceeded,
    QuotaService,
)
from config import settings
from domain.errors import DomainError
from domain.services import DomainServices
from models import (
    TelegramUpdate,
    TelegramMessage,
    RawEntry,
    StructuredEntry,
    EntryCategory,
    StatusResponse,
    ReportFeedback,
)
from memory import get_memory_manager
from llm_agent import get_llm_agent
from nutrition.providers import get_nutrition_provider
from telegram_commands import DeterministicCommandMixin
from utils import (
    daily_voice_unit_limit,
    transcribe_telegram_voice,
    validate_voice_metadata,
    voice_quota_units,
    format_streak,
    format_duration,
    extract_keywords,
    get_day_boundaries,
)

logger = logging.getLogger(__name__)


class TelegramClient:
    def __init__(self, token: str):
        self.token = token
        self.base_url = f"https://api.telegram.org/bot{token}"
        self._max_retries = 3
        self._base_delay = 1.0

    async def _request_with_retry(self, method: str, endpoint: str, **kwargs) -> dict:
        import asyncio
        import random

        last_error = None

        for attempt in range(self._max_retries + 1):
            try:
                async with httpx.AsyncClient() as client:
                    if method.upper() == "GET":
                        response = await client.get(
                            f"{self.base_url}/{endpoint}", timeout=30, **kwargs
                        )
                    else:
                        response = await client.post(
                            f"{self.base_url}/{endpoint}", timeout=30, **kwargs
                        )

                    result = response.json()

                    if not result.get("ok") and result.get("error_code") == 429:
                        retry_after = result.get("parameters", {}).get("retry_after", 5)
                        logger.warning(
                            f"Rate limited by Telegram. Waiting {retry_after}s..."
                        )
                        await asyncio.sleep(retry_after)
                        continue

                    return result

            except (httpx.TimeoutException, httpx.NetworkError) as e:
                last_error = e

                if attempt < self._max_retries:
                    delay = self._base_delay * (2**attempt) + random.random()
                    logger.warning(
                        "Telegram API request failed; retrying",
                        extra={
                            "error_category": type(e).__name__,
                            "attempt": attempt + 1,
                        },
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        "Telegram API retries exhausted",
                        extra={"error_category": type(e).__name__},
                    )
                    raise

        raise last_error

    async def send_message(
        self,
        chat_id: int,
        text: str,
        parse_mode: str = "HTML",
        reply_to_message_id: Optional[int] = None,
        reply_markup: Optional[dict] = None,
        queue_cleanup: bool = True,
    ) -> dict:
        payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}

        if reply_to_message_id:
            payload["reply_to_message_id"] = reply_to_message_id
        if reply_markup:
            payload["reply_markup"] = reply_markup

        result = await self._request_with_retry(
            "POST",
            "sendMessage",
            json=payload,
        )
        if settings.message_cleanup_enabled and queue_cleanup and result.get("ok"):
            message_id = (result.get("result") or {}).get("message_id")
            if message_id is not None:
                try:
                    await asyncio.to_thread(
                        self._queue_outbound_cleanup,
                        chat_id,
                        int(message_id),
                    )
                except Exception:
                    logger.exception("Unable to queue outbound Telegram cleanup")
        return result

    @staticmethod
    def _queue_outbound_cleanup(chat_id: int, message_id: int) -> None:
        from telegram_cleanup import queue_telegram_message

        memory = get_memory_manager()
        now = datetime.now(timezone.utc)
        with memory.get_session() as session:
            queue_telegram_message(
                session,
                telegram_id=chat_id,
                chat_id=chat_id,
                message_id=message_id,
                direction="outbound",
                purpose="bot_response",
                processed_at=now,
                delete_after=now
                + timedelta(seconds=settings.message_cleanup_delay_seconds),
            )

    async def delete_message(self, chat_id: int, message_id: int) -> dict:
        return await self._request_with_retry(
            "POST",
            "deleteMessage",
            json={"chat_id": chat_id, "message_id": message_id},
        )

    async def answer_callback_query(
        self,
        callback_query_id: str,
        text: str | None = None,
    ) -> dict:
        payload = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text[:200]
        return await self._request_with_retry(
            "POST",
            "answerCallbackQuery",
            json=payload,
        )

    async def send_typing_action(self, chat_id: int) -> None:
        try:
            await self._request_with_retry(
                "POST", "sendChatAction", json={"chat_id": chat_id, "action": "typing"}
            )
        except Exception:
            pass

    async def set_webhook(self, url: str, secret_token: str) -> dict:
        if not secret_token:
            raise ValueError("Telegram webhook secret is required")
        return await self._request_with_retry(
            "POST",
            "setWebhook",
            json={
                "url": url,
                "secret_token": secret_token,
                "allowed_updates": ["message", "callback_query"],
            },
        )

    async def delete_webhook(self) -> dict:
        return await self._request_with_retry("POST", "deleteWebhook")

    async def get_webhook_info(self) -> dict:
        return await self._request_with_retry("GET", "getWebhookInfo")


class BotHandler(DeterministicCommandMixin):
    def __init__(self):
        self.telegram = TelegramClient(settings.telegram_bot_token)
        self.memory = get_memory_manager()
        self.agent = None if settings.public_v2_enabled else get_llm_agent()
        self.bounded_assistant: BoundedAssistant | None = None

    async def handle_update(self, update: TelegramUpdate) -> None:
        if update.callback_query:
            await self._handle_callback_update(update)
            return
        if not update.message:
            logger.debug("Update has no message, skipping")
            return

        message = update.message
        chat_id = message.chat.get("id")
        user_id = message.from_user.id if message.from_user else None

        # Everything this bot stores is one person's private record. In a group
        # the reply, and every listing inside it, would be readable by every
        # member, so refuse before any record is read or written.
        if not self._is_private_chat(message.chat):
            await self._decline_group_chat(chat_id)
            return

        if message.pinned_message is not None:
            await asyncio.to_thread(
                self._protect_pinned_message,
                int(chat_id),
                message.pinned_message.message_id,
            )
            return

        try:
            if settings.public_v2_enabled and settings.invite_only:
                try:
                    await asyncio.to_thread(
                        self._require_beta_access,
                        message,
                    )
                except BetaAccessRequired:
                    await self.telegram.send_message(
                        chat_id,
                        "Beta access is required. If you have an invite, send "
                        "<code>/start YOUR_INVITE_CODE</code>.",
                    )
                    return

            if message.from_user and not settings.public_v2_enabled:
                await asyncio.to_thread(
                    self.memory.get_or_create_user,
                    telegram_id=message.from_user.id,
                    first_name=message.from_user.first_name,
                    last_name=message.from_user.last_name,
                    username=message.from_user.username,
                )

            spoken = message.spoken_audio
            if spoken is not None:
                if settings.public_v2_enabled:
                    await self._handle_bounded_voice(message, update.update_id)
                else:
                    await self._handle_voice(message)
            elif message.text or message.caption:
                body = message.text or message.caption or ""
                if body.startswith("/"):
                    await self._handle_command(message)
                elif settings.public_v2_enabled:
                    await self._handle_bounded_text(message, update.update_id)
                else:
                    await self._handle_text(message)
            else:
                await self.telegram.send_message(
                    chat_id,
                    "🎙️ Send me a voice note, or type what you want to record. "
                    "I can also read forwarded voice messages and audio files.",
                )

        except Exception:
            logger.exception("Telegram update handler failed")
            await self.telegram.send_message(
                chat_id, "❌ Sorry, something went wrong. Please try again."
            )

    async def _handle_callback_update(self, update: TelegramUpdate) -> None:
        callback = update.callback_query
        if callback is None or callback.message is None:
            return
        actor_message = TelegramMessage(
            message_id=callback.message.message_id,
            date=callback.message.date,
            chat=callback.message.chat,
            from_user=callback.from_user,
            text=callback.data,
        )
        chat_id = actor_message.chat.get("id")
        try:
            if not self._is_private_chat(actor_message.chat):
                await self.telegram.answer_callback_query(
                    callback.id,
                    "This only works in a direct message.",
                )
                return
            if settings.public_v2_enabled and settings.invite_only:
                await asyncio.to_thread(self._require_beta_access, actor_message)
            parts = (callback.data or "").split(":")
            if (
                len(parts) not in {3, 4}
                or parts[0] != "agent"
                or not parts[2].isdigit()
                or (len(parts) == 4 and not parts[3].isdigit())
            ):
                await self.telegram.answer_callback_query(
                    callback.id,
                    "This action is no longer available.",
                )
                return
            pending_id = int(parts[2])
            assistant = self._get_bounded_assistant()
            if parts[1] == "pick" and len(parts) == 4:
                reply = await asyncio.to_thread(
                    assistant.choose,
                    self._actor(actor_message),
                    pending_id,
                    int(parts[3]),
                )
                callback_text = (
                    "Selected" if reply.status == "confirmation" else "Unavailable"
                )
            elif parts[1] == "confirm":
                reply = await asyncio.to_thread(
                    assistant.confirm,
                    self._actor(actor_message),
                    pending_id,
                )
                callback_text = "Saved" if reply.status == "completed" else "Not saved"
            elif parts[1] == "cancel":
                cancelled = await asyncio.to_thread(
                    assistant.cancel,
                    self._actor(actor_message),
                    pending_id,
                )
                callback_text = "Cancelled"
                reply = AssistantReply(
                    "Nothing was saved. Send a new voice note and I will try again.",
                    cancelled.status,
                )
            else:
                await self.telegram.answer_callback_query(
                    callback.id,
                    "Unsupported action.",
                )
                return
            await self.telegram.answer_callback_query(callback.id, callback_text)
            await self._send_assistant_reply(chat_id, reply)
            try:
                await self.telegram.delete_message(
                    chat_id,
                    callback.message.message_id,
                )
            except Exception:
                logger.warning(
                    "Unable to remove resolved Telegram confirmation",
                    extra={"callback_stage": "confirmation_cleanup"},
                )
        except BetaAccessRequired:
            await self.telegram.answer_callback_query(
                callback.id,
                "Beta access is required.",
            )
        except ProviderUnavailable:
            await self.telegram.answer_callback_query(
                callback.id,
                "The assistant is unavailable.",
            )
        except Exception:
            logger.exception("Telegram callback handling failed")
            await self.telegram.answer_callback_query(
                callback.id,
                "Please try again.",
            )

    @staticmethod
    def _is_private_chat(chat: dict) -> bool:
        """Treat anything that is not a one-to-one chat as unsafe to answer.

        An unknown or missing chat type is refused rather than assumed private,
        because the cost of guessing wrong is publishing someone's records.
        """
        return str((chat or {}).get("type", "")).lower() == "private"

    async def _decline_group_chat(self, chat_id: int) -> None:
        await self.telegram.send_message(
            chat_id,
            "🔒 I only work in a direct message, because everything I store is "
            "private to one account. Open a private chat with me and send your "
            "voice note there.",
            queue_cleanup=False,
        )

    def _require_beta_access(self, message: TelegramMessage) -> None:
        if message.from_user is None:
            raise BetaAccessRequired()
        invite_code = None
        parts = (message.text or "").split(maxsplit=1)
        if parts and parts[0].lower() == "/start" and len(parts) == 2:
            invite_code = parts[1].strip()
        with self.memory.get_session() as session:
            owner = DomainServices(session).ensure_owner(
                telegram_id=message.from_user.id,
                first_name=message.from_user.first_name,
                last_name=message.from_user.last_name,
                username=message.from_user.username,
            )
            invites = InviteService(session)
            invite_claimed = False
            if invite_code:
                try:
                    invites.claim(owner.id, invite_code)
                    invite_claimed = True
                except DomainError as exc:
                    raise BetaAccessRequired() from exc
            if not invite_claimed and not invites.has_access(owner.id):
                raise BetaAccessRequired()

    @staticmethod
    def _protect_pinned_message(chat_id: int, message_id: int) -> None:
        from telegram_cleanup import protect_pinned_telegram_message

        memory = get_memory_manager()
        with memory.get_session() as session:
            protect_pinned_telegram_message(
                session,
                chat_id=chat_id,
                message_id=message_id,
            )

    async def _handle_voice(self, message: TelegramMessage) -> None:
        chat_id = message.chat.get("id")
        user_id = message.from_user.id if message.from_user else 0

        await self.telegram.send_typing_action(chat_id)

        await self.telegram.send_message(
            chat_id,
            "🎙️ Got your voice note! Processing...",
            reply_to_message_id=message.message_id,
        )

        try:
            logger.info(f"Transcribing voice note from user {user_id}")
            transcript = await transcribe_telegram_voice(
                message.voice.file_id, settings.telegram_bot_token
            )

            if not transcript or len(transcript.strip()) < 10:
                await self.telegram.send_message(
                    chat_id,
                    "🔇 I couldn't hear anything clear in that recording. Could you try again?",
                )
                return

            validation = self.agent.validate_content_relevance(transcript)
            if not validation["is_relevant"] and validation["confidence"] > 0.7:
                logger.warning(
                    f"Content not relevant for user {user_id}: {validation['reason']}"
                )
                await self.telegram.send_message(
                    chat_id,
                    f"⚠️ <b>Content Not Related</b>\n\n"
                    f"This doesn't seem to be about work or learning progress.\n\n"
                    f"📋 <b>Detected:</b> {validation['category'].title()}\n"
                    f"💡 <b>Tip:</b> Share updates about coding, learning, meetings, blockers, or achievements!\n\n"
                    f"<i>If you think this is a mistake, try rephrasing your update.</i>",
                    parse_mode="HTML",
                )
                return

            logger.info(f"Classifying transcript: {len(transcript)} chars")
            classification = self.agent.classify_entry(transcript)

            raw_entry = RawEntry(
                telegram_id=user_id,
                telegram_message_id=message.message_id,
                timestamp=datetime.utcfromtimestamp(message.date),
                audio_file_id=message.voice.file_id,
                audio_duration=message.voice.duration,
                transcript=transcript,
            )
            raw_entry_id = self.memory.save_raw_entry(raw_entry)

            structured_entry = StructuredEntry(
                raw_entry_id=raw_entry_id,
                category=classification.category,
                activities=classification.activities,
                blockers=classification.blockers,
                accomplishments=classification.accomplishments,
                learnings=classification.learnings,
                summary=classification.summary,
                keywords=classification.keywords,
                sentiment=classification.sentiment,
            )
            self.memory.save_structured_entry(structured_entry)

            keywords_str = (
                ",".join(classification.keywords) if classification.keywords else ""
            )
            self.memory.add_to_vector_memory(
                entry_id=raw_entry_id,
                text=transcript,
                metadata={
                    "telegram_id": user_id,
                    "category": classification.category.value,
                    "timestamp": datetime.utcnow().isoformat(),
                    "keywords": keywords_str,
                },
            )

            streak = self.memory.update_user_streak(user_id)

            category_emoji = self._get_category_emoji(classification.category)
            duration_str = format_duration(message.voice.duration)
            streak_str = format_streak(streak)

            response = f"""✅ <b>Entry Logged!</b>

{category_emoji} <b>Category:</b> {classification.category.value.title()}

📝 <b>Summary:</b>
{classification.summary}

{self._format_entry_details(classification)}

{streak_str}

<i>Duration: {duration_str}</i>"""

            await self.telegram.send_message(chat_id, response)

            logger.info(f"Successfully processed voice note for user {user_id}")

        except Exception as e:
            logger.error(f"Error processing voice note: {e}", exc_info=True)
            await self.telegram.send_message(
                chat_id, "❌ Error processing your voice note. Please try again."
            )

    def _get_category_emoji(self, category: EntryCategory) -> str:
        emojis = {
            EntryCategory.CODING: "💻",
            EntryCategory.LEARNING: "📚",
            EntryCategory.DEBUGGING: "🐛",
            EntryCategory.RESEARCH: "🔍",
            EntryCategory.MEETING: "👥",
            EntryCategory.PLANNING: "📋",
            EntryCategory.BLOCKERS: "🚧",
            EntryCategory.ACHIEVEMENT: "🏆",
            EntryCategory.OTHER: "📌",
        }
        return emojis.get(category, "📌")

    def _format_entry_details(self, classification) -> str:
        parts = []

        if classification.activities:
            parts.append(
                f"🎯 <b>Activities:</b> {', '.join(classification.activities[:3])}"
            )

        if classification.accomplishments:
            parts.append(
                f"✨ <b>Done:</b> {', '.join(classification.accomplishments[:3])}"
            )

        if classification.blockers:
            parts.append(
                f"⚠️ <b>Blockers:</b> {', '.join(classification.blockers[:2])}"
            )

        if classification.learnings:
            parts.append(
                f"💡 <b>Learned:</b> {', '.join(classification.learnings[:2])}"
            )

        return "\n".join(parts) if parts else ""

    async def _handle_command(self, message: TelegramMessage) -> None:
        chat_id = message.chat.get("id")
        command = message.text.split()[0].lower()

        commands = {
            "/start": self._cmd_start,
            "/help": self._cmd_help,
            "/log": self._v2_create_work_log,
            "/logs": self._v2_list_work_logs,
            "/editlog": self._v2_edit_work_log,
            "/deletelog": self._v2_delete_work_log,
            "/note": self._v2_create_note,
            "/notes": self._v2_list_notes,
            "/editnote": self._v2_edit_note,
            "/deletenote": self._v2_delete_note,
            "/pin": self._v2_toggle_note_pin,
            "/expense": self._v2_create_expense,
            "/income": self._v2_create_income,
            "/ledger": self._v2_list_ledger,
            "/editledger": self._v2_edit_ledger,
            "/deleteledger": self._v2_delete_ledger,
            "/remind": self._v2_create_reminder,
            "/reminders": self._v2_list_reminders,
            "/editreminder": self._v2_edit_reminder,
            "/pausereminder": self._v2_pause_reminder,
            "/resumereminder": self._v2_resume_reminder,
            "/deletereminder": self._v2_delete_reminder,
            "/food": self._v2_create_food,
            "/nutrition": self._v2_nutrition_summary,
            "/confirmfood": self._v2_confirm_food,
            "/savefoodnote": self._v2_save_unestimated_food,
            "/editfood": self._v2_edit_food_item,
            "/deletefood": self._v2_delete_food,
            "/nutritiontargets": self._v2_nutrition_targets,
            "/goal": self._v2_create_goal,
            "/set_goal": self._v2_create_goal,
            "/goals": self._v2_list_goals,
            "/editgoal": self._v2_edit_goal,
            "/goalprogress": self._v2_progress_goal,
            "/completegoal": self._v2_complete_goal,
            "/pausegoal": self._v2_pause_goal,
            "/deletegoal": self._v2_delete_goal,
            "/answeragent": self._v2_answer_agent,
            "/confirmagent": self._v2_confirm_agent,
            "/cancelagent": self._v2_cancel_agent,
        }
        if settings.public_v2_enabled:
            commands.update(
                {
                    "/today": self._v2_today_summary,
                    "/week": self._v2_week_summary,
                    "/summary": self._v2_week_summary,
                    "/spending": self._v2_spending_summary,
                    "/settings": self._v2_settings_link,
                    "/export": self._v2_export_link,
                    "/deleteaccount": self._v2_delete_account_link,
                }
            )
        else:
            commands.update(
                {
                    "/status": self._cmd_status,
                    "/summary": self._cmd_summary,
                    "/stats": self._cmd_status,
                    "/delete": self._cmd_delete,
                    "/recent": self._cmd_recent,
                }
            )

        handler = commands.get(command)

        if handler:
            await handler(message)
        else:
            await self.telegram.send_message(
                chat_id, "❓ Unknown command. Use /help to see available commands."
            )

    def _get_bounded_assistant(self) -> BoundedAssistant:
        if self.bounded_assistant is None:
            self.bounded_assistant = BoundedAssistant(
                self.memory.SessionLocal,
                get_intent_provider(),
                get_nutrition_provider(settings.nutrition_provider),
                min_confidence=settings.ai_agent_min_confidence,
                pending_ttl_minutes=settings.agent_pending_ttl_minutes,
                max_input_length=settings.max_agent_input_length,
                daily_ai_limit=settings.per_user_daily_ai_limit,
                daily_summary_limit=settings.per_user_daily_summary_limit,
                global_daily_ai_limit=settings.global_daily_ai_limit,
            )
        return self.bounded_assistant

    @staticmethod
    def _choice_label(label: str, limit: int = 60) -> str:
        """Telegram button text is short, so keep the recognisable part."""
        normalized = " ".join((label or "").split()) or "Untitled"
        return normalized if len(normalized) <= limit else normalized[: limit - 1] + "…"

    @staticmethod
    def _actor(message: TelegramMessage) -> ActorContext:
        if message.from_user is None:
            raise ValueError("Telegram user identity is required")
        return ActorContext(
            telegram_id=message.from_user.id,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
            username=message.from_user.username,
        )

    async def _send_assistant_reply(
        self,
        chat_id: int,
        reply: AssistantReply,
    ) -> None:
        reply_markup = None
        if reply.status == "confirmation" and reply.pending_id is not None:
            reply_markup = {
                "inline_keyboard": [
                    [
                        {
                            "text": "✅ Correct",
                            "callback_data": f"agent:confirm:{reply.pending_id}",
                        },
                        {
                            "text": "❌ Wrong",
                            "callback_data": f"agent:cancel:{reply.pending_id}",
                        },
                    ]
                ]
            }
        elif reply.status == "disambiguation" and reply.pending_id is not None:
            # One row per candidate keeps the record id in callback data, so
            # the user picks by reading the record instead of quoting a number.
            rows = [
                [
                    {
                        "text": self._choice_label(label),
                        "callback_data": (
                            f"agent:pick:{reply.pending_id}:{record_id}"
                        ),
                    }
                ]
                for record_id, label in reply.options
            ]
            rows.append(
                [
                    {
                        "text": "❌ Cancel",
                        "callback_data": f"agent:cancel:{reply.pending_id}",
                    }
                ]
            )
            reply_markup = {"inline_keyboard": rows}
        await self.telegram.send_message(
            chat_id,
            reply.text,
            reply_markup=reply_markup,
        )

    async def _handle_bounded_text(
        self,
        message: TelegramMessage,
        update_id: int,
    ) -> None:
        if len(message.text or "") > settings.max_agent_input_length:
            await self.telegram.send_message(
                message.chat.get("id"),
                "That message is too long. Please split it into smaller entries.",
            )
            return
        if not settings.ai_agent_enabled:
            await self.telegram.send_message(
                message.chat.get("id"),
                "Natural-language assistance is disabled. Use /help for "
                "deterministic commands.",
            )
            return
        try:
            reply = await self._interpret(
                message,
                message.text or "",
                update_id=update_id,
            )
            await self._send_assistant_reply(message.chat.get("id"), reply)
        except ProviderUnavailable:
            await self.telegram.send_message(
                message.chat.get("id"),
                "The assistant is unavailable. Slash commands still work.",
            )

    async def _interpret(
        self,
        message: TelegramMessage,
        text: str,
        *,
        update_id: int,
        review_required: bool = False,
    ) -> AssistantReply:
        """Continue an open question when one is waiting, else start fresh."""
        assistant = self._get_bounded_assistant()
        actor = self._actor(message)
        pending_id = await asyncio.to_thread(
            assistant.open_clarification_id,
            actor.telegram_id,
        )
        if pending_id is not None:
            return await asyncio.to_thread(
                assistant.answer_clarification,
                actor,
                pending_id,
                text,
            )
        return await asyncio.to_thread(
            assistant.handle,
            actor,
            text,
            update_id=update_id,
            review_required=review_required,
        )

    async def _handle_bounded_voice(
        self,
        message: TelegramMessage,
        update_id: int,
    ) -> None:
        spoken = message.spoken_audio
        if spoken is None:
            return
        try:
            validate_voice_metadata(
                duration_seconds=spoken.duration,
                file_size=spoken.file_size,
                mime_type=spoken.mime_type,
            )
            await asyncio.to_thread(
                self._consume_voice_quota,
                message,
            )
        except (ValueError, QuotaExceeded) as exc:
            await self.telegram.send_message(
                message.chat.get("id"),
                str(exc),
            )
            return
        if not settings.ai_agent_enabled:
            await self.telegram.send_message(
                message.chat.get("id"),
                "Voice interpretation is disabled. Use /help for commands.",
            )
            return
        await self.telegram.send_typing_action(message.chat.get("id"))
        processing = await self.telegram.send_message(
            message.chat.get("id"),
            "Voice received. Processing securely...",
            reply_to_message_id=message.message_id,
            queue_cleanup=False,
        )
        processing_message_id = (processing.get("result") or {}).get("message_id")
        try:
            try:
                transcript = await transcribe_telegram_voice(
                    spoken.file_id,
                    settings.telegram_bot_token,
                )
            except Exception:
                logger.exception(
                    "Bounded voice transcription failed",
                    extra={"voice_stage": "transcription"},
                )
                await self.telegram.send_message(
                    message.chat.get("id"),
                    "I could not transcribe that voice note. No action was taken.",
                )
                return
            try:
                reply = await self._interpret(
                    message,
                    transcript,
                    update_id=update_id,
                    review_required=True,
                )
                await self._send_assistant_reply(message.chat.get("id"), reply)
            except ProviderUnavailable:
                await self.telegram.send_message(
                    message.chat.get("id"),
                    "The assistant is unavailable. Slash commands still work.",
                )
            except Exception:
                logger.exception(
                    "Bounded voice intent handling failed",
                    extra={"voice_stage": "intent"},
                )
                await self.telegram.send_message(
                    message.chat.get("id"),
                    "I could not process that voice note. No action was taken.",
                )
        finally:
            if processing_message_id is not None:
                try:
                    await self.telegram.delete_message(
                        message.chat.get("id"),
                        int(processing_message_id),
                    )
                except Exception:
                    logger.warning(
                        "Unable to remove Telegram voice processing notice",
                        extra={"voice_stage": "processing_notice_cleanup"},
                    )

    def _consume_voice_quota(self, message: TelegramMessage) -> None:
        spoken = message.spoken_audio
        if message.from_user is None or spoken is None:
            raise ValueError("Voice identity is missing.")
        with self.memory.get_session() as session:
            owner = DomainServices(session).ensure_owner(
                telegram_id=message.from_user.id,
                first_name=message.from_user.first_name,
                last_name=message.from_user.last_name,
                username=message.from_user.username,
            )
            QuotaService(session).require(
                owner.id,
                "voice_units",
                limit=daily_voice_unit_limit(),
                units=voice_quota_units(spoken.duration),
            )

    async def _v2_answer_agent(self, message: TelegramMessage) -> None:
        parts = (message.text or "").split(maxsplit=2)
        if len(parts) != 3 or not parts[1].isdigit():
            await self.telegram.send_message(
                message.chat.get("id"),
                "Usage: <code>/answeragent ID your answer</code>",
            )
            return
        try:
            reply = await asyncio.to_thread(
                self._get_bounded_assistant().answer_clarification,
                self._actor(message),
                int(parts[1]),
                parts[2],
            )
            await self._send_assistant_reply(message.chat.get("id"), reply)
        except ProviderUnavailable:
            await self.telegram.send_message(
                message.chat.get("id"),
                "The assistant is unavailable. Try again later.",
            )

    async def _v2_confirm_agent(self, message: TelegramMessage) -> None:
        await self._bounded_pending_command(message, "confirm")

    async def _v2_cancel_agent(self, message: TelegramMessage) -> None:
        await self._bounded_pending_command(message, "cancel")

    async def _bounded_pending_command(
        self,
        message: TelegramMessage,
        operation: str,
    ) -> None:
        parts = (message.text or "").split()
        if len(parts) != 2 or not parts[1].isdigit():
            await self.telegram.send_message(
                message.chat.get("id"),
                f"Usage: <code>/{operation}agent ID</code>",
            )
            return
        try:
            assistant = self._get_bounded_assistant()
            handler = assistant.confirm if operation == "confirm" else assistant.cancel
            reply = await asyncio.to_thread(
                handler,
                self._actor(message),
                int(parts[1]),
            )
            await self.telegram.send_message(message.chat.get("id"), reply.text)
        except ProviderUnavailable:
            await self.telegram.send_message(
                message.chat.get("id"),
                "The assistant is unavailable. Try again later.",
            )

    async def _legacy_cmd_start(self, message: TelegramMessage) -> None:
        chat_id = message.chat.get("id")
        user_name = message.from_user.first_name if message.from_user else "there"

        welcome = f"""👋 <b>Welcome to Weekly Progress Agent, {user_name}!</b>

I'm your personal productivity assistant. I help you:

🎙️ <b>Track Progress:</b> Send voice notes about your daily work
📊 <b>Get Insights:</b> Automatic daily reflections and summaries
📝 <b>LinkedIn Posts:</b> Weekly generated posts for your network

<b>How to use:</b>
1. Send me voice notes about what you're working on
2. I'll transcribe, categorize, and remember everything
3. Get daily summaries and weekly LinkedIn post drafts!

<b>Commands:</b>
/status - See your streak and stats
/summary - Get your latest summary
/generate - Generate LinkedIn post drafts
/help - Show all commands

<i>💡 Tip: Voice notes work best! Just talk naturally about your day.</i>

Ready to start? Send me your first voice note! 🚀"""

        await self.telegram.send_message(chat_id, welcome)

    async def _legacy_cmd_help(self, message: TelegramMessage) -> None:
        chat_id = message.chat.get("id")

        help_text = """📚 <b>Weekly Progress Agent - Help</b>

<b>🎙️ Voice Notes</b>
Send a voice message about:
• What you worked on
• What you learned
• Blockers or challenges
• Accomplishments

<b>📝 Text Logging</b>
<code>#log Worked on API, fixed 3 bugs</code>
<code>#progress Learned React hooks today</code>

<b>📋 Commands</b>
/status - Your streak and stats
/summary - Today's logged entries
/summary DD-MM-YYYY DD-MM-YYYY - Date range summary
/generate - Generate LinkedIn post
/recent - Show recent entries
/delete [ID] - Delete an entry
/goal [text] - Set a new goal
/set_goal [text] - Set a new goal
/goals - View all your goals
/help - This help

<b>🎯 Goals</b>
Set goals and I'll track your progress:
<code>/goal Improve DSA skills weekly</code>
<code>/goals</code> - See all goals

<b>🤖 Features</b>
• Automatic entry classification
• Goal tracking with sub-tasks
• Morning reminder if no logs
• Daily reflection summaries
• Weekly LinkedIn posts

<b>💡 Tips</b>
• Be specific about what you did
• Mention technologies and projects
• Regular logging = better tracking!"""

        await self.telegram.send_message(chat_id, help_text)

    async def _cmd_status(self, message: TelegramMessage) -> None:
        chat_id = message.chat.get("id")
        user_id = message.from_user.id if message.from_user else 0

        await self.telegram.send_typing_action(chat_id)

        try:
            stats = self.memory.get_user_stats(user_id)

            if not stats:
                await self.telegram.send_message(
                    chat_id,
                    "📊 No data yet! Send your first voice note to get started.",
                )
                return

            streak_str = format_streak(stats.get("streak", 0))
            last_entry = stats.get("last_entry")

            if last_entry:
                time_ago = datetime.utcnow() - last_entry
                hours_ago = int(time_ago.total_seconds() / 3600)
                if hours_ago < 1:
                    last_entry_str = "Just now"
                elif hours_ago < 24:
                    last_entry_str = f"{hours_ago} hours ago"
                else:
                    days_ago = hours_ago // 24
                    last_entry_str = f"{days_ago} days ago"
            else:
                last_entry_str = "Never"

            status = f"""📊 <b>Your Status</b>

{streak_str}

📈 <b>Stats:</b>
• Total entries: {stats.get('total_entries', 0)}
• This week: {stats.get('entries_this_week', 0)}
• Most logged: {stats.get('most_common_category', 'N/A').title()}

⏰ <b>Last entry:</b> {last_entry_str}

<i>Keep logging to build your streak! 💪</i>"""

            await self.telegram.send_message(chat_id, status)

        except Exception as e:
            logger.error(f"Error getting status: {e}")
            await self.telegram.send_message(
                chat_id, "❌ Error fetching status. Please try again."
            )

    async def _cmd_summary(self, message: TelegramMessage) -> None:
        chat_id = message.chat.get("id")
        user_id = message.from_user.id if message.from_user else 0

        await self.telegram.send_typing_action(chat_id)

        try:
            parts = message.text.split()

            if len(parts) >= 3:
                try:
                    start_date = datetime.strptime(parts[1], "%d-%m-%Y")
                    end_date = datetime.strptime(parts[2], "%d-%m-%Y")
                    end_date = end_date.replace(hour=23, minute=59, second=59)

                    entries = self.memory.get_structured_entries_by_date(
                        user_id, start_date, end_date
                    )

                    if not entries:
                        await self.telegram.send_message(
                            chat_id,
                            f"📭 No entries found between {parts[1]} and {parts[2]}",
                        )
                        return

                    summary = await self._generate_quick_summary(
                        entries, start_date, end_date
                    )
                    await self.telegram.send_message(chat_id, summary)
                    return

                except ValueError:
                    await self.telegram.send_message(
                        chat_id,
                        "❌ Invalid date format. Use: /summary DD-MM-YYYY DD-MM-YYYY\n\nExample: /summary 02-02-2026 04-02-2026",
                    )
                    return

            day_start, day_end = get_day_boundaries()
            entries = self.memory.get_structured_entries_by_date(
                user_id, day_start, day_end
            )

            if entries:
                summary = await self._generate_quick_summary(
                    entries, day_start, day_end
                )
                await self.telegram.send_message(chat_id, summary)
            else:
                await self.telegram.send_message(
                    chat_id,
                    """📅 <b>No entries today yet!</b>

Send a voice note or text with #log to start logging.

<i>Tip: Talk about what you're working on, learning, or struggling with.</i>""",
                )

        except Exception as e:
            logger.error(f"Error getting summary: {e}")
            await self.telegram.send_message(
                chat_id, "❌ Error generating summary. Please try again."
            )

    async def _generate_quick_summary(
        self, entries: list, start_date: datetime, end_date: datetime
    ) -> str:
        categories = {}
        all_text = []

        for e in entries:
            cat = e.category.value if hasattr(e.category, "value") else str(e.category)
            categories[cat] = categories.get(cat, 0) + 1
            if e.keywords:
                all_text.extend(e.keywords[:2])
            if e.summary:
                all_text.append(e.summary[:100])

        is_single_day = start_date.date() == end_date.date()
        date_str = (
            start_date.strftime("%B %d")
            if is_single_day
            else f"{start_date.strftime('%b %d')} - {end_date.strftime('%b %d')}"
        )

        categories_text = (
            ", ".join([f"{k}: {v}" for k, v in categories.items()])
            if categories
            else "None"
        )

        topics_summary = ""
        if all_text:
            unique_topics = list(dict.fromkeys(all_text))[:6]
            topics_summary = f"\n\n🏷️ <b>Topics:</b>\n" + "\n".join(
                [f"• {t}" for t in unique_topics]
            )

        return f"""📅 <b>Summary - {date_str}</b>

📊 <b>Total Entries:</b> {len(entries)}
📁 <b>Categories:</b> {categories_text}{topics_summary}

<i>Use /generate to create a LinkedIn post from these entries.</i>"""

    def _format_list(self, items: list, max_items: int = 3) -> str:
        if not items:
            return "• None"
        return "\n".join([f"• {item}" for item in items[:max_items]])

    def _convert_raw_to_structured(self, raw_entries: List[Dict]) -> List:
        """Convert raw entries to structured format for post generation."""
        from models import StructuredEntry, EntryCategory

        structured = []
        for raw in raw_entries:
            try:
                entry = StructuredEntry(
                    id=raw.get("id", 0),
                    raw_entry_id=raw.get("id", 0),
                    category=EntryCategory.OTHER,
                    activities=(
                        [raw.get("raw_text", "")[:100]] if raw.get("raw_text") else []
                    ),
                    blockers=[],
                    accomplishments=[],
                    learnings=[],
                    summary=(
                        raw.get("raw_text", "")[:200] if raw.get("raw_text") else ""
                    ),
                    keywords=[],
                    sentiment="neutral",
                )
                structured.append(entry)
            except Exception as e:
                logger.warning(f"Could not convert raw entry: {e}")
                continue
        return structured

    async def _cmd_generate(self, message: TelegramMessage) -> None:
        chat_id = message.chat.get("id")
        user_id = message.from_user.id if message.from_user else 0

        await self.telegram.send_message(
            chat_id, "✍️ Analyzing your entries... This may take a moment."
        )
        await self.telegram.send_typing_action(chat_id)

        try:
            last_posted_date = self.memory.get_last_posted_report_date(user_id)

            from datetime import timedelta

            if last_posted_date:
                start = last_posted_date + timedelta(hours=1)
            else:
                # No previous posts - use last 7 days
                start = datetime.utcnow() - timedelta(days=7)

            end = datetime.utcnow() + timedelta(hours=1)

            logger.info(
                f"Generating post for user {user_id} with entries from {start} to {end}"
            )

            entries = self.memory.get_structured_entries_by_date(user_id, start, end)

            MIN_ENTRIES_THRESHOLD = 1
            if not entries or len(entries) < MIN_ENTRIES_THRESHOLD:
                next_week = self.memory.get_next_week_number(user_id)
                last_week = next_week - 1

                await self.telegram.send_message(
                    chat_id,
                    f"📭 <b>Not enough new content for Week {next_week}</b>\n\n"
                    f"I found <b>0 new entries</b> since your Week {last_week} post.\n\n"
                    f"💡 <b>What to do:</b>\n"
                    f"• Send some voice notes about this week's work\n"
                    f"• Use <code>#log</code> to add text entries\n"
                    f"• Then run /generate again\n\n"
                    f"<i>I need at least {MIN_ENTRIES_THRESHOLD} new entry to create a meaningful post.</i>",
                )
                return

            logger.info(f"Found {len(entries)} new entries for user {user_id}")

            feedback_suggestions = self.memory.get_feedback_for_prompt_refinement(
                report_type="linkedin", limit=5
            )
            refinement_instructions = ""
            if feedback_suggestions:
                refinement_instructions = (
                    "Apply this quality feedback from previous generated reports:\n"
                    + "\n".join([f"- {item}" for item in feedback_suggestions])
                )

            daily_summaries = self.memory.get_daily_summaries(user_id, days=7)
            logger.info(
                f"Found {len(daily_summaries)} daily summaries for user {user_id}"
            )

            if not daily_summaries:
                logger.info(
                    f"Creating summary from {len(entries)} entries for user {user_id}"
                )

                all_activities = []
                all_learnings = []
                all_accomplishments = []
                all_blockers = []
                all_themes = []

                for entry in entries:
                    if entry.activities:
                        all_activities.extend(entry.activities)
                    if entry.learnings:
                        all_learnings.extend(entry.learnings)
                    if entry.accomplishments:
                        all_accomplishments.extend(entry.accomplishments)
                    if entry.blockers:
                        all_blockers.extend(entry.blockers)
                    all_themes.append(entry.category.value)

                from models import WeeklySummary, LinkedInPost, PostStatus, PostTone

                unique_themes = list(set(all_themes))[:5]

                weekly_summary = WeeklySummary(
                    telegram_id=user_id,
                    week_start=start,
                    week_end=end,
                    daily_summaries=[],
                    total_entries=len(entries),
                    main_themes=unique_themes if unique_themes else ["development"],
                    accomplishments=(
                        all_accomplishments[:5]
                        if all_accomplishments
                        else ["Made progress on projects"]
                    ),
                    learnings=all_learnings[:5] if all_learnings else [],
                    trends={
                        "activities": all_activities[:10],
                        "blockers": all_blockers[:5],
                        "productivity_trend": "stable",
                    },
                    comparison_with_previous=None,
                )

                weekly_id = self.memory.save_weekly_summary(weekly_summary)
                weekly_summary.id = weekly_id

                recent_published = self.memory.get_published_posts(user_id, limit=5)

                next_week = self.memory.get_next_week_number(user_id)

                posts = self.agent.generate_linkedin_posts(
                    weekly_summary,
                    custom_instructions=refinement_instructions,
                    recent_posts=recent_published,
                    week_number=next_week,
                )
            else:
                themes = self.memory.detect_themes(user_id)

                previous_weekly = self.memory.get_latest_weekly_summary(user_id)

                recent_posts = self.memory.get_recent_post_embeddings(
                    user_id, n_results=3
                )

                weekly_summary = self.agent.generate_weekly_summary(
                    daily_summaries=daily_summaries,
                    themes=themes,
                    previous_week=previous_weekly,
                    recent_posts=recent_posts,
                )
                weekly_summary.telegram_id = user_id

                weekly_id = self.memory.save_weekly_summary(weekly_summary)
                weekly_summary.id = weekly_id

                recent_published = self.memory.get_published_posts(user_id, limit=5)

                next_week = self.memory.get_next_week_number(user_id)

                posts = self.agent.generate_linkedin_posts(
                    weekly_summary,
                    custom_instructions=refinement_instructions,
                    recent_posts=recent_published,
                    week_number=next_week,
                )

            saved_post_ids = []
            for post in posts:
                post.telegram_id = user_id
                post.weekly_summary_id = weekly_summary.id
                post_id = self.memory.save_linkedin_post(post)
                saved_post_ids.append(post_id)

            if posts and saved_post_ids:
                critique = self.agent.critique_report(
                    report_content=posts[0].content, report_type="linkedin"
                )

                feedback = ReportFeedback(
                    report_type="linkedin",
                    report_id=saved_post_ids[0],
                    clarity_score=int(critique.get("clarity_score", 7)),
                    suggestions=critique.get("suggestions", [])[:5],
                    applied_improvements=[],
                )
                self.memory.save_report_feedback(feedback)

            await self.telegram.send_message(
                chat_id,
                f"✅ Generated {len(posts)} LinkedIn post drafts!\n\n<i>Here they are:</i>",
            )

            for post in posts:
                tone_emoji = {"friendly": "😊", "professional": "💼", "technical": "🔧"}
                emoji = tone_emoji.get(post.tone.value, "📝")

                post_message = f"""{emoji} <b>{post.tone.value.title()} Version</b>

{post.content}

<i>Reply with edits or use the dashboard to customize.</i>"""

                await self.telegram.send_message(chat_id, post_message)

            await self.telegram.send_message(
                chat_id,
                "💡 <b>Tip:</b> View and edit these posts in the web dashboard for easier copying!",
            )

            if posts and saved_post_ids:
                top_suggestion = ""
                if feedback.suggestions:
                    top_suggestion = (
                        f"\n💡 <b>Next improvement:</b> {feedback.suggestions[0]}"
                    )
                await self.telegram.send_message(
                    chat_id,
                    f"🪞 <b>Auto Review</b>\n"
                    f"Clarity score: <b>{feedback.clarity_score}/10</b>{top_suggestion}",
                )

        except Exception as e:
            logger.error(f"Error generating posts: {e}", exc_info=True)
            await self.telegram.send_message(
                chat_id, "❌ Error generating posts. Please try again later."
            )

    async def _cmd_delete(self, message: TelegramMessage) -> None:
        chat_id = message.chat.get("id")
        user_id = message.from_user.id if message.from_user else 0

        try:
            parts = message.text.split()

            if len(parts) > 1:
                try:
                    entry_id = int(parts[1])
                    success = self.memory.delete_entry(entry_id, user_id)

                    if success:
                        await self.telegram.send_message(
                            chat_id, f"✅ Entry #{entry_id} deleted!"
                        )
                    else:
                        await self.telegram.send_message(
                            chat_id, f"❌ Entry #{entry_id} not found."
                        )
                    return
                except ValueError:
                    pass

            entries = self.memory.get_recent_entries_for_deletion(user_id, limit=5)

            if not entries:
                await self.telegram.send_message(chat_id, "📭 No recent entries found.")
                return

            entries_text = "\n\n".join(
                [
                    f"🔹 <b>ID: {e['id']}</b>\n"
                    f"   📅 {e.get('timestamp', 'Unknown')}\n"
                    f"   📝 {e.get('summary', '')[:80]}"
                    for e in entries
                ]
            )

            response = f"""🗑️ <b>Delete Entry</b>

{entries_text}

<b>To delete:</b> <code>/delete [ID]</code>
Example: <code>/delete {entries[0]['id']}</code>"""

            await self.telegram.send_message(chat_id, response)
        except Exception as e:
            logger.error(f"Error in /delete: {e}")
            await self.telegram.send_message(chat_id, "❌ Error. Please try again.")

    async def _cmd_recent(self, message: TelegramMessage) -> None:
        chat_id = message.chat.get("id")
        user_id = message.from_user.id if message.from_user else 0

        try:
            entries = self.memory.get_recent_entries_for_deletion(user_id, limit=10)

            if not entries:
                await self.telegram.send_message(chat_id, "📭 No recent entries found.")
                return

            entries_text = "\n\n".join(
                [
                    f"🔹 <b>#{e['id']}</b> | {e.get('category', 'entry').title()}\n"
                    f"   📅 {e.get('timestamp', 'Unknown')}\n"
                    f"   📝 {e.get('summary', '')[:100]}"
                    for e in entries
                ]
            )

            response = f"""📋 <b>Recent Entries</b>

{entries_text}

💡 <i>Use /delete [ID] to remove an entry.</i>"""

            await self.telegram.send_message(chat_id, response)
        except Exception as e:
            logger.error(f"Error in /recent: {e}")
            await self.telegram.send_message(
                chat_id, "❌ Error fetching entries. Please try again."
            )

    async def _cmd_goal(self, message: TelegramMessage) -> None:
        """Handle /goal command - set or update a goal."""
        from models import Goal, GoalStatus

        chat_id = message.chat.get("id")
        user_id = message.from_user.id if message.from_user else 0

        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            await self.telegram.send_message(
                chat_id,
                """🎯 <b>Set a Goal</b>

Usage: <code>/goal Your goal description</code>

<b>Examples:</b>
• <code>/goal Improve DSA skills - practice daily</code>
• <code>/goal Complete React course by end of month</code>
• <code>/goal Build side project MVP</code>

I'll break down your goal into actionable sub-tasks and track your progress!

<i>Use /goals to see all your goals.</i>""",
            )
            return

        goal_text = parts[1].strip()

        await self.telegram.send_typing_action(chat_id)

        try:
            sub_tasks = self.agent.break_goal_into_tasks(goal_text)

            goal = Goal(
                telegram_id=user_id,
                title=goal_text[:100],
                description=goal_text,
                status=GoalStatus.ACTIVE,
                progress=0,
                sub_tasks=sub_tasks,
            )

            goal_id = self.memory.save_goal(goal)

            tasks_text = "\n".join([f"  • {task}" for task in sub_tasks[:5]])

            response = f"""🎯 <b>Goal Set!</b>

<b>Goal:</b> {goal_text[:100]}

<b>Sub-tasks:</b>
{tasks_text}

📊 <b>Progress:</b> 0%

<i>I'll track your entries and update your progress automatically. Use /goals to see all goals.</i>"""

            await self.telegram.send_message(chat_id, response)
            logger.info(f"Created goal {goal_id} for user {user_id}")

        except Exception as e:
            logger.error(f"Error creating goal: {e}")
            await self.telegram.send_message(
                chat_id, "❌ Error creating goal. Please try again."
            )

    async def _cmd_goals(self, message: TelegramMessage) -> None:
        """Handle /goals command - list all goals."""
        chat_id = message.chat.get("id")
        user_id = message.from_user.id if message.from_user else 0

        try:
            goals = self.memory.get_all_goals(user_id)

            if not goals:
                await self.telegram.send_message(
                    chat_id,
                    """📋 <b>No Goals Yet</b>

Set your first goal with:
<code>/goal Your goal here</code>

<b>Examples:</b>
• <code>/goal Learn Docker and Kubernetes</code>
• <code>/goal Build full-stack app with Next.js</code>""",
                )
                return

            active_goals = [g for g in goals if g.status.value == "active"]
            completed_goals = [g for g in goals if g.status.value == "completed"]

            def format_goal(g, show_status=False):
                progress_bar = self._get_progress_bar(g.progress)
                status_icon = "✅" if g.status.value == "completed" else "🎯"
                status_text = f" ({g.status.value})" if show_status else ""
                return f"{status_icon} <b>#{g.id}</b> {g.title[:50]}{status_text}\n   {progress_bar} {g.progress}%"

            response_parts = ["📋 <b>Your Goals</b>\n"]

            if active_goals:
                response_parts.append("<b>Active:</b>")
                for g in active_goals[:5]:
                    response_parts.append(format_goal(g))
                response_parts.append("")

            if completed_goals:
                response_parts.append("<b>Completed:</b>")
                for g in completed_goals[:3]:
                    response_parts.append(format_goal(g, True))

            response_parts.append("\n<i>Set new goal: /goal [description]</i>")

            await self.telegram.send_message(chat_id, "\n".join(response_parts))

        except Exception as e:
            logger.error(f"Error listing goals: {e}")
            await self.telegram.send_message(
                chat_id, "❌ Error fetching goals. Please try again."
            )

    def _get_progress_bar(self, progress: int) -> str:
        """Generate a visual progress bar."""
        filled = int(progress / 10)
        empty = 10 - filled
        return "▓" * filled + "░" * empty

    TEXT_LOG_PREFIXES = ["#log", "#progress", "/log"]

    async def _handle_text(self, message: TelegramMessage) -> None:
        chat_id = message.chat.get("id")
        user_id = message.from_user.id if message.from_user else 0
        text = message.text.strip() if message.text else ""

        text_lower = text.lower()
        for prefix in self.TEXT_LOG_PREFIXES:
            if text_lower.startswith(prefix):
                log_content = text[len(prefix) :].strip()

                if not log_content or len(log_content) < 10:
                    await self.telegram.send_message(
                        chat_id,
                        f"📝 Please include your progress after the prefix.\n\nExample:\n<code>{prefix} Today I worked on the API endpoints and fixed 3 bugs.</code>",
                    )
                    return

                await self._process_text_log(message, log_content)
                return

        if await self._handle_clarification_response(message):
            return

        await self.telegram.send_message(
            chat_id,
            """📝 <b>Text Logging Available!</b>

To log progress via text, use one of these prefixes:

• <code>#log</code> Your progress here
• <code>#progress</code> What you worked on
• <code>/log</code> Your update

<b>Example:</b>
<code>#log Worked on the API today, fixed authentication bug and added rate limiting.</code>

🎙️ <b>Voice notes work too!</b>
Just send a voice message directly.

<i>Use /help to see all commands.</i>""",
        )

    async def _process_text_log(
        self, message: TelegramMessage, log_content: str
    ) -> None:
        chat_id = message.chat.get("id")
        user_id = message.from_user.id if message.from_user else 0

        await self.telegram.send_typing_action(chat_id)

        await self.telegram.send_message(
            chat_id,
            "📝 Processing your text log...",
            reply_to_message_id=message.message_id,
        )

        try:
            logger.info(f"Classifying text log: {len(log_content)} chars")
            classification = self.agent.classify_entry(log_content)

            clarification = self._check_needs_clarification(log_content, classification)
            if clarification:
                await self._ask_clarification(
                    chat_id,
                    user_id,
                    message.message_id,
                    log_content,
                    classification,
                    clarification,
                )
                return

            raw_entry = RawEntry(
                telegram_id=user_id,
                telegram_message_id=message.message_id,
                timestamp=datetime.utcfromtimestamp(message.date),
                audio_file_id="text_entry",
                audio_duration=0,
                transcript=log_content,
            )
            raw_entry_id = self.memory.save_raw_entry(raw_entry)

            structured_entry = StructuredEntry(
                raw_entry_id=raw_entry_id,
                category=classification.category,
                activities=classification.activities,
                blockers=classification.blockers,
                accomplishments=classification.accomplishments,
                learnings=classification.learnings,
                summary=classification.summary,
                keywords=classification.keywords,
                sentiment=classification.sentiment,
            )
            self.memory.save_structured_entry(structured_entry)

            keywords_str = (
                ",".join(classification.keywords) if classification.keywords else ""
            )
            self.memory.add_to_vector_memory(
                entry_id=raw_entry_id,
                text=log_content,
                metadata={
                    "telegram_id": user_id,
                    "category": classification.category.value,
                    "timestamp": datetime.utcnow().isoformat(),
                    "keywords": keywords_str,
                    "source": "text",
                },
            )

            streak = self.memory.update_user_streak(user_id)

            category_emoji = self._get_category_emoji(classification.category)
            streak_str = format_streak(streak)

            response = f"""✅ <b>Text Entry Logged!</b>

{category_emoji} <b>Category:</b> {classification.category.value.title()}

📝 <b>Summary:</b>
{classification.summary}

{self._format_entry_details(classification)}

{streak_str}

<i>Source: Text message</i>"""

            await self.telegram.send_message(chat_id, response)
            logger.info(f"Successfully processed text log for user {user_id}")

        except Exception as e:
            logger.error(f"Error processing text log: {e}", exc_info=True)
            await self.telegram.send_message(
                chat_id, "❌ Error processing your text log. Please try again."
            )

    def _check_needs_clarification(self, content: str, classification) -> Optional[str]:
        vague_indicators = [
            "stuff",
            "things",
            "some work",
            "worked on it",
            "did stuff",
            "made progress",
            "worked",
        ]

        content_lower = content.lower()

        if len(content.split()) < 5:
            return "Could you tell me more about what you worked on? What specific tasks or projects?"

        for indicator in vague_indicators:
            if indicator in content_lower and not classification.activities:
                return f"I see you mentioned '{indicator}'. Could you be more specific about what you actually did?"

        if any(
            word in content_lower
            for word in ["stuck", "problem", "issue", "cant", "can't"]
        ):
            if not classification.blockers:
                return "It sounds like you ran into some issues. What specific problems are you facing?"

        if "learned" in content_lower or "learning" in content_lower:
            if not classification.learnings:
                return "What specifically did you learn? Any key takeaways?"

        return None

    _pending_clarifications: Dict[int, Dict] = {}

    async def _ask_clarification(
        self,
        chat_id: int,
        user_id: int,
        message_id: int,
        original_content: str,
        classification,
        question: str,
    ) -> None:
        self._pending_clarifications[user_id] = {
            "original_content": original_content,
            "classification": classification,
            "message_id": message_id,
            "timestamp": datetime.utcnow(),
        }

        await self.telegram.send_message(
            chat_id,
            f"❓ <b>Quick question:</b>\n\n{question}\n\n<i>Just reply with more details, or type 'skip' to log as-is.</i>",
            reply_to_message_id=message_id,
        )

    async def _handle_clarification_response(self, message: TelegramMessage) -> bool:
        user_id = message.from_user.id if message.from_user else 0

        if user_id not in self._pending_clarifications:
            return False

        pending = self._pending_clarifications[user_id]

        if (datetime.utcnow() - pending["timestamp"]).seconds > 600:
            del self._pending_clarifications[user_id]
            return False

        chat_id = message.chat.get("id")
        text = message.text.strip() if message.text else ""

        if text.lower() in ["skip", "no", "nevermind", "nvm"]:
            del self._pending_clarifications[user_id]
            await self._save_clarified_entry(
                chat_id, user_id, pending["original_content"], pending["classification"]
            )
            return True

        enhanced_content = (
            f"{pending['original_content']}\n\nAdditional details: {text}"
        )

        try:
            new_classification = self.agent.classify_entry(enhanced_content)
            await self._save_clarified_entry(
                chat_id, user_id, enhanced_content, new_classification
            )
        except Exception as e:
            logger.error(f"Error processing clarification: {e}")
            await self._save_clarified_entry(
                chat_id, user_id, pending["original_content"], pending["classification"]
            )

        del self._pending_clarifications[user_id]
        return True

    async def _save_clarified_entry(
        self, chat_id: int, user_id: int, content: str, classification
    ) -> None:
        try:
            raw_entry = RawEntry(
                telegram_id=user_id,
                telegram_message_id=0,
                timestamp=datetime.utcnow(),
                audio_file_id="text_entry_clarified",
                audio_duration=0,
                transcript=content,
            )
            raw_entry_id = self.memory.save_raw_entry(raw_entry)

            structured_entry = StructuredEntry(
                raw_entry_id=raw_entry_id,
                category=classification.category,
                activities=classification.activities,
                blockers=classification.blockers,
                accomplishments=classification.accomplishments,
                learnings=classification.learnings,
                summary=classification.summary,
                keywords=classification.keywords,
                sentiment=classification.sentiment,
            )
            self.memory.save_structured_entry(structured_entry)

            keywords_str = (
                ",".join(classification.keywords) if classification.keywords else ""
            )
            self.memory.add_to_vector_memory(
                entry_id=raw_entry_id,
                text=content,
                metadata={
                    "telegram_id": user_id,
                    "category": classification.category.value,
                    "timestamp": datetime.utcnow().isoformat(),
                    "keywords": keywords_str,
                    "source": "text_clarified",
                },
            )

            streak = self.memory.update_user_streak(user_id)

            category_emoji = self._get_category_emoji(classification.category)
            streak_str = format_streak(streak)

            response = f"""✅ <b>Entry Logged!</b>

{category_emoji} <b>Category:</b> {classification.category.value.title()}

📝 <b>Summary:</b>
{classification.summary}

{self._format_entry_details(classification)}

{streak_str}"""

            await self.telegram.send_message(chat_id, response)

        except Exception as e:
            logger.error(f"Error saving clarified entry: {e}", exc_info=True)
            await self.telegram.send_message(
                chat_id, "❌ Error saving your entry. Please try again."
            )


_bot_handler: Optional[BotHandler] = None


def get_bot_handler() -> BotHandler:
    global _bot_handler
    if _bot_handler is None:
        _bot_handler = BotHandler()
    return _bot_handler
