"""Bounded assistant orchestration over tenant-scoped domain operations."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from difflib import SequenceMatcher
from hashlib import sha256
from html import escape
import json
import re
from typing import Callable
import uuid
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from sqlalchemy.orm import Session

from abuse_controls import GlobalQuotaExceeded, QuotaExceeded, QuotaService
from assistant.providers import IntentProvider
from assistant.schemas import (
    READ_ONLY_ACTIONS,
    SELECTOR_ACTIONS,
    AgentProposal,
    ClarificationAction,
    CreateGoalAction,
    CreateLedgerAction,
    CreateNoteAction,
    CreateNutritionAction,
    CreateReminderAction,
    CreateWorkLogAction,
    DeleteManyRecordsAction,
    DeleteRecordAction,
    ListRecordsAction,
    QueryAction,
    RetrievePrivateFactAction,
    RecordGoalProgressAction,
    SetRecordStatusAction,
    SmalltalkAction,
    UnsupportedAction,
    UpdateRecordAction,
    UpdateSettingsAction,
)
from domain.errors import DomainError, RecordNotFound
from domain.schemas import (
    EstimatedNutritionItem,
    GoalCreate,
    GoalUpdate,
    LedgerCreate,
    LedgerUpdate,
    NoteCreate,
    NoteUpdate,
    NutritionDraftCreate,
    NutritionManualSave,
    ReminderCreate,
    ReminderUpdate,
    SchedulePreferenceUpdate,
    WorkLogCreate,
    WorkLogUpdate,
)
from domain.services import DomainServices
from nutrition.providers import NutritionEstimationProvider
from public_models import (
    AgentAction,
    AgentPendingAction,
    AgentRun,
    LedgerEntry,
    Note,
    NutritionLog,
    PublicUser,
    PrivateFact,
    PrivateFactAudit,
    Reminder,
    TrackedGoal,
    WorkLog,
)
from config import settings
from vault_crypto import VaultCipher, VaultConfigurationError, VaultDecryptionError
from vault_policy import VaultFactInput, mask_private_fact

UTC = timezone.utc

# Pending states that are still awaiting the user. Anything else is resolved.
OPEN_PENDING_STATES = ("clarification", "confirmation", "disambiguation")

# Shown whenever a request falls outside the assistant, so the capability
# surface is learned in context rather than from a command list.
CAPABILITY_HINT = (
    "I can track work, notes, money, reminders, goals and meals. Try:\n"
    '• "spent 200 rupees on lunch"\n'
    '• "remind me to call Ravi tomorrow at 6 pm"\n'
    '• "show me all my notes"\n'
    '• "pause my water reminder"\n'
    '• "delete my note about the invoice"'
)


@dataclass(frozen=True)
class ActorContext:
    telegram_id: int
    first_name: str
    last_name: str | None = None
    username: str | None = None


@dataclass(frozen=True)
class AssistantReply:
    text: str
    status: str
    record_type: str | None = None
    record_id: int | None = None
    pending_id: int | None = None
    # Candidate (record_id, label) pairs the caller should render as choices
    # when a spoken reference matched more than one record.
    options: tuple[tuple[int, str], ...] = ()


class BoundedAssistant:
    """Validates untrusted model proposals before calling named tools."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        provider: IntentProvider,
        nutrition_provider: NutritionEstimationProvider,
        *,
        min_confidence: float = 0.8,
        pending_ttl_minutes: int = 30,
        max_input_length: int = 4000,
        daily_ai_limit: int = 25,
        daily_summary_limit: int = 30,
        global_daily_ai_limit: int = 0,
        clock: Callable[[], datetime] | None = None,
    ):
        self.session_factory = session_factory
        self.provider = provider
        self.nutrition_provider = nutrition_provider
        self.min_confidence = min_confidence
        self.pending_ttl_minutes = pending_ttl_minutes
        self.max_input_length = max_input_length
        self.daily_ai_limit = daily_ai_limit
        self.daily_summary_limit = daily_summary_limit
        # Zero disables the deployment-wide ceiling; a private deployment does
        # not need one, a public one does.
        self.global_daily_ai_limit = global_daily_ai_limit
        self.clock = clock or (lambda: datetime.now(UTC))

    def handle(
        self,
        actor: ActorContext,
        text: str,
        *,
        update_id: int,
        review_required: bool = False,
    ) -> AssistantReply:
        text = text.strip()
        if not text or len(text) > self.max_input_length:
            return AssistantReply(
                "Please send a shorter, non-empty request.",
                "rejected",
            )
        if self._is_direct_account_reset_request(text):
            return AssistantReply(
                "For safety, voice and ordinary chat can never erase your whole "
                "account. If you intend a permanent reset, type "
                "<code>/resetmydata DELETE MY ACCOUNT</code> exactly; I will still "
                "ask for one final tap.",
                "rejected",
            )
        idempotency_key = f"agent:{actor.telegram_id}:{update_id}"
        existing = self._existing_reply(actor.telegram_id, idempotency_key)
        if existing is not None:
            return existing
        try:
            vault_capture = self._parse_vault_capture(text)
        except (ValidationError, ValueError) as exc:
            if isinstance(exc, ValidationError):
                detail = str(exc.errors()[0].get("msg", "Invalid vault value"))
                detail = detail.removeprefix("Value error, ")
            else:
                detail = str(exc)
            return AssistantReply(
                f"I could not save that vault item: {escape(detail)}.",
                "rejected",
            )
        if vault_capture is not None:
            return self._prepare_private_fact_create(
                actor,
                text,
                update_id,
                idempotency_key,
                vault_capture,
            )
        manual_nutrition = self._parse_manual_nutrition(text)
        if manual_nutrition is not None:
            owner_id, run_id, default_timezone = self._start_run(
                actor,
                text,
                update_id,
                consume_ai_quota=False,
            )
            proposal = AgentProposal(
                confidence=1,
                action=CreateNutritionAction(
                    kind="create_nutrition_log",
                    text=text,
                    meal_name=manual_nutrition["meal_name"],
                    timezone=default_timezone,
                    calories=manual_nutrition["calories"],
                    protein_grams=manual_nutrition["protein_grams"],
                ),
            )
            return self._apply_proposal(
                owner_id,
                run_id,
                proposal,
                update_id=update_id,
                idempotency_key=idempotency_key,
                review_required=review_required,
            )
        try:
            owner_id, run_id, default_timezone = self._start_run(actor, text, update_id)
        except GlobalQuotaExceeded:
            return AssistantReply(
                "I am at capacity right now and cannot interpret new requests "
                "today. Slash commands still work, and this resets at midnight "
                "UTC.",
                "rejected",
            )
        except QuotaExceeded:
            return AssistantReply(
                "Your daily assistant limit has been reached. "
                "Deterministic slash commands still work.",
                "rejected",
            )
        context = {
            "current_utc": self.clock().isoformat(),
            "default_timezone": default_timezone,
            "review_required": review_required,
        }
        try:
            raw = self.provider.classify(text, context=context)
            proposal = AgentProposal.model_validate(raw)
            proposal = self._normalize_contextual_queries(
                proposal,
                text,
                default_timezone,
            )
        except ValidationError:
            self._fail_run(run_id, "invalid_provider_schema")
            return AssistantReply(
                "I did not understand that confidently enough to act, so nothing "
                "was saved. Please try once more in a short sentence.",
                "failed",
            )
        except Exception:
            self._fail_run(run_id, "provider_failure")
            return AssistantReply(
                "I could not interpret that message just now, so nothing was saved. "
                "Please resend it, or use /help for a direct command.",
                "failed",
            )
        return self._apply_proposal(
            owner_id,
            run_id,
            proposal,
            update_id=update_id,
            idempotency_key=idempotency_key,
            review_required=review_required,
        )

    def _normalize_contextual_queries(
        self,
        proposal: AgentProposal,
        text: str,
        default_timezone: str,
    ) -> AgentProposal:
        """Make explicit time/ranking words authoritative over model omissions."""
        normalized = " ".join(text.casefold().split())
        rewritten = []
        for action in proposal.proposed_actions:
            if not isinstance(action, QueryAction) or action.query_type != "spending":
                rewritten.append(action)
                continue
            updates = {}
            try:
                zone = ZoneInfo(action.timezone or default_timezone)
            except Exception:
                zone = ZoneInfo(default_timezone)
            today = self.clock().astimezone(zone).date()
            if "last month" in normalized:
                previous_end = today.replace(day=1) - timedelta(days=1)
                updates.update(
                    start_date=previous_end.replace(day=1),
                    end_date=previous_end,
                )
            elif "this month" in normalized:
                updates.update(start_date=today.replace(day=1), end_date=today)
            if action.ranking is None:
                if re.search(r"\b(?:most|highest|maximum)\b", normalized):
                    updates["ranking"] = "highest"
                elif re.search(r"\b(?:least|lowest|minimum)\b", normalized):
                    updates["ranking"] = "lowest"
            if action.search is None:
                match = re.search(
                    r"\b(?:spend|spent)\s+on\s+(?P<search>.+?)\s+"
                    r"(?:this|last)\s+month\b",
                    normalized,
                )
                if match:
                    updates["search"] = match.group("search").strip(' ,.?"')[:200]
            rewritten.append(action.model_copy(update=updates) if updates else action)
        return proposal.model_copy(
            update={
                "action": rewritten[0] if proposal.action is not None else None,
                "actions": rewritten if proposal.actions is not None else None,
            }
        )

    @staticmethod
    def _is_direct_account_reset_request(text: str) -> bool:
        """Recognise a direct reset request without scanning quoted note data."""
        normalized = " ".join(text.casefold().split())
        if re.match(
            r"^(?:create|save|write|remember|add|make)\b.*\b(?:note|log)\b",
            normalized,
        ):
            return False
        return bool(
            re.match(
                r"^(?:please\s+)?(?:i\s+(?:want|need|would\s+like)\s+"
                r"(?:you\s+)?to\s+)?(?:reset|delete|erase|remove)\b",
                normalized,
            )
            and re.search(
                r"\b(?:account|everything|all\s+(?:of\s+)?(?:my\s+)?data|"
                r"all\s+(?:of\s+)?(?:my\s+)?records)\b",
                normalized,
            )
        )

    @staticmethod
    def _parse_manual_nutrition(text: str) -> dict[str, Decimal | str] | None:
        """Extract exact whole-meal macros the user explicitly supplied."""
        if not re.search(
            r"^\s*(?:i\s+)?(?:ate|had|consumed)\b|^\s*(?:log|add|record)\b.*\bfood\b",
            text,
            re.IGNORECASE,
        ):
            return None
        calorie_match = re.search(
            r"(?P<value>\d+(?:\.\d+)?)\s*(?:kcal|calories?|cals?)\b",
            text,
            re.IGNORECASE,
        )
        protein_match = re.search(
            r"(?P<value>\d+(?:\.\d+)?)\s*(?:g|grams?)?\s*(?:of\s+)?protein\b",
            text,
            re.IGNORECASE,
        ) or re.search(
            r"\bprotein\s*(?P<value>\d+(?:\.\d+)?)\s*(?:g|grams?)?\b",
            text,
            re.IGNORECASE,
        )
        if calorie_match is None or protein_match is None:
            return None
        cleaned = re.sub(
            r"\b\d+(?:\.\d+)?\s*(?:kcal|calories?|cals?)\b",
            " ",
            text,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            r"\b\d+(?:\.\d+)?\s*(?:g|grams?)?\s*(?:of\s+)?protein\b|"
            r"\bprotein\s*\d+(?:\.\d+)?\s*(?:g|grams?)?\b",
            " ",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            r"^\s*(?:i\s+)?(?:ate|had|consumed)\s+",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            r"\b(?:with|and|containing|which has|that has)\b",
            " ",
            cleaned,
            flags=re.IGNORECASE,
        )
        meal_name = " ".join(cleaned.strip(" ,.;:-").split()) or "User-described meal"
        return {
            "meal_name": meal_name[:128],
            "calories": Decimal(calorie_match.group("value")),
            "protein_grams": Decimal(protein_match.group("value")),
        }

    # Two questions is generous for a bounded tracker. Anything beyond that is
    # a provider that cannot converge, not a user who is being unclear.
    MAX_CLARIFICATION_ROUNDS = 2

    def _abandon_clarification(self, pending: AgentPendingAction) -> AssistantReply:
        """Close a question loop and hand the user a concrete way forward."""
        with self.session_factory() as session:
            current = session.get(AgentPendingAction, pending.id)
            if current is not None and current.state == "clarification":
                current.state = "cancelled"
                current.resolved_at_utc = self.clock()
                session.commit()
        return AssistantReply(
            "I could not work that one out, so I have stopped asking and saved "
            "nothing. Try saying it as one complete sentence — for example "
            '"add an expense of 200 rupees for lunch" or "show my notes".',
            "cancelled",
        )

    def _open_pending_id(self, telegram_id: int, state: str) -> int | None:
        """Return the caller's newest unexpired pending item in ``state``."""
        with self.session_factory() as session:
            pending = (
                session.query(AgentPendingAction)
                .join(PublicUser, PublicUser.id == AgentPendingAction.owner_id)
                .filter(
                    PublicUser.telegram_id == telegram_id,
                    AgentPendingAction.state == state,
                )
                .order_by(AgentPendingAction.id.desc())
                .first()
            )
            if pending is None:
                return None
            expires = pending.expires_at_utc
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=UTC)
            return pending.id if expires > self.clock() else None

    def open_clarification_id(self, telegram_id: int) -> int | None:
        """Return the caller's newest unanswered question, if one is waiting.

        This lets a spoken or typed reply continue the conversation naturally
        instead of requiring the user to quote a command and a pending id.
        """
        return self._open_pending_id(telegram_id, "clarification")

    def open_confirmation_id(self, telegram_id: int) -> int | None:
        """Return a review that can be confirmed by an explicit chat reply."""
        return self._open_pending_id(telegram_id, "confirmation")

    def answer_clarification(
        self,
        actor: ActorContext,
        pending_id: int,
        answer: str,
    ) -> AssistantReply:
        pending = self._load_pending(actor.telegram_id, pending_id)
        if pending is None:
            return AssistantReply("Pending action not found.", "rejected")
        if pending.state != "clarification":
            return AssistantReply(
                "That action is not waiting for clarification.",
                "rejected",
            )
        if self._expire_if_needed(pending):
            return AssistantReply("That clarification has expired.", "expired")
        # Each unanswered round increments the version. Past the cap the
        # assistant is not converging, and asking again would loop forever
        # while burning provider calls on every turn.
        if pending.version > self.MAX_CLARIFICATION_ROUNDS:
            return self._abandon_clarification(pending)
        context = {
            "intended_kind": pending.action_type,
            "known_arguments": pending.proposed_arguments,
            "missing_fields": pending.missing_fields,
            "clarification_question": pending.prompt,
            "clarification_round": pending.version,
            "final_round": pending.version >= self.MAX_CLARIFICATION_ROUNDS,
        }
        try:
            self._consume_ai_quota(pending.owner_id)
        except QuotaExceeded:
            return AssistantReply(
                "Your daily assistant limit has been reached.",
                "rejected",
                pending_id=pending_id,
            )
        try:
            proposal = AgentProposal.model_validate(
                self.provider.classify(answer.strip(), context=context)
            )
        except ValidationError:
            return AssistantReply(
                "I did not understand that answer confidently enough. "
                "Nothing was saved.",
                "failed",
                pending_id=pending_id,
            )
        except Exception:
            return AssistantReply(
                "I could not interpret that answer just now. Please send it once more.",
                "failed",
                pending_id=pending_id,
            )
        with self.session_factory() as session:
            current = (
                session.query(AgentPendingAction)
                .filter(
                    AgentPendingAction.id == pending_id,
                    AgentPendingAction.owner_id == pending.owner_id,
                    AgentPendingAction.state == "clarification",
                )
                .one_or_none()
            )
            if current is None:
                return AssistantReply("Pending action not found.", "rejected")
            # The provider returns the batch shape, so the single-action field
            # is empty here. Read through the accessor that handles both.
            follow_up = next(
                (
                    action
                    for action in proposal.proposed_actions
                    if isinstance(action, ClarificationAction)
                ),
                None,
            )
            if follow_up is not None:
                if current.version >= self.MAX_CLARIFICATION_ROUNDS:
                    session.expunge(current)
                    return self._abandon_clarification(current)
                current.action_type = follow_up.intended_kind
                current.proposed_arguments = follow_up.known_arguments
                current.missing_fields = follow_up.missing_fields
                current.prompt = follow_up.question
                current.version += 1
                session.commit()
                return AssistantReply(
                    escape(follow_up.question),
                    "clarification",
                    pending_id=current.id,
                )
            run_id = current.run_id
            owner_id = current.owner_id
            update_id = current.original_update_id
            idempotency_key = current.idempotency_key
        reply = self._apply_proposal(
            owner_id,
            run_id,
            proposal,
            update_id=update_id,
            idempotency_key=idempotency_key,
            replace_existing=True,
        )
        if reply.status in {"completed", "rejected"}:
            with self.session_factory() as session:
                current = session.get(AgentPendingAction, pending_id)
                if current and current.state == "clarification":
                    current.state = (
                        "executed" if reply.status == "completed" else "cancelled"
                    )
                    current.resolved_at_utc = self.clock()
                    session.commit()
        return reply

    def confirm(
        self,
        actor: ActorContext,
        pending_id: int,
    ) -> AssistantReply:
        pending = self._load_pending(actor.telegram_id, pending_id)
        if pending is None:
            return AssistantReply("Pending action not found.", "rejected")
        if pending.state == "executed":
            return AssistantReply("That action was already completed.", "completed")
        if pending.state != "confirmation":
            return AssistantReply(
                "That action is not waiting for confirmation.",
                "rejected",
            )
        if self._expire_if_needed(pending):
            return AssistantReply("That confirmation has expired.", "expired")
        if pending.proposed_arguments.get("kind") == "batch":
            return self._confirm_batch(pending)
        if pending.proposed_arguments.get("kind") == "delete_many_snapshot":
            return self._confirm_delete_many(pending)
        if pending.proposed_arguments.get("kind") == "reveal_private_fact":
            return self._confirm_private_fact_reveal(pending)
        if pending.proposed_arguments.get("kind") == "create_private_fact_encrypted":
            return self._confirm_private_fact_create(pending)
        try:
            proposal = AgentProposal.model_validate(
                {
                    "confidence": 1,
                    "action": pending.proposed_arguments,
                }
            )
        except ValidationError:
            return AssistantReply("The stored proposal is no longer valid.", "failed")
        if not isinstance(proposal.action, DeleteRecordAction):
            return AssistantReply("Unsupported confirmation action.", "rejected")
        with self.session_factory() as session:
            current = (
                session.query(AgentPendingAction)
                .filter(
                    AgentPendingAction.id == pending_id,
                    AgentPendingAction.owner_id == pending.owner_id,
                    AgentPendingAction.state == "confirmation",
                )
                .with_for_update()
                .one_or_none()
            )
            if current is None:
                return AssistantReply("Pending action not found.", "rejected")
            service = DomainServices(session)
            try:
                self._delete_record(
                    service,
                    current.owner_id,
                    proposal.action,
                )
            except RecordNotFound:
                current.state = "executed"
                current.resolved_at_utc = self.clock()
                self._update_action(
                    session,
                    current.owner_id,
                    current.idempotency_key,
                    status="executed",
                )
                session.commit()
                return AssistantReply(
                    "The record was already absent.",
                    "completed",
                )
            current.state = "executed"
            current.resolved_at_utc = self.clock()
            self._update_action(
                session,
                current.owner_id,
                current.idempotency_key,
                status="executed",
            )
            run = session.get(AgentRun, current.run_id)
            if run:
                run.status = "completed"
                run.completed_at_utc = self.clock()
            session.commit()
        return AssistantReply(
            f"{proposal.action.record_type.replace('_', ' ').title()} "
            f"#{proposal.action.record_id} deleted.",
            "completed",
            proposal.action.record_type,
            proposal.action.record_id,
        )

    def _confirm_batch(self, pending: AgentPendingAction) -> AssistantReply:
        raw_actions = pending.proposed_arguments.get("actions")
        if not isinstance(raw_actions, list) or not raw_actions:
            return AssistantReply("The stored review is no longer valid.", "failed")
        try:
            actions = [
                AgentProposal.model_validate(
                    {"confidence": 1, "action": raw_action}
                ).proposed_actions[0]
                for raw_action in raw_actions
            ]
        except ValidationError:
            return AssistantReply("The stored review is no longer valid.", "failed")
        if any(
            isinstance(action, (ClarificationAction, UnsupportedAction))
            for action in actions
        ):
            return AssistantReply("The stored review cannot be executed.", "failed")

        try:
            with self.session_factory() as session:
                current = (
                    session.query(AgentPendingAction)
                    .filter(
                        AgentPendingAction.id == pending.id,
                        AgentPendingAction.owner_id == pending.owner_id,
                        AgentPendingAction.state == "confirmation",
                    )
                    .with_for_update()
                    .one_or_none()
                )
                if current is None:
                    return AssistantReply("That review is already closed.", "completed")
                service = DomainServices(session)
                results: list[str] = []
                nutrition_reply: AssistantReply | None = None
                for index, action in enumerate(actions, start=1):
                    if isinstance(action, DeleteRecordAction):
                        try:
                            self._delete_record(service, current.owner_id, action)
                            results.append(
                                f"{action.record_type.replace('_', ' ').title()} "
                                f"#{action.record_id} deleted."
                            )
                        except RecordNotFound:
                            results.append(
                                f"{action.record_type.replace('_', ' ').title()} "
                                f"#{action.record_id} was already absent."
                            )
                        continue
                    reply = self._execute_tool(
                        service,
                        current.owner_id,
                        f"{current.idempotency_key}:{index}",
                        action,
                    )
                    results.append(reply.text)
                    if reply.status == "nutrition_confirmation":
                        nutrition_reply = reply
                current.state = "executed"
                current.resolved_at_utc = self.clock()
                self._update_action(
                    session,
                    current.owner_id,
                    current.idempotency_key,
                    status="executed",
                )
                run = session.get(AgentRun, current.run_id)
                if run:
                    run.status = "completed"
                    run.completed_at_utc = self.clock()
                session.commit()
        except (DomainError, ValueError) as exc:
            return AssistantReply(escape(str(exc)), "failed", pending_id=pending.id)
        text = "Confirmed and saved:\n" + "\n".join(
            f"{index}. {result}" for index, result in enumerate(results, start=1)
        )
        if nutrition_reply is not None:
            return AssistantReply(
                text,
                "nutrition_confirmation",
                "nutrition_log",
                nutrition_reply.record_id,
            )
        return AssistantReply(text, "completed")

    def confirm_nutrition_preview(
        self,
        actor: ActorContext,
        record_id: int,
    ) -> AssistantReply:
        """Confirm one draft, scoped only to the Telegram account that tapped."""
        with self.session_factory() as session:
            service = DomainServices(session)
            try:
                owner = service.get_owner_by_telegram_id(actor.telegram_id)
                current = service.get_nutrition_log(owner.id, record_id)
                if current.status == "confirmed":
                    return AssistantReply(
                        "That meal was already confirmed.",
                        "completed",
                        "nutrition_log",
                        current.id,
                    )
                row = service.confirm_nutrition_log(
                    owner.id,
                    current.id,
                    current.version,
                )
            except RecordNotFound:
                return AssistantReply(
                    "That food preview is not available for this account.",
                    "rejected",
                )
            session.commit()
            return AssistantReply(
                f"Food log #{row.id} confirmed: approximately "
                f"{row.total_calories} kcal and "
                f"{row.total_protein_grams} g protein.",
                "completed",
                "nutrition_log",
                row.id,
            )

    def cancel_nutrition_preview(
        self,
        actor: ActorContext,
        record_id: int,
    ) -> AssistantReply:
        """Discard an owned draft so a Wrong tap leaves no nutrition record."""
        with self.session_factory() as session:
            service = DomainServices(session)
            try:
                owner = service.get_owner_by_telegram_id(actor.telegram_id)
                current = service.get_nutrition_log(owner.id, record_id)
                if current.status != "draft":
                    return AssistantReply(
                        "Only an unconfirmed food preview can be discarded.",
                        "rejected",
                    )
                service.delete_nutrition_log(owner.id, current.id)
            except RecordNotFound:
                return AssistantReply(
                    "That food preview is not available for this account.",
                    "rejected",
                )
            session.commit()
        return AssistantReply(
            "Food preview discarded. Nothing was counted.",
            "cancelled",
        )

    def cancel(self, actor: ActorContext, pending_id: int) -> AssistantReply:
        pending = self._load_pending(actor.telegram_id, pending_id)
        if pending is None:
            return AssistantReply("Pending action not found.", "rejected")
        with self.session_factory() as session:
            current = (
                session.query(AgentPendingAction)
                .filter(
                    AgentPendingAction.id == pending_id,
                    AgentPendingAction.owner_id == pending.owner_id,
                    AgentPendingAction.state.in_(OPEN_PENDING_STATES),
                )
                .one_or_none()
            )
            if current is None:
                return AssistantReply("That action is already closed.", "completed")
            current.state = "cancelled"
            current.resolved_at_utc = self.clock()
            self._update_action(
                session,
                current.owner_id,
                current.idempotency_key,
                status="cancelled",
            )
            session.commit()
        return AssistantReply("Pending action cancelled.", "cancelled")

    def _start_run(
        self,
        actor: ActorContext,
        text: str,
        update_id: int,
        *,
        consume_ai_quota: bool = True,
    ) -> tuple[int, int, str]:
        with self.session_factory() as session:
            service = DomainServices(session)
            owner = service.ensure_owner(
                telegram_id=actor.telegram_id,
                first_name=actor.first_name,
                last_name=actor.last_name,
                username=actor.username,
            )
            if consume_ai_quota:
                quotas = QuotaService(session)
                quotas.require(
                    owner.id,
                    "ai_classifications",
                    limit=self.daily_ai_limit,
                )
                if self.global_daily_ai_limit > 0:
                    quotas.require_global(
                        "ai_classifications",
                        limit=self.global_daily_ai_limit,
                    )
            default_timezone = service.get_schedule_preferences(owner.id)["timezone"]
            run = AgentRun(
                owner_id=owner.id,
                provider=(self.provider.provider_name if consume_ai_quota else "local"),
                model=(self.provider.model_name[:128] if consume_ai_quota else "vault"),
                input_hash=sha256(text.encode("utf-8")).hexdigest(),
                original_update_id=update_id,
            )
            session.add(run)
            session.commit()
            return owner.id, run.id, default_timezone

    def _consume_ai_quota(self, owner_id: int) -> None:
        with self.session_factory() as session:
            QuotaService(session).require(
                owner_id,
                "ai_classifications",
                limit=self.daily_ai_limit,
            )
            session.commit()

    def _apply_proposal(
        self,
        owner_id: int,
        run_id: int,
        proposal: AgentProposal,
        *,
        update_id: int,
        idempotency_key: str,
        replace_existing: bool = False,
        review_required: bool = False,
    ) -> AssistantReply:
        actions = proposal.proposed_actions
        unsupported = next(
            (action for action in actions if isinstance(action, UnsupportedAction)),
            None,
        )
        if unsupported is not None:
            # Teach the capability surface at the moment of failure. This is
            # where a user actually wonders what the bot can do, and it means
            # discovering features never requires reading a command list.
            return self._reject(
                owner_id,
                run_id,
                idempotency_key,
                unsupported.kind,
                unsupported.reason + "\n\n" + CAPABILITY_HINT,
            )
        clarification = next(
            (action for action in actions if isinstance(action, ClarificationAction)),
            None,
        )
        if clarification is not None:
            return self._pending(
                owner_id,
                run_id,
                idempotency_key,
                update_id,
                state="clarification",
                action_type=clarification.intended_kind,
                arguments=clarification.known_arguments,
                missing_fields=clarification.missing_fields,
                prompt=clarification.question,
                replace_existing=replace_existing,
            )
        if any(isinstance(action, DeleteManyRecordsAction) for action in actions):
            if len(actions) != 1:
                return self._reject(
                    owner_id,
                    run_id,
                    idempotency_key,
                    "delete_many_records",
                    "Please ask for a bulk deletion on its own so I can show "
                    "one clear review.",
                )
            return self._prepare_delete_many(
                owner_id,
                run_id,
                idempotency_key,
                update_id,
                actions[0],
                replace_existing=replace_existing,
            )
        if any(isinstance(action, RetrievePrivateFactAction) for action in actions):
            if len(actions) != 1:
                return self._reject(
                    owner_id,
                    run_id,
                    idempotency_key,
                    "retrieve_private_fact",
                    "Please ask for one vault item at a time.",
                )
            return self._prepare_private_fact_reveal(
                owner_id,
                run_id,
                idempotency_key,
                update_id,
                actions[0],
                replace_existing=replace_existing,
            )
        # A spoken deletion names a record the way a person would. Resolve that
        # to a concrete row before anything is reviewed or stored, so every
        # later stage works with an unambiguous, owner-verified target.
        actions, early_reply = self._resolve_deletions(
            owner_id,
            run_id,
            idempotency_key,
            update_id,
            actions,
            replace_existing=replace_existing,
        )
        if early_reply is not None:
            return early_reply

        # A nutrition preview is itself the review surface: it contains the
        # interpreted food, item estimates, totals, and assumptions. Creating
        # the draft here avoids a confusing review followed by a second
        # /confirmfood step. Drafts never count toward daily totals.
        if len(actions) == 1 and isinstance(actions[0], CreateNutritionAction):
            return self._execute(
                owner_id,
                run_id,
                idempotency_key,
                actions[0],
                replace_existing=replace_existing,
            )

        # Reading owned records or answering conversationally cannot change
        # anything, so neither the review step nor the confidence floor applies.
        # Both exist to protect writes, and applying them here only forces a
        # button tap between the user and an answer they already asked for.
        read_only = all(isinstance(action, READ_ONLY_ACTIONS) for action in actions)
        uncertain = proposal.confidence < self.min_confidence

        if uncertain and not read_only and not review_required:
            arguments = (
                actions[0].model_dump(mode="json")
                if len(actions) == 1
                else {
                    "kind": "batch",
                    "actions": [action.model_dump(mode="json") for action in actions],
                }
            )
            return self._pending(
                owner_id,
                run_id,
                idempotency_key,
                update_id,
                state="clarification",
                action_type=(actions[0].kind if len(actions) == 1 else "batch"),
                arguments=arguments,
                missing_fields=["intent_confirmation"],
                prompt=(
                    "I am not confident enough to act. Please restate the request "
                    "with the exact details I should save."
                ),
                replace_existing=replace_existing,
            )
        if not read_only and (review_required or len(actions) > 1):
            # A reviewed request that the provider was unsure about still goes
            # to the user rather than to a dead end: nothing is saved until the
            # proposal is read and confirmed, so showing it is safe and is far
            # more useful than discarding a usable transcript.
            return self._pending(
                owner_id,
                run_id,
                idempotency_key,
                update_id,
                state="confirmation",
                action_type="batch",
                arguments={
                    "kind": "batch",
                    "actions": [action.model_dump(mode="json") for action in actions],
                },
                missing_fields=[],
                prompt=self._review_prompt(
                    actions,
                    owner_id=owner_id,
                    uncertain=uncertain,
                ),
                replace_existing=replace_existing,
            )
        if len(actions) > 1:
            return self._execute_read_only_batch(
                owner_id,
                run_id,
                idempotency_key,
                actions,
                replace_existing=replace_existing,
            )
        action = actions[0]
        if isinstance(action, DeleteRecordAction):
            return self._pending(
                owner_id,
                run_id,
                idempotency_key,
                update_id,
                state="confirmation",
                action_type=action.kind,
                arguments=action.model_dump(mode="json"),
                missing_fields=[],
                prompt=self._delete_prompt(owner_id, action),
                replace_existing=replace_existing,
            )
        return self._execute(
            owner_id,
            run_id,
            idempotency_key,
            action,
            replace_existing=replace_existing,
        )

    BULK_DELETE_LIMIT = 2000

    @staticmethod
    def _record_model(record_type: str):
        return {
            "work_log": WorkLog,
            "note": Note,
            "reminder": Reminder,
            "ledger_entry": LedgerEntry,
            "nutrition_log": NutritionLog,
            "goal": TrackedGoal,
        }[record_type]

    def _prepare_delete_many(
        self,
        owner_id: int,
        run_id: int,
        idempotency_key: str,
        update_id: int,
        action: DeleteManyRecordsAction,
        *,
        replace_existing: bool,
    ) -> AssistantReply:
        model = self._record_model(action.record_type)
        with self.session_factory() as session:
            ids = [
                row[0]
                for row in session.query(model.id)
                .filter(model.owner_id == owner_id)
                .order_by(model.id.asc())
                .limit(self.BULK_DELETE_LIMIT + 1)
                .all()
            ]
        noun = action.record_type.replace("_", " ")
        if not ids:
            return self._reject(
                owner_id,
                run_id,
                idempotency_key,
                action.kind,
                f"You do not have any {noun} records to delete.",
            )
        if len(ids) > self.BULK_DELETE_LIMIT:
            return self._reject(
                owner_id,
                run_id,
                idempotency_key,
                action.kind,
                f"There are too many {noun} records for one safe chat action. "
                "Use the Mini App instead.",
            )
        return self._pending(
            owner_id,
            run_id,
            idempotency_key,
            update_id,
            state="confirmation",
            action_type=action.kind,
            arguments={
                "kind": "delete_many_snapshot",
                "record_type": action.record_type,
                "record_ids": ids,
            },
            missing_fields=[],
            prompt=(
                f"Delete all {len(ids)} {noun} record"
                f"{'s' if len(ids) != 1 else ''}? This cannot be undone."
            ),
            replace_existing=replace_existing,
        )

    def _confirm_delete_many(self, pending: AgentPendingAction) -> AssistantReply:
        stored = pending.proposed_arguments
        record_type = stored.get("record_type")
        record_ids = stored.get("record_ids")
        if (
            record_type
            not in {
                "work_log",
                "note",
                "reminder",
                "ledger_entry",
                "nutrition_log",
                "goal",
            }
            or not isinstance(record_ids, list)
            or not all(
                isinstance(record_id, int) and record_id > 0 for record_id in record_ids
            )
        ):
            return AssistantReply(
                "The stored deletion review is no longer valid.", "failed"
            )
        deleted = 0
        with self.session_factory() as session:
            current = (
                session.query(AgentPendingAction)
                .filter(
                    AgentPendingAction.id == pending.id,
                    AgentPendingAction.owner_id == pending.owner_id,
                    AgentPendingAction.state == "confirmation",
                )
                .with_for_update()
                .one_or_none()
            )
            if current is None:
                return AssistantReply("That deletion is already closed.", "completed")
            service = DomainServices(session)
            for record_id in record_ids:
                action = DeleteRecordAction(
                    kind="delete_record",
                    record_type=record_type,
                    record_id=record_id,
                )
                try:
                    self._delete_record(service, current.owner_id, action)
                    deleted += 1
                except RecordNotFound:
                    pass
            current.state = "executed"
            current.resolved_at_utc = self.clock()
            self._update_action(
                session,
                current.owner_id,
                current.idempotency_key,
                status="executed",
            )
            run = session.get(AgentRun, current.run_id)
            if run:
                run.status = "completed"
                run.completed_at_utc = self.clock()
            session.commit()
        noun = record_type.replace("_", " ")
        return AssistantReply(
            f"Deleted {deleted} {noun} record{'s' if deleted != 1 else ''}.",
            "completed",
            record_type,
        )

    @staticmethod
    def _parse_vault_capture(text: str) -> VaultFactInput | None:
        """Parse an explicit vault save locally so its value never reaches the LLM."""
        if not re.search(r"\bvault\b", text, re.IGNORECASE) or not re.search(
            r"\b(?:save|store|remember)\b", text, re.IGNORECASE
        ):
            return None

        body = text.strip().rstrip(" .")
        body = re.sub(
            r"^(?:please\s+)?(?:save|store|remember)\s+",
            "",
            body,
            flags=re.IGNORECASE,
        )
        body = re.sub(
            r"^(?:this\s+)?(?:in|into|to)\s+(?:(?:my|the)\s+)?vault[,\s]*",
            "",
            body,
            flags=re.IGNORECASE,
        )
        body = re.sub(
            r"[,\s]+(?:in|into|to)\s+(?:(?:my|the)\s+)?vault$",
            "",
            body,
            flags=re.IGNORECASE,
        ).strip(" ,")

        match = re.match(
            r"^(?:my\s+)?(?P<label>.+?)\s+(?:is|as|equals?)\s+(?P<value>.+)$",
            body,
            flags=re.IGNORECASE,
        )
        if match is None:
            known_label = re.match(
                r"^(?:my\s+)?(?P<label>(?:mobile|phone|telephone|contact)\s+"
                r"(?:number|no\.?|num(?:ber)?\.?)|(?:bank\s+)?account\s+"
                r"(?:number|no\.?|num(?:ber)?\.?)|ifsc(?:\s+code)?|"
                r"(?:aadhaar|aadhar)\s+last\s+(?:four|4)|"
                r"(?:sixth|6th|semester|sem|college|university|academic|my)"
                r"[^,]*?(?:cgpa|gpa|score))[,\s:]+(?P<value>.+)$",
                body,
                flags=re.IGNORECASE,
            )
            match = known_label
        if match is None:
            raise ValueError(
                'say the label and value explicitly, for example "save my mobile '
                'number as 9876543210 in my vault"'
            )

        label = " ".join(match.group("label").split()).strip(" ,:")
        value = " ".join(match.group("value").split()).strip(" ,:")
        lowered = label.lower()
        if re.search(r"\b(?:mobile|phone|telephone|contact)\b", lowered):
            fact_type = "phone"
        elif "ifsc" in lowered:
            fact_type = "ifsc"
        elif "aadhaar" in lowered or "aadhar" in lowered:
            fact_type = "aadhaar_last4"
        elif "account" in lowered:
            fact_type = "bank_account"
        elif re.search(r"\b(?:cgpa|gpa|score)\b", lowered):
            fact_type = "academic_score"
        else:
            fact_type = "other_permitted"
        return VaultFactInput(
            fact_type=fact_type,
            label=label,
            value=value,
            notes=None,
        )

    def _prepare_private_fact_create(
        self,
        actor: ActorContext,
        text: str,
        update_id: int,
        idempotency_key: str,
        fact: VaultFactInput,
    ) -> AssistantReply:
        if not settings.vault_enabled:
            return AssistantReply(
                "The encrypted vault is not enabled on this deployment.",
                "rejected",
            )
        try:
            cipher = VaultCipher(settings.vault_encryption_keys)
        except VaultConfigurationError:
            return AssistantReply("The vault is not available right now.", "failed")

        owner_id, run_id, _ = self._start_run(
            actor,
            text,
            update_id,
            consume_ai_quota=False,
        )
        record_uuid = str(uuid.uuid4())
        encrypted = cipher.encrypt(
            {"value": fact.value, "notes": fact.notes},
            owner_id=owner_id,
            record_uuid=record_uuid,
            fact_type=fact.fact_type,
        )
        masked = mask_private_fact(fact.fact_type, fact.value)
        return self._pending(
            owner_id,
            run_id,
            idempotency_key,
            update_id,
            state="confirmation",
            action_type="create_private_fact",
            arguments={
                "kind": "create_private_fact_encrypted",
                "record_uuid": record_uuid,
                "fact_type": fact.fact_type,
                "label": fact.label,
                "masked_value": masked,
                "ciphertext": base64.b64encode(encrypted.ciphertext).decode("ascii"),
                "nonce": base64.b64encode(encrypted.nonce).decode("ascii"),
                "key_id": encrypted.key_id,
            },
            missing_fields=[],
            prompt=f"Save {fact.label} ({masked}) in your encrypted vault?",
            replace_existing=False,
        )

    def _confirm_private_fact_create(
        self,
        pending: AgentPendingAction,
    ) -> AssistantReply:
        values = pending.proposed_arguments
        try:
            record_uuid = str(uuid.UUID(str(values["record_uuid"])))
            fact_type = str(values["fact_type"])
            if fact_type not in {
                "aadhaar_last4",
                "phone",
                "bank_account",
                "ifsc",
                "academic_score",
                "other_permitted",
            }:
                raise ValueError
            label = str(values["label"])
            masked = str(values["masked_value"])
            key_id = str(values["key_id"])
            ciphertext = base64.b64decode(str(values["ciphertext"]), validate=True)
            nonce = base64.b64decode(str(values["nonce"]), validate=True)
            if not (label and len(label) <= 160 and masked and len(masked) <= 64):
                raise ValueError
        except (KeyError, TypeError, ValueError):
            return AssistantReply(
                "The stored vault proposal is no longer valid.", "failed"
            )

        with self.session_factory() as session:
            current = (
                session.query(AgentPendingAction)
                .filter(
                    AgentPendingAction.id == pending.id,
                    AgentPendingAction.owner_id == pending.owner_id,
                    AgentPendingAction.state == "confirmation",
                )
                .with_for_update()
                .one_or_none()
            )
            if current is None:
                return AssistantReply("That vault save is already closed.", "completed")
            row = PrivateFact(
                owner_id=current.owner_id,
                record_uuid=record_uuid,
                fact_type=fact_type,
                label=label,
                masked_value=masked,
                ciphertext=ciphertext,
                nonce=nonce,
                key_id=key_id,
            )
            session.add(row)
            session.flush()
            session.add(
                PrivateFactAudit(
                    owner_id=current.owner_id,
                    record_uuid=record_uuid,
                    action="create",
                    channel="telegram",
                )
            )
            current.state = "executed"
            current.resolved_at_utc = self.clock()
            self._update_action(
                session,
                current.owner_id,
                current.idempotency_key,
                status="executed",
            )
            run = session.get(AgentRun, current.run_id)
            if run:
                run.status = "completed"
                run.completed_at_utc = self.clock()
            session.commit()
            record_id = row.id
        return AssistantReply(
            f"Saved {escape(label)} ({escape(masked)}) to your encrypted vault.",
            "completed",
            "private_fact",
            record_id,
        )

    def _prepare_private_fact_reveal(
        self,
        owner_id: int,
        run_id: int,
        idempotency_key: str,
        update_id: int,
        action: RetrievePrivateFactAction,
        *,
        replace_existing: bool,
    ) -> AssistantReply:
        needle = " ".join(action.label.split())[:160]
        with self.session_factory() as session:
            rows = (
                session.query(PrivateFact)
                .filter(
                    PrivateFact.owner_id == owner_id,
                )
                .order_by(PrivateFact.updated_at.desc())
                .limit(100)
                .all()
            )
            ranked = sorted(
                (
                    (self._vault_label_score(needle, row.label, row.fact_type), row)
                    for row in rows
                ),
                key=lambda item: item[0],
                reverse=True,
            )
            accepted = [item for item in ranked if item[0] >= 0.55]
            if accepted:
                best_score = accepted[0][0]
                accepted = [item for item in accepted if best_score - item[0] <= 0.08]
            matches = [(row.id, row.label, row.masked_value) for _, row in accepted[:5]]
        if not matches:
            return self._reject(
                owner_id,
                run_id,
                idempotency_key,
                action.kind,
                f'I could not find a vault item matching "{needle}". '
                "Check its label in the Mini App.",
            )
        if len(matches) > 1:
            labels = ", ".join(label for _, label, _ in matches)
            return self._reject(
                owner_id,
                run_id,
                idempotency_key,
                action.kind,
                f"I found several vault items: {labels}. Ask again using the "
                "exact label.",
            )
        record_id, label, masked = matches[0]
        return self._pending(
            owner_id,
            run_id,
            idempotency_key,
            update_id,
            state="confirmation",
            action_type=action.kind,
            arguments={
                "kind": "reveal_private_fact",
                "record_id": record_id,
                "label": label,
            },
            missing_fields=[],
            prompt=(
                f"Reveal {label} ({masked}) in this chat? The message will be "
                "auto-deleted."
            ),
            replace_existing=replace_existing,
        )

    @staticmethod
    def _normalized_reference(value: str) -> str:
        normalized = value.casefold().replace("a/c", " account ")
        tokens = re.findall(r"[a-z0-9]+", normalized)
        aliases = {
            "mobile": "phone",
            "cell": "phone",
            "telephone": "phone",
            "contact": "phone",
            "no": "number",
            "num": "number",
            "nbr": "number",
            "acct": "account",
            "sem": "semester",
            "sixth": "6",
            "6th": "6",
        }
        ignored = {"my", "the", "please", "show", "tell", "what", "is"}
        return " ".join(
            aliases.get(token, token) for token in tokens if token not in ignored
        )

    @classmethod
    def _vault_label_score(cls, needle: str, label: str, fact_type: str) -> float:
        wanted = cls._normalized_reference(needle)
        candidate = cls._normalized_reference(label)
        if not wanted or not candidate:
            return 0.0
        if wanted == candidate:
            return 1.0
        if wanted in candidate or candidate in wanted:
            return 0.92
        wanted_tokens = set(wanted.split())
        candidate_tokens = set(candidate.split())
        overlap = len(wanted_tokens & candidate_tokens) / max(
            len(wanted_tokens | candidate_tokens), 1
        )
        sequence = SequenceMatcher(None, wanted, candidate).ratio()
        type_aliases = {
            "phone": {"phone", "number"},
            "bank_account": {"bank", "account"},
            "ifsc": {"ifsc"},
            "academic_score": {"cgpa", "gpa", "score"},
            "aadhaar_last4": {"aadhaar", "aadhar"},
        }
        type_bonus = 0.2 if wanted_tokens & type_aliases.get(fact_type, set()) else 0
        return min(1.0, max(overlap, sequence * 0.75) + type_bonus)

    def _confirm_private_fact_reveal(
        self,
        pending: AgentPendingAction,
    ) -> AssistantReply:
        record_id = pending.proposed_arguments.get("record_id")
        if not isinstance(record_id, int) or record_id <= 0:
            return AssistantReply(
                "The stored vault request is no longer valid.", "failed"
            )
        try:
            cipher = VaultCipher(settings.vault_encryption_keys)
        except VaultConfigurationError:
            return AssistantReply("The vault is not available right now.", "failed")
        with self.session_factory() as session:
            current = (
                session.query(AgentPendingAction)
                .filter(
                    AgentPendingAction.id == pending.id,
                    AgentPendingAction.owner_id == pending.owner_id,
                    AgentPendingAction.state == "confirmation",
                )
                .with_for_update()
                .one_or_none()
            )
            if current is None:
                return AssistantReply(
                    "That vault request is already closed.", "completed"
                )
            row = (
                session.query(PrivateFact)
                .filter(
                    PrivateFact.id == record_id,
                    PrivateFact.owner_id == current.owner_id,
                )
                .one_or_none()
            )
            if row is None:
                return AssistantReply(
                    "That vault item is no longer available.", "failed"
                )
            try:
                payload = cipher.decrypt(
                    ciphertext=row.ciphertext,
                    nonce=row.nonce,
                    key_id=row.key_id,
                    owner_id=current.owner_id,
                    record_uuid=row.record_uuid,
                    fact_type=row.fact_type,
                )
            except VaultDecryptionError:
                return AssistantReply(
                    "I could not safely open that vault item.", "failed"
                )
            session.add(
                PrivateFactAudit(
                    owner_id=current.owner_id,
                    record_uuid=row.record_uuid,
                    action="reveal",
                    channel="telegram",
                )
            )
            current.state = "executed"
            current.resolved_at_utc = self.clock()
            self._update_action(
                session,
                current.owner_id,
                current.idempotency_key,
                status="executed",
            )
            run = session.get(AgentRun, current.run_id)
            if run:
                run.status = "completed"
                run.completed_at_utc = self.clock()
            label = row.label
            value = str(payload.get("value", ""))
            notes = payload.get("notes")
            session.commit()
        text = f"{escape(label)}: <code>{escape(value)}</code>"
        if notes:
            text += f"\n{escape(str(notes))}"
        text += "\n\nFor privacy, this message will be auto-deleted."
        return AssistantReply(text, "completed", "private_fact", record_id)

    MAX_DELETE_CHOICES = 5

    @staticmethod
    def _reference_of(action) -> tuple[str, int | None, str | None, str | None] | None:
        """Extract (record_type, id, search, ordinal) from any record action."""
        if isinstance(action, DeleteRecordAction):
            return action.record_type, action.record_id, action.search, action.ordinal
        if isinstance(action, RecordGoalProgressAction):
            selector = action.selector
            return "goal", selector.record_id, selector.search, selector.ordinal
        if isinstance(action, SELECTOR_ACTIONS):
            selector = action.selector
            return (
                action.record_type,
                selector.record_id,
                selector.search,
                selector.ordinal,
            )
        return None

    @staticmethod
    def _with_resolved_id(action, record_id: int):
        if isinstance(action, DeleteRecordAction):
            return action.model_copy(update={"record_id": record_id})
        return action.model_copy(
            update={
                "selector": action.selector.model_copy(update={"record_id": record_id})
            }
        )

    def _resolve_deletions(
        self,
        owner_id: int,
        run_id: int,
        idempotency_key: str,
        update_id: int,
        actions: list,
        *,
        replace_existing: bool,
    ) -> tuple[list, AssistantReply | None]:
        """Replace spoken record references with concrete owned record ids."""
        resolved = []
        for action in actions:
            reference = self._reference_of(action)
            if reference is None:
                resolved.append(action)
                continue
            record_type, record_id, search, ordinal = reference
            if record_id:
                resolved.append(action)
                continue
            with self.session_factory() as session:
                candidates = self._reference_candidates(
                    DomainServices(session),
                    owner_id,
                    record_type=record_type,
                    search=search,
                    ordinal=ordinal,
                )
            noun = record_type.replace("_", " ")
            if not candidates:
                return actions, self._reject(
                    owner_id,
                    run_id,
                    idempotency_key,
                    action.kind,
                    f"I could not find a {noun} matching that. "
                    f"Ask me to list your {noun} records and try again.",
                )
            if len(candidates) == 1 or ordinal is not None:
                record_id, _ = candidates[0]
                resolved.append(self._with_resolved_id(action, record_id))
                continue
            choices = candidates[: self.MAX_DELETE_CHOICES]
            verb = self._reference_verb(action)
            if len(actions) > 1:
                # Disambiguating one item inside a multi-intent request would
                # leave the rest of the batch in limbo, so ask instead.
                return actions, self._pending(
                    owner_id,
                    run_id,
                    idempotency_key,
                    update_id,
                    state="clarification",
                    action_type=action.kind,
                    arguments={},
                    missing_fields=["record_reference"],
                    prompt=(
                        f"Several {noun} records match that. Please send that "
                        f"one request on its own so I can show you the choices."
                    ),
                    replace_existing=replace_existing,
                )
            return actions, self._pending(
                owner_id,
                run_id,
                idempotency_key,
                update_id,
                state="disambiguation",
                action_type=action.kind,
                arguments={
                    "kind": "record_choice",
                    "record_type": record_type,
                    # The chosen id is merged back into this stored action, so
                    # the choice resumes the original intent rather than
                    # assuming the user was deleting something.
                    "pending_action": action.model_dump(mode="json"),
                    "candidates": [
                        {"record_id": record_id, "label": label}
                        for record_id, label in choices
                    ],
                },
                missing_fields=["record_reference"],
                prompt=f"Which {noun} should I {verb}?",
                replace_existing=replace_existing,
                options=tuple(choices),
            )
        return resolved, None

    @staticmethod
    def _reference_verb(action) -> str:
        if isinstance(action, DeleteRecordAction):
            return "delete"
        if isinstance(action, SetRecordStatusAction):
            return "update"
        if isinstance(action, RecordGoalProgressAction):
            return "record progress against"
        return "change"

    def _reference_candidates(
        self,
        service: DomainServices,
        owner_id: int,
        *,
        record_type: str,
        search: str | None,
        ordinal: str | None,
    ) -> list[tuple[int, str]]:
        """Return owner-scoped candidates for a spoken reference, newest first."""
        needle = (search or "").strip().lower()
        scan_limit = 100

        if record_type == "work_log":
            rows = service.list_work_logs(owner_id, search=search, limit=scan_limit)
            labels = [(row.id, row.original_text) for row in rows]
        elif record_type == "note":
            rows = service.list_notes(owner_id, search=search, limit=scan_limit)
            labels = [
                (
                    row.id,
                    (
                        f"{row.title} — {row.body}"
                        if row.title and row.title.strip() != row.body.strip()
                        else row.body
                    ),
                )
                for row in rows
            ]
        elif record_type == "ledger_entry":
            rows = service.list_ledger_entries(
                owner_id, search=search, limit=scan_limit
            )
            labels = [
                (
                    row.id,
                    f"{row.direction} {row.currency} "
                    f"{self._major_amount(row.amount_minor, row.currency)} — "
                    f"{row.description}",
                )
                for row in rows
            ]
        elif record_type == "reminder":
            rows = service.list_reminders(owner_id, limit=scan_limit)
            labels = [(row.id, row.title) for row in rows]
        elif record_type == "goal":
            rows = service.list_goals(owner_id, limit=scan_limit)
            labels = [(row.id, row.title) for row in rows]
        else:
            rows = service.list_nutrition_logs(owner_id, limit=scan_limit)
            labels = [(row.id, row.meal_name or row.original_text) for row in rows]

        # The domain layer filters what it can in SQL; the rest is matched here
        # so every record type accepts the same spoken reference.
        if needle and record_type in {"reminder", "goal", "nutrition_log"}:
            labels = [
                (record_id, label)
                for record_id, label in labels
                if needle in (label or "").lower()
            ]
        if needle and not labels:
            unfiltered = self._reference_candidates(
                service,
                owner_id,
                record_type=record_type,
                search=None,
                ordinal=None,
            )
            normalized_needle = self._normalized_reference(needle)
            wanted = set(normalized_needle.split())
            scored = []
            for record_id, label in unfiltered:
                normalized_label = self._normalized_reference(label)
                candidate = set(normalized_label.split())
                overlap = len(wanted & candidate) / max(len(wanted), 1)
                sequence = SequenceMatcher(
                    None,
                    normalized_needle,
                    normalized_label,
                ).ratio()
                score = max(overlap, sequence * 0.8)
                if score >= 0.5:
                    scored.append((score, record_id, label))
            scored.sort(key=lambda item: item[0], reverse=True)
            labels = [(record_id, label) for _, record_id, label in scored]
        if ordinal == "oldest":
            labels = list(reversed(labels))
        return [
            (record_id, " ".join((label or "").split())) for record_id, label in labels
        ]

    def _delete_prompt(self, owner_id: int, action: DeleteRecordAction) -> str:
        """Describe the target in the user's own words rather than by number."""
        noun = action.record_type.replace("_", " ")
        with self.session_factory() as session:
            service = DomainServices(session)
            getters = {
                "work_log": (service.get_work_log, lambda row: row.original_text),
                "note": (
                    service.get_note,
                    lambda row: (
                        f"{row.title} — {row.body}"
                        if row.title and row.title.strip() != row.body.strip()
                        else row.body
                    ),
                ),
                "reminder": (service.get_reminder, lambda row: row.title),
                "ledger_entry": (
                    service.get_ledger_entry,
                    lambda row: f"{row.direction} {row.currency} "
                    f"{self._major_amount(row.amount_minor, row.currency)} — "
                    f"{row.description}",
                ),
                "nutrition_log": (
                    service.get_nutrition_log,
                    lambda row: row.meal_name or row.original_text,
                ),
                "goal": (service.get_goal, lambda row: row.title),
            }
            getter, describe = getters[action.record_type]
            try:
                label = describe(getter(owner_id, action.record_id))
            except (RecordNotFound, DomainError):
                return f"Confirm deletion of {noun} #{action.record_id}."
        return f"Delete this {noun}? {self._clip(label, 160)}"

    def choose(
        self,
        actor: ActorContext,
        pending_id: int,
        record_id: int,
    ) -> AssistantReply:
        """Accept one of the offered deletion candidates, then ask to confirm."""
        pending = self._load_pending(actor.telegram_id, pending_id)
        if pending is None:
            return AssistantReply("Pending action not found.", "rejected")
        if pending.state != "disambiguation":
            return AssistantReply(
                "That action is not waiting for a choice.",
                "rejected",
            )
        if self._expire_if_needed(pending):
            return AssistantReply("That choice has expired.", "expired")
        stored = pending.proposed_arguments or {}
        candidates = stored.get("candidates") or []
        # The tapped value arrives from the client, so it is only honoured when
        # it matches a candidate this server offered for this pending action.
        chosen = next(
            (
                candidate
                for candidate in candidates
                if int(candidate.get("record_id", 0)) == record_id
            ),
            None,
        )
        if chosen is None:
            return AssistantReply("That choice is no longer available.", "rejected")
        try:
            original = AgentProposal.model_validate(
                {"confidence": 1, "action": stored.get("pending_action")}
            ).proposed_actions[0]
        except ValidationError:
            return AssistantReply("That choice is no longer valid.", "failed")
        resolved = self._with_resolved_id(original, record_id)
        label = self._clip(chosen.get("label"), 160)
        with self.session_factory() as session:
            current = (
                session.query(AgentPendingAction)
                .filter(
                    AgentPendingAction.id == pending_id,
                    AgentPendingAction.owner_id == pending.owner_id,
                    AgentPendingAction.state == "disambiguation",
                )
                .one_or_none()
            )
            if current is None:
                return AssistantReply("That action is already closed.", "completed")
            current.state = "confirmation"
            current.action_type = resolved.kind
            # Stored in the batch shape so confirmation runs the same execution
            # path as every other reviewed action.
            current.proposed_arguments = {
                "kind": "batch",
                "actions": [resolved.model_dump(mode="json")],
            }
            current.missing_fields = []
            current.prompt = (
                f"{self._review_prompt([resolved], owner_id=pending.owner_id)}"
                f"\n\nSelected: {label}"
            )
            current.version += 1
            session.commit()
            prompt = current.prompt
        return AssistantReply(escape(prompt), "confirmation", pending_id=pending_id)

    def _review_prompt(
        self,
        actions,
        *,
        owner_id: int,
        uncertain: bool = False,
    ) -> str:
        def short(value, limit: int = 180) -> str:
            normalized = " ".join(str(value).split())
            return (
                normalized
                if len(normalized) <= limit
                else normalized[: limit - 1] + "…"
            )

        lines = [
            (
                "I am not fully sure I understood this. Here is my best reading — "
                "nothing has been saved yet:"
                if uncertain
                else "I understood the following. No changes have been made yet:"
            )
        ]
        for index, action in enumerate(actions, start=1):
            if isinstance(action, CreateWorkLogAction):
                details = []
                if action.category:
                    details.append(f"category {short(action.category, 64)}")
                if action.tags:
                    details.append(
                        "tags " + ", ".join(short(tag, 32) for tag in action.tags)
                    )
                suffix = f" ({'; '.join(details)})" if details else ""
                summary = f"Work log — {short(action.text)}{suffix}"
            elif isinstance(action, CreateNoteAction):
                title = f"{short(action.title, 80)}: " if action.title else ""
                tags = (
                    " (tags " + ", ".join(short(tag, 32) for tag in action.tags) + ")"
                    if action.tags
                    else ""
                )
                summary = f"Note — {title}{short(action.body)}{tags}"
            elif isinstance(action, CreateLedgerAction):
                summary = (
                    f"{action.direction.title()} — {action.amount} "
                    f"{action.currency} for {short(action.description)}"
                )
            elif isinstance(action, CreateReminderAction):
                summary = (
                    f"Reminder — {short(action.title)} at "
                    f"{action.start_at_local.isoformat()} ({action.timezone})"
                )
            elif isinstance(action, CreateNutritionAction):
                summary = f"Food log — {short(action.text)}"
            elif isinstance(action, CreateGoalAction):
                details = []
                if action.target_value is not None:
                    details.append(
                        f"target {action.target_value}"
                        f"{' ' + short(action.unit, 32) if action.unit else ''}"
                    )
                if action.description:
                    details.append(f"description {short(action.description, 100)}")
                suffix = f" ({'; '.join(details)})" if details else ""
                summary = f"Goal — {short(action.title)}{suffix}"
            elif isinstance(action, QueryAction):
                summary = f"Read {action.query_type} summary"
            elif isinstance(action, ListRecordsAction):
                summary = f"List {action.record_type.replace('_', ' ')} records"
            elif isinstance(action, SmalltalkAction):
                summary = f"Reply — {short(action.answer)}"
            elif isinstance(action, UpdateRecordAction):
                changed = ", ".join(
                    name
                    for name, value in (
                        ("title", action.title),
                        ("text", action.text),
                        ("category", action.category),
                        ("tags", action.tags),
                        ("amount", action.amount),
                        ("currency", action.currency),
                        ("target", action.target_value),
                        ("unit", action.unit),
                        ("time", action.start_at_local),
                    )
                    if value is not None
                )
                summary = f"Update {action.record_type.replace('_', ' ')} — {changed}"
            elif isinstance(action, SetRecordStatusAction):
                summary = (
                    f"Mark {action.record_type.replace('_', ' ')} as "
                    f"{action.status}"
                )
            elif isinstance(action, RecordGoalProgressAction):
                verb = "Set" if action.mode == "set" else "Add"
                summary = f"{verb} goal progress — {action.value}"
            elif isinstance(action, UpdateSettingsAction):
                summary = "Change settings — " + ", ".join(
                    name
                    for name, value in (
                        ("timezone", action.timezone),
                        ("Sunday summary", action.sunday_digest_enabled),
                        ("summary time", action.sunday_digest_time),
                    )
                    if value is not None
                )
            elif isinstance(action, DeleteRecordAction):
                summary = self._delete_prompt(owner_id, action).rstrip(".?")
            else:
                summary = "Unsupported action"
            lines.append(f"{index}. {summary}")
        lines.append("Is this correct?")
        return "\n".join(lines)[:1000]

    def _execute(
        self,
        owner_id: int,
        run_id: int,
        idempotency_key: str,
        action,
        *,
        replace_existing: bool,
    ) -> AssistantReply:
        with self.session_factory() as session:
            record = (
                session.query(AgentAction)
                .filter(
                    AgentAction.owner_id == owner_id,
                    AgentAction.idempotency_key == idempotency_key,
                )
                .one_or_none()
            )
            if record is None:
                record = AgentAction(
                    run_id=run_id,
                    owner_id=owner_id,
                    action_type=action.kind,
                    status="proposed",
                    idempotency_key=idempotency_key,
                    argument_fields=sorted(action.model_dump().keys()),
                )
                session.add(record)
                session.flush()
            elif not replace_existing:
                return AssistantReply("That update was already processed.", "completed")
            service = DomainServices(session)
            try:
                reply = self._execute_tool(
                    service,
                    owner_id,
                    idempotency_key,
                    action,
                )
            except (DomainError, ValueError) as exc:
                record.status = "failed"
                record.safe_error_category = type(exc).__name__
                run = session.get(AgentRun, run_id)
                if run:
                    run.status = "failed"
                    run.safe_error_category = type(exc).__name__
                    run.completed_at_utc = self.clock()
                session.commit()
                return AssistantReply(escape(str(exc)), "failed")
            record.status = "executed"
            record.record_type = reply.record_type
            record.record_id = reply.record_id
            record.completed_at_utc = self.clock()
            run = session.get(AgentRun, run_id)
            if run:
                run.status = "completed"
                run.completed_at_utc = self.clock()
            session.commit()
            return reply

    def _execute_read_only_batch(
        self,
        owner_id: int,
        run_id: int,
        idempotency_key: str,
        actions,
        *,
        replace_existing: bool,
    ) -> AssistantReply:
        """Answer several read-only intentions in one turn without a review."""
        with self.session_factory() as session:
            record = (
                session.query(AgentAction)
                .filter(
                    AgentAction.owner_id == owner_id,
                    AgentAction.idempotency_key == idempotency_key,
                )
                .one_or_none()
            )
            if record is None:
                record = AgentAction(
                    run_id=run_id,
                    owner_id=owner_id,
                    action_type="batch",
                    status="proposed",
                    idempotency_key=idempotency_key,
                    argument_fields=[],
                )
                session.add(record)
                session.flush()
            elif not replace_existing:
                return AssistantReply("That update was already processed.", "completed")
            service = DomainServices(session)
            sections: list[str] = []
            try:
                for index, action in enumerate(actions, start=1):
                    reply = self._execute_tool(
                        service,
                        owner_id,
                        f"{idempotency_key}:{index}",
                        action,
                    )
                    sections.append(reply.text)
            except (DomainError, ValueError) as exc:
                record.status = "failed"
                record.safe_error_category = type(exc).__name__
                run = session.get(AgentRun, run_id)
                if run:
                    run.status = "failed"
                    run.safe_error_category = type(exc).__name__
                    run.completed_at_utc = self.clock()
                session.commit()
                return AssistantReply(escape(str(exc)), "failed")
            record.status = "executed"
            record.completed_at_utc = self.clock()
            run = session.get(AgentRun, run_id)
            if run:
                run.status = "completed"
                run.completed_at_utc = self.clock()
            session.commit()
        return AssistantReply("\n\n".join(sections), "completed")

    def _execute_tool(
        self,
        service: DomainServices,
        owner_id: int,
        idempotency_key: str,
        action,
    ) -> AssistantReply:
        if isinstance(action, CreateWorkLogAction):
            row = service.create_work_log(
                owner_id,
                WorkLogCreate(
                    original_text=action.text,
                    category=action.category,
                    tags=action.tags,
                    capture_source="telegram_text",
                    idempotency_key=idempotency_key,
                ),
            )
            return AssistantReply(
                f"Work log #{row.id} saved.",
                "completed",
                "work_log",
                row.id,
            )
        if isinstance(action, CreateNoteAction):
            row = service.create_note(
                owner_id,
                NoteCreate(
                    title=action.title,
                    body=action.body,
                    tags=action.tags,
                    capture_source="telegram_text",
                    idempotency_key=idempotency_key,
                ),
            )
            return AssistantReply(
                f"Note #{row.id} saved.",
                "completed",
                "note",
                row.id,
            )
        if isinstance(action, CreateLedgerAction):
            row = service.create_ledger_entry(
                owner_id,
                LedgerCreate(
                    direction=action.direction,
                    amount=action.amount,
                    currency=action.currency,
                    description=action.description,
                    category=action.category,
                    capture_source="telegram_text",
                    idempotency_key=idempotency_key,
                ),
            )
            return AssistantReply(
                f"{action.direction.title()} #{row.id} saved as "
                f"{action.amount} {row.currency}.",
                "completed",
                "ledger_entry",
                row.id,
            )
        if isinstance(action, CreateReminderAction):
            row = service.create_reminder(
                owner_id,
                ReminderCreate(
                    title=action.title,
                    schedule_type=action.schedule_type,
                    start_at_local=action.start_at_local,
                    timezone=action.timezone,
                    weekday=action.weekday,
                    idempotency_key=idempotency_key,
                ),
            )
            return AssistantReply(
                f"Reminder #{row.id} scheduled.",
                "completed",
                "reminder",
                row.id,
            )
        if isinstance(action, CreateNutritionAction):
            draft_data = NutritionDraftCreate(
                original_text=action.text,
                meal_name=action.meal_name,
                timezone=action.timezone,
                idempotency_key=idempotency_key,
            )
            if action.calories is not None and action.protein_grams is not None:
                row = service.create_nutrition_draft(owner_id, draft_data)
                assumption = "Calories and protein were entered by the user."
                row = service.apply_manual_nutrition(
                    owner_id,
                    row.id,
                    NutritionManualSave(
                        version=row.version,
                        items=[
                            EstimatedNutritionItem(
                                original_item_text=action.text[:1000],
                                normalized_name=(
                                    action.meal_name or "User-described meal"
                                ),
                                quantity_value=Decimal("1"),
                                quantity_unit="serving",
                                portion_description="User-entered serving",
                                calories=action.calories,
                                protein_grams=action.protein_grams,
                                visible_assumptions=[assumption],
                                confidence=Decimal("1"),
                            )
                        ],
                        visible_assumptions=[assumption],
                    ),
                    confirm=False,
                )
            else:
                row = service.estimate_nutrition_draft(
                    owner_id,
                    draft_data,
                    self.nutrition_provider,
                )
            if row.clarification_question:
                text = (
                    f"Food draft #{row.id} saved. "
                    f"{escape(row.clarification_question)}"
                )
            else:
                item_lines = "\n".join(
                    f"• {escape(item.normalized_name)}: "
                    f"{item.calories} kcal, {item.protein_grams} g protein"
                    for item in row.items
                )
                assumptions = "\n".join(
                    f"• {escape(value)}" for value in row.visible_assumptions
                )
                assumption_text = (
                    f"\n\n<b>Assumptions</b>\n{assumptions}" if assumptions else ""
                )
                text = (
                    f"<b>Food preview #{row.id}</b>\n"
                    f"You said: {escape(action.text)}\n\n"
                    f"{item_lines}\n\n"
                    f"Total: approximately {row.total_calories} kcal and "
                    f"{row.total_protein_grams} g protein."
                    f"{assumption_text}\n\n"
                    "Tap Correct to count this meal, or Wrong to discard it."
                )
            status = (
                "completed"
                if row.status == "confirmed" or row.clarification_question
                else "nutrition_confirmation"
            )
            return AssistantReply(text, status, "nutrition_log", row.id)
        if isinstance(action, CreateGoalAction):
            row = service.create_goal(
                owner_id,
                GoalCreate(
                    title=action.title,
                    description=action.description,
                    target_value=action.target_value,
                    unit=action.unit,
                    idempotency_key=idempotency_key,
                ),
            )
            return AssistantReply(
                f"Goal #{row.id} created.",
                "completed",
                "goal",
                row.id,
            )
        if isinstance(action, QueryAction):
            return AssistantReply(
                self._query(service, owner_id, action),
                "completed",
            )
        if isinstance(action, ListRecordsAction):
            return AssistantReply(
                self._list_records(service, owner_id, action),
                "completed",
            )
        if isinstance(action, SmalltalkAction):
            return AssistantReply(escape(action.answer), "completed")
        if isinstance(action, UpdateRecordAction):
            return self._update_record(service, owner_id, action)
        if isinstance(action, SetRecordStatusAction):
            return self._set_record_status(service, owner_id, action)
        if isinstance(action, RecordGoalProgressAction):
            return self._record_goal_progress(service, owner_id, action)
        if isinstance(action, UpdateSettingsAction):
            return self._update_settings(service, owner_id, action)
        raise DomainError("The proposed action is not an allowed tool.")

    def _update_record(
        self,
        service: DomainServices,
        owner_id: int,
        action: UpdateRecordAction,
    ) -> AssistantReply:
        """Map the shared update fields onto the right versioned domain update."""
        record_id = action.selector.record_id
        if action.record_type == "work_log":
            current = service.get_work_log(owner_id, record_id)
            row = service.update_work_log(
                owner_id,
                record_id,
                WorkLogUpdate(
                    version=current.version,
                    **self._present(
                        original_text=action.text,
                        category=action.category,
                        tags=action.tags,
                    ),
                ),
            )
            summary = self._clip(row.original_text)
        elif action.record_type == "note":
            current = service.get_note(owner_id, record_id)
            row = service.update_note(
                owner_id,
                record_id,
                NoteUpdate(
                    version=current.version,
                    **self._present(
                        title=action.title,
                        body=action.text,
                        tags=action.tags,
                    ),
                ),
            )
            summary = self._clip(row.title or row.body)
        elif action.record_type == "ledger_entry":
            current = service.get_ledger_entry(owner_id, record_id)
            row = service.update_ledger_entry(
                owner_id,
                record_id,
                LedgerUpdate(
                    version=current.version,
                    **self._present(
                        amount=action.amount,
                        currency=action.currency,
                        description=action.text,
                        category=action.category,
                    ),
                ),
            )
            summary = (
                f"{row.direction} {row.currency} "
                f"{self._major_amount(row.amount_minor, row.currency)} — "
                f"{self._clip(row.description, 90)}"
            )
        elif action.record_type == "reminder":
            current = service.get_reminder(owner_id, record_id)
            row = service.update_reminder(
                owner_id,
                record_id,
                ReminderUpdate(
                    version=current.version,
                    **self._present(
                        title=action.title,
                        description=action.text,
                        start_at_local=action.start_at_local,
                        timezone=action.timezone,
                    ),
                ),
            )
            summary = self._clip(row.title)
        elif action.record_type == "goal":
            current = service.get_goal(owner_id, record_id)
            row = service.update_goal(
                owner_id,
                record_id,
                GoalUpdate(
                    version=current.version,
                    **self._present(
                        title=action.title,
                        description=action.text,
                        target_value=action.target_value,
                        unit=action.unit,
                    ),
                ),
            )
            summary = self._clip(row.title)
        else:
            raise DomainError(
                "A food log's estimate is edited item by item in the Mini App."
            )
        return AssistantReply(
            f"Updated: {summary}",
            "completed",
            action.record_type,
            record_id,
        )

    @staticmethod
    def _present(**values) -> dict:
        """Drop unset fields so a versioned update only touches what changed."""
        return {key: value for key, value in values.items() if value is not None}

    def _set_record_status(
        self,
        service: DomainServices,
        owner_id: int,
        action: SetRecordStatusAction,
    ) -> AssistantReply:
        record_id = action.selector.record_id
        status = action.status
        if action.record_type == "goal":
            if status not in {"active", "paused", "completed"}:
                raise DomainError("A goal can be active, paused, or completed.")
            current = service.get_goal(owner_id, record_id)
            row = service.update_goal(
                owner_id,
                record_id,
                GoalUpdate(version=current.version, status=status),
            )
            return AssistantReply(
                f'Goal "{self._clip(row.title, 80)}" is now {status}.',
                "completed",
                "goal",
                record_id,
            )
        if action.record_type == "reminder":
            if status not in {"enabled", "active", "disabled", "paused"}:
                raise DomainError("A reminder can be paused or resumed.")
            enabled = status in {"enabled", "active"}
            current = service.get_reminder(owner_id, record_id)
            row = service.update_reminder(
                owner_id,
                record_id,
                ReminderUpdate(version=current.version, enabled=enabled),
            )
            return AssistantReply(
                f'Reminder "{self._clip(row.title, 80)}" is now '
                f"{'active' if enabled else 'paused'}.",
                "completed",
                "reminder",
                record_id,
            )
        if action.record_type == "note":
            if status not in {"pinned", "unpinned"}:
                raise DomainError("A note can be pinned or unpinned.")
            current = service.get_note(owner_id, record_id)
            row = service.update_note(
                owner_id,
                record_id,
                NoteUpdate(version=current.version, pinned=status == "pinned"),
            )
            return AssistantReply(
                f'Note "{self._clip(row.title or row.body, 80)}" is now {status}.',
                "completed",
                "note",
                record_id,
            )
        if status != "confirmed":
            raise DomainError("A food draft can only be confirmed.")
        current = service.get_nutrition_log(owner_id, record_id)
        row = service.confirm_nutrition_log(owner_id, record_id, current.version)
        return AssistantReply(
            f"Confirmed {self._clip(row.meal_name or row.original_text, 80)}: "
            f"approximately {row.total_calories} kcal, "
            f"{row.total_protein_grams} g protein.",
            "completed",
            "nutrition_log",
            record_id,
        )

    def _record_goal_progress(
        self,
        service: DomainServices,
        owner_id: int,
        action: RecordGoalProgressAction,
    ) -> AssistantReply:
        record_id = action.selector.record_id
        current = service.get_goal(owner_id, record_id)
        updated_value = (
            action.value
            if action.mode == "set"
            else Decimal(current.current_value) + action.value
        )
        row = service.update_goal(
            owner_id,
            record_id,
            GoalUpdate(version=current.version, current_value=updated_value),
        )
        target = (
            f" of {row.target_value} {row.unit or ''}".rstrip()
            if row.target_value is not None
            else ""
        )
        return AssistantReply(
            f'"{self._clip(row.title, 80)}" is now at ' f"{row.current_value}{target}.",
            "completed",
            "goal",
            record_id,
        )

    def _update_settings(
        self,
        service: DomainServices,
        owner_id: int,
        action: UpdateSettingsAction,
    ) -> AssistantReply:
        current = service.get_schedule_preferences(owner_id)
        digest_time = current["sunday_digest_time"]
        if isinstance(digest_time, str):
            digest_time = time.fromisoformat(digest_time)
        if action.sunday_digest_time is not None:
            digest_time = time.fromisoformat(f"{action.sunday_digest_time}:00")
        updated = service.update_schedule_preferences(
            owner_id,
            SchedulePreferenceUpdate(
                preference_version=current["preference_version"],
                digest_version=current["digest_version"],
                timezone=action.timezone or current["timezone"],
                sunday_digest_enabled=(
                    current["sunday_digest_enabled"]
                    if action.sunday_digest_enabled is None
                    else action.sunday_digest_enabled
                ),
                sunday_digest_time=digest_time,
            ),
        )
        return AssistantReply(
            f"Settings updated. Timezone {escape(updated['timezone'])}, "
            f"Sunday summary "
            f"{'on' if updated['sunday_digest_enabled'] else 'off'} at "
            f"{updated['sunday_digest_time']}.",
            "completed",
        )

    def _list_records(
        self,
        service: DomainServices,
        owner_id: int,
        action: ListRecordsAction,
    ) -> str:
        QuotaService(service.session).require(
            owner_id,
            "summaries",
            limit=self.daily_summary_limit,
        )
        renderer = {
            "work_log": self._list_work_logs,
            "note": self._list_notes,
            "reminder": self._list_reminders,
            "ledger_entry": self._list_ledger_entries,
            "nutrition_log": self._list_nutrition_logs,
            "goal": self._list_goals,
        }[action.record_type]
        heading, lines = renderer(service, owner_id, action)
        if not lines:
            return f"No {heading} matched that."
        return "\n".join([f"{heading.capitalize()}:", *lines])

    @staticmethod
    def _clip(value: object, limit: int = 140) -> str:
        normalized = " ".join(str(value or "").split())
        if len(normalized) > limit:
            normalized = normalized[: limit - 1] + "…"
        return escape(normalized)

    def _list_work_logs(self, service, owner_id, action):
        rows = service.list_work_logs(
            owner_id,
            start_date=action.start_date,
            end_date=action.end_date,
            tag=action.tag,
            search=action.search,
            limit=action.limit,
        )
        return "work logs", [
            f"• #{row.id} · {row.user_local_date} — {self._clip(row.original_text)}"
            for row in rows
        ]

    def _list_notes(self, service, owner_id, action):
        rows = service.list_notes(
            owner_id,
            search=action.search,
            tag=action.tag,
            pinned=True if action.status == "pinned" else None,
            limit=action.limit,
        )
        return "notes", [
            f"• #{row.id} {'📌 ' if row.pinned else ''}"
            f"{self._clip(row.title, 60)} — {self._clip(row.body, 110)}"
            for row in rows
        ]

    def _list_reminders(self, service, owner_id, action):
        enabled = {"enabled": True, "active": True, "paused": False, "disabled": False}
        rows = service.list_reminders(
            owner_id,
            enabled=enabled.get(action.status or ""),
            limit=action.limit,
        )
        lines = []
        for row in rows:
            when = (
                row.next_run_at_utc.astimezone(ZoneInfo(row.timezone)).strftime(
                    "%Y-%m-%d %H:%M"
                )
                if row.next_run_at_utc is not None
                else "not scheduled"
            )
            state = "" if row.enabled else " (paused)"
            lines.append(
                f"• #{row.id} {self._clip(row.title, 70)} — "
                f"{row.schedule_type}, next {when} {row.timezone}{state}"
            )
        return "reminders", lines

    def _list_ledger_entries(self, service, owner_id, action):
        rows = service.list_ledger_entries(
            owner_id,
            start_date=action.start_date,
            end_date=action.end_date,
            search=action.search,
            limit=action.limit,
        )
        return "ledger entries", [
            f"• #{row.id} · {row.user_local_date} — {row.direction} "
            f"{row.currency} {self._major_amount(row.amount_minor, row.currency)}"
            f" — {self._clip(row.description, 90)}"
            for row in rows
        ]

    def _list_nutrition_logs(self, service, owner_id, action):
        status = action.status if action.status in {"draft", "confirmed"} else None
        rows = service.list_nutrition_logs(
            owner_id,
            start_date=action.start_date,
            end_date=action.end_date,
            status=status,
            limit=action.limit,
        )
        return "food logs", [
            f"• #{row.id} · {row.user_local_date} [{row.status}] "
            f"{self._clip(row.meal_name or row.original_text, 90)} — "
            f"approximately {row.total_calories} kcal, "
            f"{row.total_protein_grams} g protein"
            for row in rows
        ]

    def _list_goals(self, service, owner_id, action):
        status = (
            action.status
            if action.status in {"active", "paused", "completed"}
            else None
        )
        rows = service.list_goals(owner_id, status=status, limit=action.limit)
        lines = []
        for row in rows:
            progress = (
                f" — {self._display_decimal(row.current_value)}/"
                f"{self._display_decimal(row.target_value)} {row.unit or ''}".rstrip()
                if row.target_value is not None
                else ""
            )
            lines.append(
                f"• #{row.id} {self._clip(row.title, 80)} " f"[{row.status}]{progress}"
            )
        return "goals", lines

    def _query(
        self,
        service: DomainServices,
        owner_id: int,
        action: QueryAction,
    ) -> str:
        QuotaService(service.session).require(
            owner_id,
            "summaries",
            limit=self.daily_summary_limit,
        )
        today = self.clock().astimezone(ZoneInfo(action.timezone)).date()
        if action.query_type == "today":
            rows = service.list_work_logs(
                owner_id,
                start_date=today,
                end_date=today,
                limit=20,
            )
            return (
                "No work logged today."
                if not rows
                else "Today: "
                + "; ".join(escape(row.original_text[:120]) for row in rows)
            )
        if action.query_type == "week":
            start = today - timedelta(days=today.weekday())
            rows = service.list_work_logs(
                owner_id,
                start_date=start,
                end_date=today,
                limit=50,
            )
            return (
                "No work logged this week."
                if not rows
                else "This week: "
                + "; ".join(escape(row.original_text[:120]) for row in rows)
            )
        if action.query_type == "spending":
            start = action.start_date or today.replace(day=1)
            end = action.end_date or today
            if end < start:
                return "The requested spending period is invalid."
            analysis = service.analyze_expenses(
                owner_id,
                start_date=start,
                end_date=end,
                search=action.search,
            )
            period = (
                "this month"
                if start == today.replace(day=1) and end == today
                else f"{start.isoformat()} to {end.isoformat()}"
            )
            if not analysis["entries"]:
                matching = (
                    f" matching “{escape(action.search)}”" if action.search else ""
                )
                return f"No expenses recorded for {period}{matching}."
            if action.ranking:
                label = "Most" if action.ranking == "highest" else "Least"
                lines = []
                currencies = sorted({row["currency"] for row in analysis["categories"]})
                for currency in currencies:
                    candidates = [
                        row
                        for row in analysis["categories"]
                        if row["currency"] == currency
                    ]
                    selected = (
                        max(candidates, key=lambda row: row["amount_minor"])
                        if action.ranking == "highest"
                        else min(candidates, key=lambda row: row["amount_minor"])
                    )
                    lines.append(
                        f"{escape(selected['category'])}: {currency} "
                        f"{self._major_amount(selected['amount_minor'], currency)} "
                        f"across {selected['count']} expense"
                        f"{'s' if selected['count'] != 1 else ''}"
                    )
                return f"{label} spending category for {period}: " + "; ".join(lines)
            if action.search:
                return (
                    f"Spending matching “{escape(action.search)}” for {period}: "
                    + "; ".join(
                        f"{row['currency']} "
                        f"{self._major_amount(row['amount_minor'], row['currency'])} "
                        f"across {row['count']} expense"
                        f"{'s' if row['count'] != 1 else ''}"
                        for row in analysis["totals"]
                    )
                )
            totals = service.summarize_ledger(
                owner_id,
                start_date=start,
                end_date=end,
            )
            return f"Ledger summary for {period}: " + "; ".join(
                f"{row['currency']} expenses "
                f"{self._major_amount(row['expense_minor'], row['currency'])}, "
                f"income {self._major_amount(row['income_minor'], row['currency'])}"
                for row in totals
            )
        if action.query_type == "nutrition":
            summary = service.summarize_nutrition(owner_id, today, today)
            meals = service.list_nutrition_logs(
                owner_id,
                start_date=today,
                end_date=today,
                status="confirmed",
                limit=50,
            )
            if not meals:
                return "No confirmed food logs today."
            lines = ["Today's food:"]
            for meal in reversed(meals):
                label = meal.meal_name or meal.original_text
                lines.append(
                    f"• {escape(label[:160])}: approximately "
                    f"{meal.total_calories} kcal, "
                    f"{meal.total_protein_grams} g protein"
                )
            lines.append(
                f"Total: approximately {summary['total_calories']} kcal, "
                f"{summary['total_protein_grams']} g protein."
            )
            return "\n".join(lines)
        goals = service.list_goals(owner_id, status="active", limit=20)
        return (
            "No active goals."
            if not goals
            else "Active goals: "
            + "; ".join(f"#{row.id} {escape(row.title[:100])}" for row in goals)
        )

    @staticmethod
    def _major_amount(amount_minor: int, currency: str) -> str:
        """Render integer minor units as a fixed-precision major amount."""
        from domain.schemas import (
            THREE_DECIMAL_CURRENCIES,
            ZERO_DECIMAL_CURRENCIES,
        )

        digits = (
            0
            if currency in ZERO_DECIMAL_CURRENCIES
            else 3 if currency in THREE_DECIMAL_CURRENCIES else 2
        )
        major = Decimal(amount_minor) / (Decimal(10) ** digits)
        return f"{major.quantize(Decimal(1).scaleb(-digits)):f}"

    @staticmethod
    def _display_decimal(value: Decimal) -> str:
        rendered = format(value, "f")
        if "." in rendered:
            rendered = rendered.rstrip("0").rstrip(".")
        return rendered or "0"

    @staticmethod
    def _delete_record(
        service: DomainServices,
        owner_id: int,
        action: DeleteRecordAction,
    ) -> None:
        operations = {
            "work_log": service.delete_work_log,
            "note": service.delete_note,
            "reminder": service.delete_reminder,
            "ledger_entry": service.delete_ledger_entry,
            "nutrition_log": service.delete_nutrition_log,
            "goal": service.delete_goal,
        }
        operations[action.record_type](owner_id, action.record_id)

    def _pending(
        self,
        owner_id: int,
        run_id: int,
        idempotency_key: str,
        update_id: int,
        *,
        state: str,
        action_type: str,
        arguments: dict,
        missing_fields: list[str],
        prompt: str,
        replace_existing: bool,
        options: tuple[tuple[int, str], ...] = (),
    ) -> AssistantReply:
        with self.session_factory() as session:
            action = (
                session.query(AgentAction)
                .filter(
                    AgentAction.owner_id == owner_id,
                    AgentAction.idempotency_key == idempotency_key,
                )
                .one_or_none()
            )
            if action is None:
                action = AgentAction(
                    run_id=run_id,
                    owner_id=owner_id,
                    action_type=action_type,
                    status=(
                        "confirmation_required"
                        if state == "confirmation"
                        else "clarification"
                    ),
                    idempotency_key=idempotency_key,
                    argument_fields=sorted(arguments.keys()),
                )
                session.add(action)
            elif replace_existing:
                action.action_type = action_type
                action.status = (
                    "confirmation_required"
                    if state == "confirmation"
                    else "clarification"
                )
                action.argument_fields = sorted(arguments.keys())
            pending = (
                session.query(AgentPendingAction)
                .filter(
                    AgentPendingAction.owner_id == owner_id,
                    AgentPendingAction.idempotency_key == idempotency_key,
                )
                .one_or_none()
            )
            if pending is None:
                pending = AgentPendingAction(
                    owner_id=owner_id,
                    run_id=run_id,
                    action_type=action_type,
                    state=state,
                    proposed_arguments=json.loads(json.dumps(arguments, default=str)),
                    missing_fields=missing_fields,
                    prompt=prompt,
                    original_update_id=update_id,
                    idempotency_key=idempotency_key,
                    expires_at_utc=self.clock()
                    + timedelta(minutes=self.pending_ttl_minutes),
                )
                session.add(pending)
            else:
                pending.action_type = action_type
                pending.state = state
                pending.proposed_arguments = json.loads(
                    json.dumps(arguments, default=str)
                )
                pending.missing_fields = missing_fields
                pending.prompt = prompt
                pending.expires_at_utc = self.clock() + timedelta(
                    minutes=self.pending_ttl_minutes
                )
                pending.version += 1
            run = session.get(AgentRun, run_id)
            if run:
                run.status = state
                run.completed_at_utc = self.clock()
            session.commit()
            pending_id = pending.id
        # Every pending state is resolved by tapping a button or by simply
        # replying, so the prompt no longer quotes a command and an id back at
        # the user. The slash commands still work as a deterministic fallback.
        return AssistantReply(
            escape(prompt),
            state,
            pending_id=pending_id,
            options=options,
        )

    def _reject(
        self,
        owner_id: int,
        run_id: int,
        idempotency_key: str,
        action_type: str,
        reason: str,
    ) -> AssistantReply:
        with self.session_factory() as session:
            action = (
                session.query(AgentAction)
                .filter(
                    AgentAction.owner_id == owner_id,
                    AgentAction.idempotency_key == idempotency_key,
                )
                .one_or_none()
            )
            if action is None:
                action = AgentAction(
                    run_id=run_id,
                    owner_id=owner_id,
                    action_type=action_type,
                    status="rejected",
                    idempotency_key=idempotency_key,
                    argument_fields=[],
                )
                session.add(action)
            else:
                action.action_type = action_type
                action.status = "rejected"
                action.argument_fields = []
            run = session.get(AgentRun, run_id)
            if run:
                run.status = "rejected"
                run.completed_at_utc = self.clock()
            session.commit()
        return AssistantReply(escape(reason), "rejected")

    def _fail_run(self, run_id: int, category: str) -> None:
        with self.session_factory() as session:
            run = session.get(AgentRun, run_id)
            if run:
                run.status = "failed"
                run.safe_error_category = category
                run.completed_at_utc = self.clock()
                session.commit()

    def _existing_reply(
        self,
        telegram_id: int,
        idempotency_key: str,
    ) -> AssistantReply | None:
        with self.session_factory() as session:
            action = (
                session.query(AgentAction)
                .join(AgentRun, AgentRun.id == AgentAction.run_id)
                .join(PublicUser, PublicUser.id == AgentAction.owner_id)
                .filter(
                    AgentRun.owner_id == AgentAction.owner_id,
                    PublicUser.telegram_id == telegram_id,
                    AgentAction.idempotency_key == idempotency_key,
                )
                .one_or_none()
            )
            if action is None:
                return None
            pending = (
                session.query(AgentPendingAction)
                .filter(
                    AgentPendingAction.owner_id == action.owner_id,
                    AgentPendingAction.idempotency_key == idempotency_key,
                    AgentPendingAction.state.in_(OPEN_PENDING_STATES),
                )
                .one_or_none()
            )
            if pending:
                return AssistantReply(
                    escape(pending.prompt),
                    pending.state,
                    pending_id=pending.id,
                    options=self._stored_options(pending),
                )
            return AssistantReply(
                "That Telegram update was already processed.",
                action.status,
                action.record_type,
                action.record_id,
            )

    def _load_pending(
        self,
        telegram_id: int,
        pending_id: int,
    ) -> AgentPendingAction | None:
        with self.session_factory() as session:
            pending = (
                session.query(AgentPendingAction)
                .join(AgentRun, AgentRun.id == AgentPendingAction.run_id)
                .join(PublicUser, PublicUser.id == AgentPendingAction.owner_id)
                .filter(
                    AgentPendingAction.id == pending_id,
                    AgentRun.owner_id == AgentPendingAction.owner_id,
                    PublicUser.telegram_id == telegram_id,
                )
                .one_or_none()
            )
            if pending is None:
                return None
            session.expunge(pending)
            return pending

    def _expire_if_needed(self, pending: AgentPendingAction) -> bool:
        expires = pending.expires_at_utc
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        if expires > self.clock():
            return False
        with self.session_factory() as session:
            current = session.get(AgentPendingAction, pending.id)
            if current and current.state in OPEN_PENDING_STATES:
                current.state = "expired"
                current.resolved_at_utc = self.clock()
                session.commit()
        return True

    @staticmethod
    def _stored_options(pending: AgentPendingAction) -> tuple[tuple[int, str], ...]:
        """Rebuild the offered choices when a pending action is replayed."""
        if pending.state != "disambiguation":
            return ()
        candidates = (pending.proposed_arguments or {}).get("candidates") or []
        return tuple(
            (int(candidate["record_id"]), str(candidate.get("label", "")))
            for candidate in candidates
            if candidate.get("record_id")
        )

    @staticmethod
    def _update_action(
        session: Session,
        owner_id: int,
        idempotency_key: str,
        *,
        status: str,
        record_type: str | None = None,
        record_id: int | None = None,
    ) -> None:
        action = (
            session.query(AgentAction)
            .filter(
                AgentAction.owner_id == owner_id,
                AgentAction.idempotency_key == idempotency_key,
            )
            .one_or_none()
        )
        if action:
            action.status = status
            action.record_type = record_type or action.record_type
            action.record_id = record_id or action.record_id
            action.completed_at_utc = datetime.now(UTC)
