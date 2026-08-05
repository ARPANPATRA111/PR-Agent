"""Bounded assistant orchestration over tenant-scoped domain operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
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
    READ_ONLY_ACTIONS,
    AgentProposal,
    ClarificationAction,
    CreateGoalAction,
    CreateLedgerAction,
    CreateNoteAction,
    CreateNutritionAction,
    CreateReminderAction,
    CreateWorkLogAction,
    DeleteRecordAction,
    ListRecordsAction,
    QueryAction,
    SmalltalkAction,
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

# Pending states that are still awaiting the user. Anything else is resolved.
OPEN_PENDING_STATES = ("clarification", "confirmation", "disambiguation")


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

    def open_clarification_id(self, telegram_id: int) -> int | None:
        """Return the caller's newest unanswered question, if one is waiting.

        This lets a spoken or typed reply continue the conversation naturally
        instead of requiring the user to quote a command and a pending id.
        """
        with self.session_factory() as session:
            pending = (
                session.query(AgentPendingAction)
                .join(PublicUser, PublicUser.id == AgentPendingAction.owner_id)
                .filter(
                    PublicUser.telegram_id == telegram_id,
                    AgentPendingAction.state == "clarification",
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
                prompt=self._review_prompt(actions, uncertain=uncertain),
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

    MAX_DELETE_CHOICES = 5

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
            if not isinstance(action, DeleteRecordAction) or action.record_id:
                resolved.append(action)
                continue
            with self.session_factory() as session:
                candidates = self._delete_candidates(
                    DomainServices(session),
                    owner_id,
                    action,
                )
            noun = action.record_type.replace("_", " ")
            if not candidates:
                return actions, self._reject(
                    owner_id,
                    run_id,
                    idempotency_key,
                    action.kind,
                    f"I could not find a {noun} matching that. "
                    f"Ask me to list your {noun} records and try again.",
                )
            if len(candidates) == 1 or action.ordinal is not None:
                record_id, _ = candidates[0]
                resolved.append(action.model_copy(update={"record_id": record_id}))
                continue
            choices = candidates[: self.MAX_DELETE_CHOICES]
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
                        f"Several {noun} records match that. Please send the "
                        f"deletion on its own so I can show you the choices."
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
                    "kind": "delete_choice",
                    "record_type": action.record_type,
                    "candidates": [
                        {"record_id": record_id, "label": label}
                        for record_id, label in choices
                    ],
                },
                missing_fields=["record_reference"],
                prompt=f"Which {noun} should I delete?",
                replace_existing=replace_existing,
                options=tuple(choices),
            )
        return resolved, None

    def _delete_candidates(
        self,
        service: DomainServices,
        owner_id: int,
        action: DeleteRecordAction,
    ) -> list[tuple[int, str]]:
        """Return owner-scoped deletion candidates, newest match first."""
        search = (action.search or "").strip().lower()
        scan_limit = 100

        if action.record_type == "work_log":
            rows = service.list_work_logs(
                owner_id, search=action.search, limit=scan_limit
            )
            labels = [(row.id, row.original_text) for row in rows]
        elif action.record_type == "note":
            rows = service.list_notes(owner_id, search=action.search, limit=scan_limit)
            labels = [(row.id, row.title or row.body) for row in rows]
        elif action.record_type == "ledger_entry":
            rows = service.list_ledger_entries(
                owner_id, search=action.search, limit=scan_limit
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
        elif action.record_type == "reminder":
            rows = service.list_reminders(owner_id, limit=scan_limit)
            labels = [(row.id, row.title) for row in rows]
        elif action.record_type == "goal":
            rows = service.list_goals(owner_id, limit=scan_limit)
            labels = [(row.id, row.title) for row in rows]
        else:
            rows = service.list_nutrition_logs(owner_id, limit=scan_limit)
            labels = [(row.id, row.meal_name or row.original_text) for row in rows]

        # The domain layer filters what it can in SQL; the rest is matched here
        # so every record type accepts the same spoken reference.
        if search and action.record_type in {"reminder", "goal", "nutrition_log"}:
            labels = [
                (record_id, label)
                for record_id, label in labels
                if search in (label or "").lower()
            ]
        if action.ordinal == "oldest":
            labels = list(reversed(labels))
        return [(record_id, " ".join((label or "").split())) for record_id, label in labels]

    def _delete_prompt(self, owner_id: int, action: DeleteRecordAction) -> str:
        """Describe the target in the user's own words rather than by number."""
        noun = action.record_type.replace("_", " ")
        with self.session_factory() as session:
            service = DomainServices(session)
            getters = {
                "work_log": (service.get_work_log, lambda row: row.original_text),
                "note": (service.get_note, lambda row: row.title or row.body),
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
        record_type = stored.get("record_type")
        noun = str(record_type).replace("_", " ")
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
            current.action_type = "delete_record"
            current.proposed_arguments = {
                "kind": "delete_record",
                "record_type": record_type,
                "record_id": record_id,
                "search": None,
                "ordinal": None,
            }
            current.missing_fields = []
            current.prompt = (
                f"Delete this {noun}? {self._clip(chosen.get('label'), 160)}"
            )
            current.version += 1
            session.commit()
            prompt = current.prompt
        return AssistantReply(prompt, "confirmation", pending_id=pending_id)

    @staticmethod
    def _review_prompt(actions, *, uncertain: bool = False) -> str:
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
            elif isinstance(action, ListRecordsAction):
                summary = f"List {action.record_type.replace('_', ' ')} records"
            elif isinstance(action, SmalltalkAction):
                summary = f"Reply — {short(action.answer)}"
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
        if isinstance(action, ListRecordsAction):
            return AssistantReply(
                self._list_records(service, owner_id, action),
                "completed",
            )
        if isinstance(action, SmalltalkAction):
            return AssistantReply(escape(action.answer), "completed")
        raise DomainError("The proposed action is not an allowed tool.")

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
                f" — {row.current_value}/{row.target_value} {row.unit or ''}".rstrip()
                if row.target_value is not None
                else ""
            )
            lines.append(
                f"• #{row.id} {self._clip(row.title, 80)} "
                f"[{row.status}]{progress}"
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
