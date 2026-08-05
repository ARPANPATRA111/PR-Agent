"""Strict model-output schemas for the bounded assistant."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictAction(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateWorkLogAction(StrictAction):
    kind: Literal["create_work_log"]
    text: str = Field(min_length=1, max_length=10_000)
    category: str | None = Field(default=None, min_length=1, max_length=64)
    tags: list[str] = Field(default_factory=list, max_length=20)


class CreateNoteAction(StrictAction):
    kind: Literal["create_note"]
    body: str = Field(min_length=1, max_length=10_000)
    title: str | None = Field(default=None, min_length=1, max_length=255)
    tags: list[str] = Field(default_factory=list, max_length=20)


class CreateLedgerAction(StrictAction):
    kind: Literal["create_ledger_entry"]
    direction: Literal["expense", "income"]
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=6)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    description: str = Field(min_length=1, max_length=10_000)
    category: str | None = Field(default=None, min_length=1, max_length=64)


class CreateReminderAction(StrictAction):
    kind: Literal["create_reminder"]
    title: str = Field(min_length=1, max_length=255)
    schedule_type: Literal["once", "daily", "weekly"]
    start_at_local: datetime
    timezone: str = Field(min_length=1, max_length=64)
    weekday: int | None = Field(default=None, ge=0, le=6)


class CreateNutritionAction(StrictAction):
    kind: Literal["create_nutrition_log"]
    text: str = Field(min_length=1, max_length=10_000)
    meal_name: str | None = Field(default=None, min_length=1, max_length=128)
    timezone: str = Field(default="UTC", min_length=1, max_length=64)


class CreateGoalAction(StrictAction):
    kind: Literal["create_goal"]
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=10_000)
    target_value: Decimal | None = Field(default=None, gt=0)
    unit: str | None = Field(default=None, min_length=1, max_length=64)


class QueryAction(StrictAction):
    kind: Literal["query"]
    query_type: Literal["today", "week", "spending", "nutrition", "goals"]
    timezone: str = Field(default="UTC", min_length=1, max_length=64)


class DeleteRecordAction(StrictAction):
    kind: Literal["delete_record"]
    record_type: Literal[
        "work_log",
        "note",
        "reminder",
        "ledger_entry",
        "nutrition_log",
        "goal",
    ]
    record_id: int = Field(gt=0)


class ClarificationAction(StrictAction):
    kind: Literal["clarification"]
    intended_kind: Literal[
        "create_work_log",
        "create_note",
        "create_ledger_entry",
        "create_reminder",
        "create_nutrition_log",
        "create_goal",
        "query",
        "delete_record",
        "unknown",
    ]
    question: str = Field(min_length=1, max_length=1000)
    missing_fields: list[str] = Field(min_length=1, max_length=20)
    known_arguments: dict = Field(default_factory=dict)

    @field_validator("known_arguments")
    @classmethod
    def model_never_supplies_identity(cls, value: dict) -> dict:
        prohibited = {
            "owner",
            "owner_id",
            "user",
            "user_id",
            "telegram_id",
            "chat_id",
        }
        if prohibited.intersection(str(key).lower() for key in value):
            raise ValueError("Identity fields are not accepted from model output")
        if len(value) > 30:
            raise ValueError("Too many proposed fields")
        return value


class UnsupportedAction(StrictAction):
    kind: Literal["unsupported"]
    reason: str = Field(min_length=1, max_length=500)


AgentActionProposal = Annotated[
    CreateWorkLogAction
    | CreateNoteAction
    | CreateLedgerAction
    | CreateReminderAction
    | CreateNutritionAction
    | CreateGoalAction
    | QueryAction
    | DeleteRecordAction
    | ClarificationAction
    | UnsupportedAction,
    Field(discriminator="kind"),
]


class AgentProposal(StrictAction):
    confidence: float = Field(ge=0, le=1)
    action: AgentActionProposal | None = None
    actions: list[AgentActionProposal] | None = Field(
        default=None,
        min_length=1,
        max_length=5,
    )

    @model_validator(mode="after")
    def exactly_one_action_shape(self):
        if (self.action is None) == (self.actions is None):
            raise ValueError("Provide exactly one of action or actions")
        return self

    @property
    def proposed_actions(self) -> list[AgentActionProposal]:
        return self.actions or [self.action]  # type: ignore[list-item]


class AgentBatchProposal(StrictAction):
    """Provider-facing envelope; one shape makes strict decoding reliable."""

    confidence: float = Field(ge=0, le=1)
    actions: list[AgentActionProposal] = Field(min_length=1, max_length=5)
