"""Strict model-output schemas for the bounded assistant."""

from __future__ import annotations

from datetime import date, datetime
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
    calories: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=12,
        decimal_places=2,
    )
    protein_grams: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=12,
        decimal_places=3,
    )

    @model_validator(mode="after")
    def manual_macros_are_a_complete_pair(self):
        if (self.calories is None) != (self.protein_grams is None):
            raise ValueError(
                "User-supplied calories and protein must be provided together"
            )
        return self


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
    start_date: date | None = None
    end_date: date | None = None
    search: str | None = Field(default=None, min_length=1, max_length=200)
    ranking: Literal["highest", "lowest"] | None = None

    @model_validator(mode="after")
    def query_period_is_ordered(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date cannot be before start_date")
        if self.query_type != "spending" and any(
            value is not None
            for value in (self.start_date, self.end_date, self.search, self.ranking)
        ):
            raise ValueError("Spending filters are only valid for spending queries")
        return self


RecordType = Literal[
    "work_log",
    "note",
    "reminder",
    "ledger_entry",
    "nutrition_log",
    "goal",
]


class ListRecordsAction(StrictAction):
    """Read-only retrieval across any owned record type.

    Every filter is applied by owner-scoped domain queries. The model chooses
    what to look for; it never receives or supplies an owner identity.
    """

    kind: Literal["list_records"]
    record_type: RecordType
    search: str | None = Field(default=None, min_length=1, max_length=200)
    tag: str | None = Field(default=None, min_length=1, max_length=64)
    status: (
        Literal[
            "active",
            "paused",
            "completed",
            "pinned",
            "enabled",
            "disabled",
            "draft",
            "confirmed",
        ]
        | None
    ) = None
    start_date: date | None = None
    end_date: date | None = None
    limit: int = Field(default=10, ge=1, le=25)
    timezone: str = Field(default="UTC", min_length=1, max_length=64)


class RecordSelector(StrictAction):
    """How the user referred to an existing record.

    Shared by every action that operates on something already stored. The
    application resolves this against owner-scoped records; the model never
    sees an id unless the user actually said one.
    """

    record_id: int | None = Field(default=None, gt=0)
    search: str | None = Field(default=None, min_length=1, max_length=200)
    ordinal: Literal["latest", "oldest"] | None = None

    @model_validator(mode="after")
    def requires_a_way_to_identify_the_record(self):
        if self.record_id is None and not self.search and self.ordinal is None:
            raise ValueError(
                "A record reference, search phrase, or ordinal is required"
            )
        return self


class UpdateRecordAction(StrictAction):
    """Change fields on an existing record.

    One action covers every record type rather than six near-identical ones,
    because strict decoding requires the model to emit every property of every
    action it could choose. A smaller schema measurably reduces malformed
    output. The application maps the supplied fields onto the correct
    versioned domain update and ignores those that do not apply.
    """

    kind: Literal["update_record"]
    record_type: RecordType
    selector: RecordSelector
    title: str | None = Field(default=None, min_length=1, max_length=255)
    text: str | None = Field(default=None, min_length=1, max_length=10_000)
    category: str | None = Field(default=None, min_length=1, max_length=64)
    tags: list[str] | None = Field(default=None, max_length=20)
    amount: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=3)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    target_value: Decimal | None = Field(default=None, ge=0, max_digits=18)
    unit: str | None = Field(default=None, min_length=1, max_length=64)
    start_at_local: datetime | None = None
    timezone: str | None = Field(default=None, min_length=1, max_length=64)

    @model_validator(mode="after")
    def requires_at_least_one_change(self):
        changes = (
            self.title,
            self.text,
            self.category,
            self.tags,
            self.amount,
            self.currency,
            self.target_value,
            self.unit,
            self.start_at_local,
        )
        if all(change is None for change in changes):
            raise ValueError("An update must change at least one field")
        return self


