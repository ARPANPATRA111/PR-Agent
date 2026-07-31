"""Deterministic Telegram commands backed by the shared domain services."""

import asyncio
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from html import escape
import logging

from config import settings
from domain.errors import DomainError
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
from domain.services import DomainServices
from models import TelegramMessage

logger = logging.getLogger(__name__)


class DeterministicCommandMixin:
    """CRUD commands that remain available when every AI provider is down."""

    async def _cmd_start(self, message: TelegramMessage) -> None:
        first_name = (
            escape(message.from_user.first_name) if message.from_user else "there"
        )
        await self.telegram.send_message(
            message.chat.get("id"),
            f"👋 <b>Welcome, {first_name}.</b>\n\n"
            "Track work, notes, reminders, goals, income, and expenses. "
            "Your records are private to your Telegram account and can be "
            "viewed, edited, or deleted.\n\n"
            "Use /help to see the deterministic commands.",
        )

    async def _cmd_help(self, message: TelegramMessage) -> None:
        await self.telegram.send_message(
            message.chat.get("id"),
            "<b>PR-Agent commands</b>\n\n"
            "<b>Work:</b> /log, /logs, /editlog, /deletelog\n"
            "<b>Notes:</b> /note, /notes, /editnote, /pin, /deletenote\n"
            "<b>Money:</b> /expense, /income, /ledger, /editledger, "
            "/deleteledger\n"
            "<b>Goals:</b> /goal, /goals, /editgoal, /goalprogress, "
            "/completegoal, /pausegoal, /deletegoal\n"
            "<b>Reminders:</b> /remind, /reminders, /editreminder, "
            "/pausereminder, /resumereminder, /deletereminder\n\n"
            "Examples:\n"
            "<code>/log Finished tenant-isolation tests</code>\n"
            "<code>/note Ask HR about relocation</code>\n"
            "<code>/expense 240 INR dinner</code>\n"
            "<code>/income 5000 INR freelance payment</code>\n"
            "<code>/remind once 2026-08-10 19:00 Asia/Kolkata Submit assignment</code>",
        )

    def _run_domain(self, message: TelegramMessage, operation):
        if not settings.public_v2_enabled and settings.app_env in {
            "staging",
            "production",
        }:
            raise DomainError("Public v2 is not enabled yet.")
        if message.from_user is None:
            raise DomainError("Telegram user identity is required.")
        with self.memory.get_session() as session:
            service = DomainServices(session)
            owner = service.ensure_owner(
                telegram_id=message.from_user.id,
                first_name=message.from_user.first_name,
                last_name=message.from_user.last_name,
                username=message.from_user.username,
            )
            return operation(service, owner.id)

    async def _domain_reply(self, message: TelegramMessage, operation) -> None:
        chat_id = message.chat.get("id")
        try:
            response = await asyncio.to_thread(
                self._run_domain,
                message,
                operation,
            )
            await self.telegram.send_message(chat_id, response)
        except (DomainError, ValueError, InvalidOperation) as exc:
            await self.telegram.send_message(
                chat_id,
                f"❌ {escape(str(exc))}",
            )
        except Exception:
            logger.exception("Deterministic command failed")
            await self.telegram.send_message(
                chat_id,
                "❌ I could not complete that request. Check the format and try again.",
            )

    @staticmethod
    def _command_body(message: TelegramMessage) -> str:
        parts = (message.text or "").split(maxsplit=1)
        return parts[1].strip() if len(parts) == 2 else ""

    @staticmethod
    def _telegram_idempotency(
        message: TelegramMessage,
        operation: str,
    ) -> str:
        return f"tg:{message.chat.get('id')}:{message.message_id}:{operation}"

    async def _v2_create_work_log(self, message: TelegramMessage) -> None:
        body = self._command_body(message)
        if not body:
            await self.telegram.send_message(
                message.chat.get("id"),
                "Usage: <code>/log what you completed</code>",
            )
            return
        data = WorkLogCreate(
            original_text=body,
            timezone=settings.timezone,
            capture_source="telegram_text",
            logged_at_local=datetime.fromtimestamp(message.date, timezone.utc),
            idempotency_key=self._telegram_idempotency(message, "log"),
        )
        await self._domain_reply(
            message,
            lambda service, owner: (lambda row: f"✅ Work log <b>#{row.id}</b> saved.")(
                service.create_work_log(owner, data)
            ),
        )

    async def _v2_list_work_logs(self, message: TelegramMessage) -> None:
        def operation(service, owner):
            rows = service.list_work_logs(owner, limit=10)
            if not rows:
                return "No work logs yet. Use <code>/log ...</code>."
            return "<b>Recent work logs</b>\n" + "\n".join(
                f"• <b>#{row.id}</b> {escape(row.original_text[:120])}" for row in rows
            )

        await self._domain_reply(message, operation)

    async def _v2_edit_work_log(self, message: TelegramMessage) -> None:
        parts = (message.text or "").split(maxsplit=2)
        if len(parts) != 3 or not parts[1].isdigit():
            await self._usage(message, "/editlog ID replacement text")
            return
        record_id, text = int(parts[1]), parts[2]

        def operation(service, owner):
            current = service.get_work_log(owner, record_id)
            row = service.update_work_log(
                owner,
                record_id,
                WorkLogUpdate(version=current.version, original_text=text),
            )
            return f"✅ Work log <b>#{row.id}</b> updated."

        await self._domain_reply(message, operation)

    async def _v2_delete_work_log(self, message: TelegramMessage) -> None:
        await self._v2_delete_by_id(
            message,
            "deletelog",
            "work log",
            lambda service, owner, record_id: service.delete_work_log(owner, record_id),
        )

    async def _v2_create_note(self, message: TelegramMessage) -> None:
        body = self._command_body(message)
        if not body:
            await self._usage(message, "/note note text")
            return
        data = NoteCreate(
            body=body,
            capture_source="telegram_text",
            idempotency_key=self._telegram_idempotency(message, "note"),
        )
        await self._domain_reply(
            message,
            lambda service, owner: (lambda row: f"✅ Note <b>#{row.id}</b> saved.")(
                service.create_note(owner, data)
            ),
        )

    async def _v2_list_notes(self, message: TelegramMessage) -> None:
        query = self._command_body(message) or None

        def operation(service, owner):
            rows = service.list_notes(owner, search=query, limit=10)
            if not rows:
                return "No matching notes."
            return "<b>Notes</b>\n" + "\n".join(
                f"{'📌' if row.pinned else '•'} <b>#{row.id}</b> "
                f"{escape(row.title[:100])}"
                for row in rows
            )

        await self._domain_reply(message, operation)

    async def _v2_edit_note(self, message: TelegramMessage) -> None:
        parts = (message.text or "").split(maxsplit=2)
        if len(parts) != 3 or not parts[1].isdigit():
            await self._usage(message, "/editnote ID replacement text")
            return
        record_id, body = int(parts[1]), parts[2]

        def operation(service, owner):
            current = service.get_note(owner, record_id)
            row = service.update_note(
                owner,
                record_id,
                NoteUpdate(version=current.version, body=body),
            )
            return f"✅ Note <b>#{row.id}</b> updated."

        await self._domain_reply(message, operation)

    async def _v2_toggle_note_pin(self, message: TelegramMessage) -> None:
        record_id = self._single_id(message)
        if record_id is None:
            await self._usage(message, "/pin NOTE_ID")
            return

        def operation(service, owner):
            current = service.get_note(owner, record_id)
            row = service.update_note(
                owner,
                record_id,
                NoteUpdate(
                    version=current.version,
                    pinned=not current.pinned,
                ),
            )
            state = "pinned" if row.pinned else "unpinned"
            return f"✅ Note <b>#{row.id}</b> {state}."

        await self._domain_reply(message, operation)

    async def _v2_delete_note(self, message: TelegramMessage) -> None:
        await self._v2_delete_by_id(
            message,
            "deletenote",
            "note",
            lambda service, owner, record_id: service.delete_note(owner, record_id),
        )

    async def _v2_create_expense(self, message: TelegramMessage) -> None:
        await self._v2_create_ledger_direction(message, "expense")

    async def _v2_create_income(self, message: TelegramMessage) -> None:
        await self._v2_create_ledger_direction(message, "income")

    async def _v2_create_ledger_direction(
        self,
        message: TelegramMessage,
        direction: str,
    ) -> None:
        parts = (message.text or "").split(maxsplit=3)
        if len(parts) != 4:
            await self._usage(
                message,
                f"/{direction} AMOUNT CURRENCY DESCRIPTION",
            )
            return
        try:
            data = LedgerCreate(
                direction=direction,
                amount=Decimal(parts[1]),
                currency=parts[2],
                description=parts[3],
                timezone=settings.timezone,
                capture_source="telegram_text",
                transaction_at_local=datetime.fromtimestamp(message.date, timezone.utc),
                idempotency_key=self._telegram_idempotency(message, direction),
            )
        except Exception as exc:
            await self.telegram.send_message(
                message.chat.get("id"),
                f"❌ {escape(str(exc))}",
            )
            return
        await self._domain_reply(
            message,
            lambda service, owner: (
                lambda row: f"✅ {direction.title()} <b>#{row.id}</b> saved."
            )(service.create_ledger_entry(owner, data)),
        )

    async def _v2_list_ledger(self, message: TelegramMessage) -> None:
        def operation(service, owner):
            rows = service.list_ledger_entries(owner, limit=10)
            totals = service.summarize_ledger(owner)
            if not rows:
                return "No ledger entries yet."
            total_text = "\n".join(
                f"• {item['currency']}: income {item['income_minor']} minor units, "
                f"expense {item['expense_minor']} minor units"
                for item in totals
            )
            row_text = "\n".join(
                f"• <b>#{row.id}</b> {row.direction} "
                f"{row.amount_minor} {row.currency} minor units — "
                f"{escape(row.description[:80])}"
                for row in rows
            )
            return f"<b>Ledger totals</b>\n{total_text}\n\n{row_text}"

        await self._domain_reply(message, operation)

    async def _v2_edit_ledger(self, message: TelegramMessage) -> None:
        parts = (message.text or "").split(maxsplit=4)
        if len(parts) != 5 or not parts[1].isdigit():
            await self._usage(
                message,
                "/editledger ID AMOUNT CURRENCY DESCRIPTION",
            )
            return
        try:
            record_id = int(parts[1])
            update_amount = Decimal(parts[2])
            update_data = (parts[3], parts[4])
        except InvalidOperation:
            await self._usage(
                message,
                "/editledger ID AMOUNT CURRENCY DESCRIPTION",
            )
            return

        def operation(service, owner):
            current = service.get_ledger_entry(owner, record_id)
            row = service.update_ledger_entry(
                owner,
                record_id,
                LedgerUpdate(
                    version=current.version,
                    amount=update_amount,
                    currency=update_data[0],
                    description=update_data[1],
                ),
            )
            return f"✅ Ledger entry <b>#{row.id}</b> updated."

        await self._domain_reply(message, operation)

    async def _v2_delete_ledger(self, message: TelegramMessage) -> None:
        await self._v2_delete_by_id(
            message,
            "deleteledger",
            "ledger entry",
            lambda service, owner, record_id: service.delete_ledger_entry(
                owner, record_id
            ),
        )

    async def _v2_create_goal(self, message: TelegramMessage) -> None:
        body = self._command_body(message)
        if not body:
            await self._usage(message, "/goal goal title")
            return
        data = GoalCreate(
            title=body,
            idempotency_key=self._telegram_idempotency(message, "goal"),
        )
        await self._domain_reply(
            message,
            lambda service, owner: (lambda row: f"✅ Goal <b>#{row.id}</b> created.")(
                service.create_goal(owner, data)
            ),
        )

    async def _v2_list_goals(self, message: TelegramMessage) -> None:
        def operation(service, owner):
            rows = service.list_goals(owner, limit=20)
            if not rows:
                return "No goals yet. Use <code>/goal ...</code>."
            return "<b>Goals</b>\n" + "\n".join(
                f"• <b>#{row.id}</b> [{row.status}] "
                f"{escape(row.title[:100])} ({row.current_value}"
                f"{' / ' + str(row.target_value) if row.target_value is not None else ''}"
                f"{' ' + escape(row.unit) if row.unit else ''})"
                for row in rows
            )

        await self._domain_reply(message, operation)

    async def _v2_edit_goal(self, message: TelegramMessage) -> None:
        parts = (message.text or "").split(maxsplit=2)
        if len(parts) != 3 or not parts[1].isdigit():
            await self._usage(message, "/editgoal ID replacement title")
            return
        await self._update_goal_command(
            message,
            int(parts[1]),
            lambda version: GoalUpdate(version=version, title=parts[2]),
            "updated",
        )

    async def _v2_progress_goal(self, message: TelegramMessage) -> None:
        parts = (message.text or "").split()
        if len(parts) != 3 or not parts[1].isdigit():
            await self._usage(message, "/goalprogress ID CURRENT_VALUE")
            return
        try:
            value = Decimal(parts[2])
        except InvalidOperation:
            await self._usage(message, "/goalprogress ID CURRENT_VALUE")
            return
        await self._update_goal_command(
            message,
            int(parts[1]),
            lambda version: GoalUpdate(
                version=version,
                current_value=value,
            ),
            "progress updated",
        )

    async def _v2_complete_goal(self, message: TelegramMessage) -> None:
        await self._goal_status_command(message, "completed")

    async def _v2_pause_goal(self, message: TelegramMessage) -> None:
        await self._goal_status_command(message, "paused")

    async def _goal_status_command(
        self,
        message: TelegramMessage,
        goal_status: str,
    ) -> None:
        record_id = self._single_id(message)
        if record_id is None:
            await self._usage(message, f"{message.text.split()[0]} GOAL_ID")
            return
        await self._update_goal_command(
            message,
            record_id,
            lambda version: GoalUpdate(
                version=version,
                status=goal_status,
            ),
            goal_status,
        )

    async def _update_goal_command(
        self,
        message: TelegramMessage,
        record_id: int,
        update_factory,
        result_text: str,
    ) -> None:
        def operation(service, owner):
            current = service.get_goal(owner, record_id)
            row = service.update_goal(
                owner,
                record_id,
                update_factory(current.version),
            )
            return f"✅ Goal <b>#{row.id}</b> {result_text}."

        await self._domain_reply(message, operation)

    async def _v2_delete_goal(self, message: TelegramMessage) -> None:
        await self._v2_delete_by_id(
            message,
            "deletegoal",
            "goal",
            lambda service, owner, record_id: service.delete_goal(owner, record_id),
        )

    async def _v2_create_reminder(self, message: TelegramMessage) -> None:
        parts = (message.text or "").split(maxsplit=5)
        if len(parts) != 6 or parts[1] not in {"once", "daily", "weekly"}:
            await self._usage(
                message,
                "/remind once|daily|weekly YYYY-MM-DD HH:MM TIMEZONE TITLE",
            )
            return
        try:
            start_at = datetime.fromisoformat(f"{parts[2]}T{parts[3]}")
            data = ReminderCreate(
                title=parts[5],
                schedule_type=parts[1],
                start_at_local=start_at,
                timezone=parts[4],
                weekday=(start_at.weekday() if parts[1] == "weekly" else None),
                idempotency_key=self._telegram_idempotency(message, "reminder"),
            )
        except Exception as exc:
            await self.telegram.send_message(
                message.chat.get("id"),
                f"❌ {escape(str(exc))}",
            )
            return
        await self._domain_reply(
            message,
            lambda service, owner: (
                lambda row: f"✅ Reminder <b>#{row.id}</b> scheduled."
            )(service.create_reminder(owner, data)),
        )

    async def _v2_list_reminders(self, message: TelegramMessage) -> None:
        def operation(service, owner):
            rows = service.list_reminders(owner, limit=20)
            if not rows:
                return "No reminders yet."
            return "<b>Reminders</b>\n" + "\n".join(
                f"• <b>#{row.id}</b> [{'active' if row.enabled else 'paused'}] "
                f"{escape(row.title[:100])} — {row.next_run_at_utc}"
                for row in rows
            )

        await self._domain_reply(message, operation)

    async def _v2_edit_reminder(self, message: TelegramMessage) -> None:
        parts = (message.text or "").split(maxsplit=5)
        if len(parts) != 6 or not parts[1].isdigit():
            await self._usage(
                message,
                "/editreminder ID YYYY-MM-DD HH:MM TIMEZONE TITLE",
            )
            return
        try:
            record_id = int(parts[1])
            start_at = datetime.fromisoformat(f"{parts[2]}T{parts[3]}")
        except ValueError:
            await self._usage(
                message,
                "/editreminder ID YYYY-MM-DD HH:MM TIMEZONE TITLE",
            )
            return

        def operation(service, owner):
            current = service.get_reminder(owner, record_id)
            row = service.update_reminder(
                owner,
                record_id,
                ReminderUpdate(
                    version=current.version,
                    title=parts[5],
                    start_at_local=start_at,
                    timezone=parts[4],
                    weekday=(
                        start_at.weekday()
                        if current.schedule_type == "weekly"
                        else None
                    ),
                ),
            )
            return f"✅ Reminder <b>#{row.id}</b> updated."

        await self._domain_reply(message, operation)

    async def _v2_pause_reminder(self, message: TelegramMessage) -> None:
        await self._reminder_enabled_command(message, False)

    async def _v2_resume_reminder(self, message: TelegramMessage) -> None:
        await self._reminder_enabled_command(message, True)

    async def _reminder_enabled_command(
        self,
        message: TelegramMessage,
        enabled: bool,
    ) -> None:
        record_id = self._single_id(message)
        if record_id is None:
            await self._usage(
                message,
                "/pausereminder ID or /resumereminder ID",
            )
            return

        def operation(service, owner):
            current = service.get_reminder(owner, record_id)
            row = service.update_reminder(
                owner,
                record_id,
                ReminderUpdate(version=current.version, enabled=enabled),
            )
            state = "resumed" if enabled else "paused"
            return f"✅ Reminder <b>#{row.id}</b> {state}."

        await self._domain_reply(message, operation)

    async def _v2_delete_reminder(self, message: TelegramMessage) -> None:
        await self._v2_delete_by_id(
            message,
            "deletereminder",
            "reminder",
            lambda service, owner, record_id: service.delete_reminder(owner, record_id),
        )

    async def _v2_delete_by_id(
        self,
        message: TelegramMessage,
        command: str,
        label: str,
        delete_operation,
    ) -> None:
        record_id = self._single_id(message)
        if record_id is None:
            await self._usage(message, f"/{command} ID")
            return

        def operation(service, owner):
            delete_operation(service, owner, record_id)
            return f"✅ {label.title()} <b>#{record_id}</b> deleted."

        await self._domain_reply(message, operation)

    async def _usage(self, message: TelegramMessage, value: str) -> None:
        await self.telegram.send_message(
            message.chat.get("id"),
            f"Usage: <code>{escape(value)}</code>",
        )

    @staticmethod
    def _single_id(message: TelegramMessage) -> int | None:
        parts = (message.text or "").split()
        if len(parts) != 2 or not parts[1].isdigit():
            return None
        return int(parts[1])
