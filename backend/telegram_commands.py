"""Deterministic Telegram commands backed by the shared domain services."""

import asyncio
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from html import escape
import logging
from zoneinfo import ZoneInfo

from abuse_controls import QuotaService
from config import settings
from domain.errors import DomainError
from domain.schemas import (
    GoalCreate,
    GoalUpdate,
    LedgerCreate,
    LedgerUpdate,
    NoteCreate,
    NoteUpdate,
    NutritionDraftCreate,
    NutritionItemUpdate,
    NutritionPreferenceUpdate,
    ReminderCreate,
    ReminderUpdate,
    WorkLogCreate,
    WorkLogUpdate,
)
from domain.services import DomainServices
from models import TelegramMessage
from nutrition.providers import get_nutrition_provider

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
        availability = (
            "\n\nâš ï¸ <b>Free staging availability:</b> This deployment can "
            "sleep when inactive. Telegram commands wake it automatically, but "
            "the first response may be delayed. Reminders and Sunday summaries "
            "are best-effort and may arrive late while it is sleeping."
            if settings.inline_staging_worker_enabled
            else ""
        )
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
            "<b>Food:</b> /food, /nutrition, /confirmfood, /savefoodnote, "
            "/editfood, /deletefood, /nutritiontargets\n\n"
            "<b>Assistant follow-up:</b> /answeragent, /confirmagent, "
            "/cancelagent\n\n"
            "<b>Summaries and privacy:</b> /today, /week, /spending, "
            "/settings, /export, /deleteaccount\n\n"
            "Examples:\n"
            "<code>/log Finished tenant-isolation tests</code>\n"
            "<code>/note Ask HR about relocation</code>\n"
            "<code>/expense 240 INR dinner</code>\n"
            "<code>/income 5000 INR freelance payment</code>\n"
            "<code>/remind once 2026-08-10 19:00 Asia/Kolkata Submit assignment</code>"
            + availability,
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

    @staticmethod
    def _consume_summary_quota(service: DomainServices, owner_id: int) -> None:
        QuotaService(service.session).require(
            owner_id,
            "summaries",
            limit=settings.per_user_daily_summary_limit,
        )

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

    async def _v2_create_food(self, message: TelegramMessage) -> None:
        body = self._command_body(message)
        if not body:
            await self._usage(
                message,
                "/food 50 g paneer, 2 medium rotis",
            )
            return
        data = NutritionDraftCreate(
            original_text=body,
            timezone=settings.timezone,
            logged_at_local=datetime.fromtimestamp(message.date, timezone.utc),
            idempotency_key=self._telegram_idempotency(message, "food"),
        )

        def operation(service, owner):
            log = service.estimate_nutrition_draft(
                owner,
                data,
                get_nutrition_provider(settings.nutrition_provider),
            )
            if log.clarification_question:
                return (
                    f"❓ <b>Food draft #{log.id}</b>\n"
                    f"{escape(log.clarification_question)}\n\n"
                    f"Original entry preserved. Use "
                    f"<code>/savefoodnote {log.id}</code> to keep it "
                    "without estimates."
                )
            lines = [
                f"• {escape(item.normalized_name)}: "
                f"{item.quantity_value} {escape(item.quantity_unit or '')}, "
                f"approximately {item.calories} kcal and "
                f"{item.protein_grams} g protein"
                for item in log.items
            ]
            assumptions = "\n".join(
                f"• {escape(value)}" for value in (log.visible_assumptions or [])
            )
            assumption_text = (
                f"\n\n<b>Visible assumptions</b>\n{assumptions}" if assumptions else ""
            )
            status_text = (
                "Saved automatically using your preference."
                if log.status == "confirmed"
                else f"Confirm with <code>/confirmfood {log.id}</code>."
            )
            return (
                f"<b>Food preview #{log.id}</b>\n"
                + "\n".join(lines)
                + f"\n\nApproximately {log.total_calories} kcal, "
                f"{log.total_protein_grams} g protein."
                + assumption_text
                + f"\n\n{status_text}"
            )

        await self._domain_reply(message, operation)

    async def _v2_confirm_food(self, message: TelegramMessage) -> None:
        record_id = self._single_id(message)
        if record_id is None:
            await self._usage(message, "/confirmfood FOOD_ID")
            return

        def operation(service, owner):
            current = service.get_nutrition_log(owner, record_id)
            log = service.confirm_nutrition_log(owner, record_id, current.version)
            return (
                f"✅ Food log <b>#{log.id}</b> confirmed at approximately "
                f"{log.total_calories} kcal and "
                f"{log.total_protein_grams} g protein."
            )

        await self._domain_reply(message, operation)

    async def _v2_save_unestimated_food(self, message: TelegramMessage) -> None:
        record_id = self._single_id(message)
        if record_id is None:
            await self._usage(message, "/savefoodnote FOOD_ID")
            return

        def operation(service, owner):
            current = service.get_nutrition_log(owner, record_id)
            log = service.save_unestimated_nutrition_log(
                owner, record_id, current.version
            )
            return (
                f"✅ Food note <b>#{log.id}</b> saved without nutrition " "estimates."
            )

        await self._domain_reply(message, operation)

    async def _v2_edit_food_item(self, message: TelegramMessage) -> None:
        parts = (message.text or "").split()
        if len(parts) != 7 or not parts[1].isdigit() or not parts[2].isdigit():
            await self._usage(
                message,
                "/editfood FOOD_ID ITEM_ID QUANTITY UNIT CALORIES PROTEIN",
            )
            return
        try:
            log_id = int(parts[1])
            item_id = int(parts[2])
            quantity = Decimal(parts[3])
            calories = Decimal(parts[5])
            protein = Decimal(parts[6])
            unit = parts[4]
        except InvalidOperation:
            await self._usage(
                message,
                "/editfood FOOD_ID ITEM_ID QUANTITY UNIT CALORIES PROTEIN",
            )
            return

        def operation(service, owner):
            item = service.get_nutrition_item(owner, log_id, item_id)
            log = service.update_nutrition_item(
                owner,
                log_id,
                item_id,
                NutritionItemUpdate(
                    version=item.version,
                    quantity_value=quantity,
                    quantity_unit=unit,
                    calories=calories,
                    protein_grams=protein,
                ),
            )
            return (
                f"✅ Food log <b>#{log.id}</b> updated. New approximate "
                f"total: {log.total_calories} kcal, "
                f"{log.total_protein_grams} g protein."
            )

        await self._domain_reply(message, operation)

    async def _v2_delete_food(self, message: TelegramMessage) -> None:
        await self._v2_delete_by_id(
            message,
            "deletefood",
            "food log",
            lambda service, owner, record_id: service.delete_nutrition_log(
                owner, record_id
            ),
        )

    async def _v2_nutrition_summary(self, message: TelegramMessage) -> None:
        body = self._command_body(message)
        try:
            local_date = (
                date.fromisoformat(body)
                if body
                else datetime.now(ZoneInfo(settings.timezone)).date()
            )
        except ValueError:
            await self._usage(message, "/nutrition [YYYY-MM-DD]")
            return

        def operation(service, owner):
            self._consume_summary_quota(service, owner)
            summary = service.summarize_nutrition(owner, local_date, local_date)
            target_lines = []
            if summary["calorie_target"] is not None:
                target_lines.append(f"Calorie target: {summary['calorie_target']} kcal")
            if summary["protein_target_grams"] is not None:
                target_lines.append(
                    f"Protein target: " f"{summary['protein_target_grams']} g"
                )
            targets = "\n" + "\n".join(target_lines) if target_lines else ""
            return (
                f"<b>Nutrition for {local_date}</b>\n"
                f"Approximately {summary['total_calories']} kcal\n"
                f"Approximately {summary['total_protein_grams']} g protein\n"
                f"Confirmed meals: {summary['confirmed_meals']}\n"
                f"Unestimated food notes: {summary['unestimated_meals']}"
                f"{targets}"
            )

        await self._domain_reply(message, operation)

    async def _v2_nutrition_targets(self, message: TelegramMessage) -> None:
        parts = (message.text or "").split()
        if len(parts) not in {3, 5}:
            await self._usage(
                message,
                "/nutritiontargets CALORIES PROTEIN [CARBS FAT]",
            )
            return
        try:
            calories = Decimal(parts[1])
            protein = Decimal(parts[2])
            carbs = Decimal(parts[3]) if len(parts) == 5 else None
            fat = Decimal(parts[4]) if len(parts) == 5 else None
        except InvalidOperation:
            await self._usage(
                message,
                "/nutritiontargets CALORIES PROTEIN [CARBS FAT]",
            )
            return

        def operation(service, owner):
            preferences = service.get_nutrition_preferences(owner)
            updated = service.update_nutrition_preferences(
                owner,
                NutritionPreferenceUpdate(
                    version=preferences.version,
                    calorie_target=calories,
                    protein_target_grams=protein,
                    carbohydrate_target_grams=carbs,
                    fat_target_grams=fat,
                ),
            )
            return (
                "✅ Your own nutrition targets were saved: "
                f"{updated.calorie_target} kcal and "
                f"{updated.protein_target_grams} g protein."
            )

        await self._domain_reply(message, operation)

    async def _v2_today_summary(self, message: TelegramMessage) -> None:
        def operation(service, owner):
            self._consume_summary_quota(service, owner)
            preferences = service.get_schedule_preferences(owner)
            local_date = datetime.now(ZoneInfo(preferences["timezone"])).date()
            work = service.list_work_logs(
                owner,
                start_date=local_date,
                end_date=local_date,
                limit=20,
            )
            ledger = service.summarize_ledger(
                owner,
                start_date=local_date,
                end_date=local_date,
            )
            nutrition = service.summarize_nutrition(
                owner,
                local_date,
                local_date,
            )
            work_text = (
                "No work logs"
                if not work
                else "; ".join(escape(row.original_text[:100]) for row in work)
            )
            money_text = (
                "No ledger entries"
                if not ledger
                else "; ".join(
                    f"{row['currency']}: expense {row['expense_minor']}, "
                    f"income {row['income_minor']} minor units"
                    for row in ledger
                )
            )
            return (
                f"<b>Today — {local_date}</b>\n"
                f"Work: {work_text}\n"
                f"Money: {money_text}\n"
                f"Nutrition: approximately {nutrition['total_calories']} kcal, "
                f"{nutrition['total_protein_grams']} g protein"
            )

        await self._domain_reply(message, operation)

    async def _v2_week_summary(self, message: TelegramMessage) -> None:
        def operation(service, owner):
            self._consume_summary_quota(service, owner)
            preferences = service.get_schedule_preferences(owner)
            local_date = datetime.now(ZoneInfo(preferences["timezone"])).date()
            start = local_date - timedelta(days=local_date.weekday())
            work = service.list_work_logs(
                owner,
                start_date=start,
                end_date=local_date,
                limit=50,
            )
            if not work:
                return f"No work logs from {start} through {local_date}."
            return f"<b>This week — {start} to {local_date}</b>\n" + "\n".join(
                f"• {escape(row.original_text[:140])}" for row in work
            )

        await self._domain_reply(message, operation)

    async def _v2_spending_summary(self, message: TelegramMessage) -> None:
        def operation(service, owner):
            self._consume_summary_quota(service, owner)
            totals = service.summarize_ledger(owner)
            if not totals:
                return "No ledger entries yet."
            return "<b>Ledger totals</b>\n" + "\n".join(
                f"{row['currency']}: expense {row['expense_minor']}, "
                f"income {row['income_minor']} minor units"
                for row in totals
            )

        await self._domain_reply(message, operation)

    async def _v2_settings_link(self, message: TelegramMessage) -> None:
        await self.telegram.send_message(
            message.chat.get("id"),
            "Open the authenticated Telegram Mini App to edit settings."
            + (
                f"\n{escape(settings.telegram_mini_app_url)}"
                if settings.telegram_mini_app_url
                else ""
            ),
        )

    async def _v2_export_link(self, message: TelegramMessage) -> None:
        await self.telegram.send_message(
            message.chat.get("id"),
            "Open the Mini App's Export data screen for a private JSON or "
            "CSV ZIP download."
            + (
                f"\n{escape(settings.telegram_mini_app_url)}"
                if settings.telegram_mini_app_url
                else ""
            ),
        )

    async def _v2_delete_account_link(self, message: TelegramMessage) -> None:
        await self.telegram.send_message(
            message.chat.get("id"),
            "Account deletion requires recent Telegram authentication, the "
            "exact confirmation phrase, acknowledgement, and final "
            "confirmation in the Mini App."
            + (
                f"\n{escape(settings.telegram_mini_app_url)}"
                if settings.telegram_mini_app_url
                else ""
            ),
        )

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