class SetRecordStatusAction(StrictAction):
    """Pause, resume, complete, pin, or confirm an existing record.

    These were five separate gaps. They are one action because they are the
    same operation from the user's point of view: change the state of a thing
    that already exists.
    """

    kind: Literal["set_record_status"]
    record_type: Literal["goal", "reminder", "note", "nutrition_log"]
    selector: RecordSelector
    status: Literal[
        "active",
        "paused",
        "completed",
        "enabled",
        "disabled",
        "pinned",
        "unpinned",
        "confirmed",
    ]


class RecordGoalProgressAction(StrictAction):
    """Add to, or set, a goal's current value."""

    kind: Literal["record_goal_progress"]
    selector: RecordSelector
    value: Decimal = Field(ge=0, max_digits=18, decimal_places=4)
    mode: Literal["add", "set"] = "add"


class UpdateSettingsAction(StrictAction):
    """Change the owner's own schedule preferences."""

    kind: Literal["update_settings"]
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    sunday_digest_enabled: bool | None = None
    sunday_digest_time: str | None = Field(
        default=None,
        pattern=r"^([01]\d|2[0-3]):[0-5]\d$",
    )

    @model_validator(mode="after")
    def requires_at_least_one_change(self):
        if (
            self.timezone is None
            and self.sunday_digest_enabled is None
            and self.sunday_digest_time is None
        ):
            raise ValueError("A settings update must change at least one field")
        return self


class SmalltalkAction(StrictAction):
    """A brief conversational or general-knowledge reply with no side effects.

    The length cap is the control: the model cannot turn the tracker into a
    general-purpose chatbot because the schema will not carry a long answer.
    """

    kind: Literal["smalltalk"]
    answer: str = Field(min_length=1, max_length=400)


class DeleteRecordAction(StrictAction):
    """Identifies what to delete, by id or by how the user referred to it.

    People say "delete my note about the invoice", not a row number. The model
    passes along the words; the application resolves them against owner-scoped
    records and still requires an explicit confirmation before deleting.
    """

    kind: Literal["delete_record"]
    record_type: RecordType
    record_id: int | None = Field(default=None, gt=0)
    search: str | None = Field(default=None, min_length=1, max_length=200)
    ordinal: Literal["latest", "oldest"] | None = None

    @model_validator(mode="after")
    def requires_a_way_to_identify_the_record(self):
        if self.record_id is None and not self.search and self.ordinal is None:
            raise ValueError(
                "Deletion needs a record id, a search phrase, or an ordinal"
            )
        return self


class DeleteManyRecordsAction(StrictAction):
    """Delete every owned record of one ordinary tracker type after review."""

    kind: Literal["delete_many_records"]
    record_type: RecordType
    scope: Literal["all"]


class RetrievePrivateFactAction(StrictAction):
    """Locate an encrypted fact by label; revealing remains application-owned."""

    kind: Literal["retrieve_private_fact"]
    label: str = Field(min_length=1, max_length=160)


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
        "list_records",
        "update_record",
        "set_record_status",
        "record_goal_progress",
        "update_settings",
        "delete_record",
        "delete_many_records",
        "retrieve_private_fact",
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
    | ListRecordsAction
    | SmalltalkAction
    | UpdateRecordAction
    | SetRecordStatusAction
    | RecordGoalProgressAction
    | UpdateSettingsAction
    | DeleteRecordAction
    | DeleteManyRecordsAction
    | RetrievePrivateFactAction
    | ClarificationAction
    | UnsupportedAction,
    Field(discriminator="kind"),
]

# Actions that operate on a record the user referred to in their own words.
# Each needs its reference resolved to a concrete owned row before review.
SELECTOR_ACTIONS = (
    UpdateRecordAction,
    SetRecordStatusAction,
    RecordGoalProgressAction,
)

# Actions that only read owner-scoped data or reply conversationally. They
# never mutate state, so they skip the Correct/Wrong review that exists to
# protect writes.
READ_ONLY_ACTIONS = (QueryAction, ListRecordsAction, SmalltalkAction)


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
