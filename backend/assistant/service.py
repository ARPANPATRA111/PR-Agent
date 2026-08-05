"""Bounded assistant orchestration over tenant-scoped domain operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from html import escape
import json
from typing import Callable
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from sqlalchemy.orm import Session

from abuse_controls import QuotaExceeded, QuotaService
from assistant.providers import IntentProvider
from assistant.schemas import (
    AgentProposal,
    ClarificationAction,
    CreateGoalAction,
    CreateLedgerAction,
    CreateNoteAction,
    CreateNutritionAction,
    CreateReminderAction,
    CreateWorkLogAction,
    DeleteRecordAction,
    QueryAction,
    UnsupportedAction,
)
from domain.errors import DomainError, RecordNotFound
from domain.schemas import (
    GoalCreate,
    LedgerCreate,
    NoteCreate,
    NutritionDraftCreate,
    ReminderCreate,
    WorkLogCreate,
)
from domain.services import DomainServices
from nutrition.providers import NutritionEstimationProvider
from public_models import (
    AgentAction,
    AgentPendingAction,
    AgentRun,
    PublicUser,
)

UTC = timezone.utc


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
        daily_ai_limit: int = 50,
        daily_summary_limit: int = 30,
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
        idempotency_key = f"agent:{actor.telegram_id}:{update_id}"
        existing = self._existing_reply(actor.telegram_id, idempotency_key)
        if existing is not None:
            return existing
        try:
            owner_id, run_id, default_timezone = self._start_run(actor, text, update_id)
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
        except ValidationError:
            self._fail_run(run_id, "invalid_provider_schema")
            return AssistantReply(
                "I could not safely validate that request. "
                "Use a slash command instead.",
                "failed",
            )
        except Exception:
            self._fail_run(run_id, "provider_failure")
            return AssistantReply(
                "The assistant is temporarily unavailable. Slash commands still work.",
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
        context = {
            "intended_kind": pending.action_type,
            "known_arguments": pending.proposed_arguments,
            "missing_fields": pending.missing_fields,
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
                "I could not safely validate that answer.",
                "failed",
                pending_id=pending_id,
            )
        except Exception:
            return AssistantReply(
                "The assistant is temporarily unavailable. Try again later.",
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
            if isinstance(proposal.action, ClarificationAction):
                current.action_type = proposal.action.intended_kind
                current.proposed_arguments = proposal.action.known_arguments
                current.missing_fields = proposal.action.missing_fields
                current.prompt = proposal.action.question
                current.version += 1
                session.commit()
                return AssistantReply(
                    proposal.action.question,
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
        return AssistantReply(
            "Confirmed and saved:\n"
            + "\n".join(
                f"{index}. {result}" for index, result in enumerate(results, start=1)
            ),
            "completed",
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
                    AgentPendingAction.state.in_(["clarification", "confirmation"]),
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
    ) -> tuple[int, int, str]:
        with self.session_factory() as session:
            service = DomainServices(session)
            owner = service.ensure_owner(
                telegram_id=actor.telegram_id,
                first_name=actor.first_name,
                last_name=actor.last_name,
                username=actor.username,
            )
            QuotaService(session).require(
                owner.id,
                "ai_classifications",
                limit=self.daily_ai_limit,
            )
            default_timezone = service.get_schedule_preferences(owner.id)["timezone"]
            run = AgentRun(
                owner_id=owner.id,
                provider=self.provider.provider_name,
                model=self.provider.model_name[:128],
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
            return self._reject(
                owner_id,
                run_id,
                idempotency_key,
                unsupported.kind,
                unsupported.reason,
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
        if proposal.confidence < self.min_confidence:
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
        if review_required or len(actions) > 1:
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
                prompt=self._review_prompt(actions),
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
                prompt=(
                    f"Confirm deletion of {action.record_type.replace('_', ' ')} "
                    f"#{action.record_id}."
                ),
                replace_existing=replace_existing,
            )
        return self._execute(
            owner_id,
            run_id,
            idempotency_key,
            action,
            replace_existing=replace_existing,
        )

    @staticmethod
    def _review_prompt(actions) -> str:
        def short(value, limit: int = 180) -> str:
            normalized = " ".join(str(value).split())
            return (
                normalized
                if len(normalized) <= limit
                else normalized[: limit - 1] + "…"
            )

        lines = ["I understood the following. No changes have been made yet:"]
        for index, action in enumerate(actions, start=1):
            if isinstance(action, CreateWorkLogAction):
                summary = f"Work log — {short(action.text)}"
            elif isinstance(action, CreateNoteAction):
                summary = f"Note — {short(action.body)}"
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
                summary = f"Goal — {short(action.title)}"
            elif isinstance(action, QueryAction):
                summary = f"Read {action.query_type} summary"
            elif isinstance(action, DeleteRecordAction):
                summary = (
                    f"Delete {action.record_type.replace('_', ' ')} "
                    f"#{action.record_id}"
                )
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
            row = service.estimate_nutrition_draft(
                owner_id,
                NutritionDraftCreate(
                    original_text=action.text,
                    meal_name=action.meal_name,
                    timezone=action.timezone,
                    idempotency_key=idempotency_key,
                ),
                self.nutrition_provider,
            )
            if row.clarification_question:
                text = (
                    f"Food draft #{row.id} saved. "
                    f"{escape(row.clarification_question)}"
                )
            else:
                text = (
                    f"Food draft #{row.id}: approximately "
                    f"{row.total_calories} kcal and "
                    f"{row.total_protein_grams} g protein. "
                    f"Confirm with /confirmfood {row.id}."
                )
            return AssistantReply(text, "completed", "nutrition_log", row.id)
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
        raise DomainError("The proposed action is not an allowed tool.")

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
            start = today.replace(day=1)
            totals = service.summarize_ledger(
                owner_id,
                start_date=start,
                end_date=today,
            )
            if not totals:
                return "No ledger entries this month."
            return "This month: " + "; ".join(
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
        zero_decimal = {
            "BIF", "CLP", "DJF", "GNF", "ISK", "JPY", "KMF", "KRW",
            "PYG", "RWF", "UGX", "UYI", "VND", "VUV", "XAF", "XOF",
            "XPF",
        }
        three_decimal = {
            "BHD", "IQD", "JOD", "KWD", "LYD", "OMR", "TND",
        }
        digits = 0 if currency in zero_decimal else 3 if currency in three_decimal else 2
        return f"{Decimal(amount_minor) / (Decimal(10) ** digits):f}"

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
        instruction = (
            f" Reply with /confirmagent {pending_id} or " f"/cancelagent {pending_id}."
            if state == "confirmation"
            else f" Reply with /answeragent {pending_id} your answer."
        )
        return AssistantReply(
            escape(prompt) + instruction,
            state,
            pending_id=pending_id,
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
                    AgentPendingAction.state.in_(["clarification", "confirmation"]),
                )
                .one_or_none()
            )
            if pending:
                return AssistantReply(
                    escape(pending.prompt),
                    pending.state,
                    pending_id=pending.id,
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
            if current and current.state in {"clarification", "confirmation"}:
                current.state = "expired"
                current.resolved_at_utc = self.clock()
                session.commit()
        return True

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
