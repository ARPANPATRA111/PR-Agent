"""Strict public-v2 request and response schemas."""

from datetime import date, datetime
from decimal import Decimal
import re
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

MAX_TEXT = 10_000
MAX_DESCRIPTION = 5_000
MAX_TAGS = 20
SUPPORTED_CURRENCIES = frozenset("""
    AED AFN ALL AMD ANG AOA ARS AUD AWG AZN BAM BBD BDT BGN BHD BIF BMD
    BND BOB BOV BRL BSD BTN BWP BYN BZD CAD CDF CHE CHF CHW CLF CLP CNY
    COP COU CRC CUC CUP CVE CZK DJF DKK DOP DZD EGP ERN ETB EUR FJD FKP
    GBP GEL GHS GIP GMD GNF GTQ GYD HKD HNL HRK HTG HUF IDR ILS INR IQD
    IRR ISK JMD JOD JPY KES KGS KHR KMF KPW KRW KWD KYD KZT LAK LBP LKR
    LRD LSL LYD MAD MDL MGA MKD MMK MNT MOP MRU MUR MVR MWK MXN MXV MYR
    MZN NAD NGN NIO NOK NPR NZD OMR PAB PEN PGK PHP PKR PLN PYG QAR RON
    RSD RUB RWF SAR SBD SCR SDG SEK SGD SHP SLE SLL SOS SRD SSP STN SVC
    SYP SZL THB TJS TMT TND TOP TRY TTD TWD TZS UAH UGX USD USN UYI UYU
    UYW UZS VED VES VND VUV WST XAF XAG XAU XBA XBB XBC XBD XCD XDR XOF
    XPD XPF XPT XSU XTS XUA XXX YER ZAR ZMW ZWL
    """.split())
ZERO_DECIMAL_CURRENCIES = frozenset(
    "BIF CLP DJF GNF ISK JPY KMF KRW PYG RWF UGX VND VUV XAF XOF XPF".split()
)
THREE_DECIMAL_CURRENCIES = frozenset("BHD IQD JOD KWD LYD OMR TND".split())


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RecordResponse(StrictSchema):
    model_config = ConfigDict(from_attributes=True, extra="forbid")
    id: int
    version: int
    created_at: datetime
    updated_at: datetime


def _reject_control_characters(value: str) -> str:
    if "\x00" in value:
        raise ValueError("Text contains a forbidden null character")
    return value


def _validate_timezone(value: str) -> str:
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("Unknown IANA timezone") from exc
    return value


def _normalize_tags(tags: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        normalized = tag.strip().lower()
        if not normalized or not re.fullmatch(r"[\w.-]{1,64}", normalized):
            raise ValueError(
                "Tags may contain letters, numbers, dot, dash, or underscore"
            )
        if normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    if len(result) > MAX_TAGS:
        raise ValueError(f"At most {MAX_TAGS} tags are allowed")
    return result


class IdempotentCreate(StrictSchema):
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=128)


class VersionedUpdate(StrictSchema):
    version: int = Field(ge=1)


class WorkLogCreate(IdempotentCreate):
    original_text: str = Field(min_length=1, max_length=MAX_TEXT)
    cleaned_text: str | None = Field(default=None, max_length=MAX_TEXT)
    category: str | None = Field(default=None, min_length=1, max_length=64)
    tags: list[str] = Field(default_factory=list)
    logged_at_local: datetime | None = None
    timezone: str = Field(default="UTC", min_length=1, max_length=64)
    capture_source: Literal["telegram_text", "telegram_voice", "mini_app", "api"] = (
        "api"
    )
    voice_file_id: str | None = Field(default=None, max_length=255)

    _text = field_validator("original_text", "cleaned_text")(
        lambda value: _reject_control_characters(value) if value is not None else value
    )
    _timezone = field_validator("timezone")(_validate_timezone)
    _tags = field_validator("tags")(_normalize_tags)


class WorkLogUpdate(VersionedUpdate):
    original_text: str | None = Field(default=None, min_length=1, max_length=MAX_TEXT)
    cleaned_text: str | None = Field(default=None, max_length=MAX_TEXT)
    category: str | None = Field(default=None, min_length=1, max_length=64)
    tags: list[str] | None = None
    logged_at_local: datetime | None = None
    timezone: str | None = Field(default=None, min_length=1, max_length=64)

    _text = field_validator("original_text", "cleaned_text")(
        lambda value: _reject_control_characters(value) if value is not None else value
    )
    _timezone = field_validator("timezone")(
        lambda value: _validate_timezone(value) if value is not None else value
    )
    _tags = field_validator("tags")(
        lambda value: _normalize_tags(value) if value is not None else value
    )


class WorkLogResponse(RecordResponse):
    original_text: str
    cleaned_text: str | None
    category: str | None
    tags: list[str]
    logged_at_utc: datetime
    user_local_date: date
    timezone: str
    capture_source: str


class NoteCreate(IdempotentCreate):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    body: str = Field(min_length=1, max_length=MAX_TEXT)
    tags: list[str] = Field(default_factory=list)
    pinned: bool = False
    capture_source: Literal["telegram_text", "telegram_voice", "mini_app", "api"] = (
        "api"
    )

    _text = field_validator("title", "body")(
        lambda value: _reject_control_characters(value) if value is not None else value
    )
    _tags = field_validator("tags")(_normalize_tags)


class NoteUpdate(VersionedUpdate):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    body: str | None = Field(default=None, min_length=1, max_length=MAX_TEXT)
    tags: list[str] | None = None
    pinned: bool | None = None

    _text = field_validator("title", "body")(
        lambda value: _reject_control_characters(value) if value is not None else value
    )
    _tags = field_validator("tags")(
        lambda value: _normalize_tags(value) if value is not None else value
    )


class NoteResponse(RecordResponse):
    title: str
    body: str
    tags: list[str]
    pinned: bool
    capture_source: str


class LedgerCreate(IdempotentCreate):
    direction: Literal["expense", "income"]
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=3)
    currency: str = Field(min_length=3, max_length=3)
    category: str | None = Field(default=None, min_length=1, max_length=64)
    description: str = Field(min_length=1, max_length=MAX_DESCRIPTION)
    transaction_at_local: datetime | None = None
    timezone: str = Field(default="UTC", min_length=1, max_length=64)
    capture_source: Literal["telegram_text", "telegram_voice", "mini_app", "api"] = (
        "api"
    )

    @field_validator("currency")
    @classmethod
    def currency_is_iso_4217(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in SUPPORTED_CURRENCIES:
            raise ValueError("Unsupported ISO 4217 currency")
        return normalized

    _timezone = field_validator("timezone")(_validate_timezone)
    _description = field_validator("description")(_reject_control_characters)

    @model_validator(mode="after")
    def currency_precision_is_valid(self):
        places = (
            0
            if self.currency in ZERO_DECIMAL_CURRENCIES
            else 3 if self.currency in THREE_DECIMAL_CURRENCIES else 2
        )
        exponent = -self.amount.as_tuple().exponent
        if exponent > places:
            raise ValueError(
                f"{self.currency} supports at most {places} decimal places"
            )
        return self


class LedgerUpdate(VersionedUpdate):
    amount: Decimal | None = Field(
        default=None,
        gt=0,
        max_digits=18,
        decimal_places=3,
    )
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    category: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_DESCRIPTION,
    )
    transaction_at_local: datetime | None = None
    timezone: str | None = Field(default=None, min_length=1, max_length=64)

    @field_validator("currency")
    @classmethod
    def currency_is_iso_4217(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.upper()
        if normalized not in SUPPORTED_CURRENCIES:
            raise ValueError("Unsupported ISO 4217 currency")
        return normalized

    _timezone = field_validator("timezone")(
        lambda value: _validate_timezone(value) if value is not None else value
    )
    _description = field_validator("description")(
        lambda value: _reject_control_characters(value) if value is not None else value
    )


class LedgerResponse(RecordResponse):
    direction: str
    amount_minor: int
    currency: str
    category: str | None
    description: str
    transaction_at_utc: datetime
    user_local_date: date
    timezone: str
    capture_source: str


class LedgerCurrencySummary(StrictSchema):
    currency: str
    expense_minor: int
    income_minor: int


class GoalCreate(IdempotentCreate):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=MAX_DESCRIPTION)
    target_value: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=18,
        decimal_places=4,
    )
    current_value: Decimal = Field(
        default=Decimal("0"),
        ge=0,
        max_digits=18,
        decimal_places=4,
    )
    unit: str | None = Field(default=None, min_length=1, max_length=32)
    start_date: date = Field(default_factory=date.today)
    due_date: date | None = None

    _text = field_validator("title", "description")(
        lambda value: _reject_control_characters(value) if value is not None else value
    )

    @model_validator(mode="after")
    def dates_are_ordered(self):
        if self.due_date is not None and self.due_date < self.start_date:
            raise ValueError("Due date cannot be before start date")
        return self


class GoalUpdate(VersionedUpdate):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=MAX_DESCRIPTION)
    target_value: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=18,
        decimal_places=4,
    )
    current_value: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=18,
        decimal_places=4,
    )
    unit: str | None = Field(default=None, min_length=1, max_length=32)
    start_date: date | None = None
    due_date: date | None = None
    status: Literal["active", "paused", "completed"] | None = None

    _text = field_validator("title", "description")(
        lambda value: _reject_control_characters(value) if value is not None else value
    )


class GoalResponse(RecordResponse):
    title: str
    description: str | None
    target_value: Decimal | None
    current_value: Decimal
    unit: str | None
    start_date: date
    due_date: date | None
    status: str


class ReminderCreate(IdempotentCreate):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=MAX_DESCRIPTION)
    schedule_type: Literal["once", "daily", "weekly"]
    start_at_local: datetime
    timezone: str = Field(min_length=1, max_length=64)
    weekday: int | None = Field(default=None, ge=0, le=6)

    _timezone = field_validator("timezone")(_validate_timezone)
    _text = field_validator("title", "description")(
        lambda value: _reject_control_characters(value) if value is not None else value
    )

    @model_validator(mode="after")
    def weekly_requires_weekday(self):
        if self.schedule_type == "weekly" and self.weekday is None:
            self.weekday = self.start_at_local.weekday()
        if self.schedule_type != "weekly" and self.weekday is not None:
            raise ValueError("weekday is only valid for weekly reminders")
        return self


class ReminderUpdate(VersionedUpdate):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=MAX_DESCRIPTION)
    start_at_local: datetime | None = None
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    weekday: int | None = Field(default=None, ge=0, le=6)
    enabled: bool | None = None

    _timezone = field_validator("timezone")(
        lambda value: _validate_timezone(value) if value is not None else value
    )
    _text = field_validator("title", "description")(
        lambda value: _reject_control_characters(value) if value is not None else value
    )


class ReminderResponse(RecordResponse):
    title: str
    description: str | None
    timezone: str
    schedule_type: str
    scheduled_local_time: str | None
    next_run_at_utc: datetime | None
    recurrence_rule: dict | None
    enabled: bool


class EstimatedNutritionItem(StrictSchema):
    original_item_text: str = Field(min_length=1, max_length=1_000)
    normalized_name: str = Field(min_length=1, max_length=255)
    quantity_value: Decimal = Field(
        gt=0,
        le=Decimal("100000"),
        max_digits=12,
        decimal_places=3,
    )
    quantity_unit: str = Field(min_length=1, max_length=32)
    portion_description: str | None = Field(default=None, max_length=255)
    estimated_grams: Decimal | None = Field(
        default=None,
        ge=0,
        le=Decimal("1000000"),
        max_digits=12,
        decimal_places=3,
    )
    calories: Decimal = Field(
        ge=0,
        le=Decimal("10000000"),
        max_digits=12,
        decimal_places=2,
    )
    protein_grams: Decimal = Field(
        ge=0,
        le=Decimal("1000000"),
        max_digits=12,
        decimal_places=3,
    )
    carbohydrate_grams: Decimal | None = Field(
        default=None,
        ge=0,
        le=Decimal("1000000"),
        max_digits=12,
        decimal_places=3,
    )
    fat_grams: Decimal | None = Field(
        default=None,
        ge=0,
        le=Decimal("1000000"),
        max_digits=12,
        decimal_places=3,
    )
    visible_assumptions: list[str] = Field(default_factory=list, max_length=10)
    confidence: Decimal | None = Field(
        default=None,
        ge=0,
        le=1,
        max_digits=5,
        decimal_places=4,
    )

    _text = field_validator(
        "original_item_text",
        "normalized_name",
        "portion_description",
    )(lambda value: _reject_control_characters(value) if value is not None else value)


class NutritionEstimate(StrictSchema):
    items: list[EstimatedNutritionItem] = Field(default_factory=list, max_length=50)
    visible_assumptions: list[str] = Field(default_factory=list, max_length=30)
    provider_name: str = Field(min_length=1, max_length=64)
    provider_version: str = Field(min_length=1, max_length=64)
    confidence: Decimal | None = Field(
        default=None,
        ge=0,
        le=1,
        max_digits=5,
        decimal_places=4,
    )
    clarification_required: bool = False
    clarification_question: str | None = Field(default=None, max_length=1_000)

    @model_validator(mode="after")
    def result_is_actionable(self):
        if self.clarification_required and not self.clarification_question:
            raise ValueError("A clarification question is required")
        if not self.clarification_required and not self.items:
            raise ValueError("At least one estimated item is required")
        return self


class NutritionDraftCreate(IdempotentCreate):
    original_text: str = Field(min_length=1, max_length=MAX_TEXT)
    meal_name: str | None = Field(default=None, min_length=1, max_length=128)
    logged_at_local: datetime | None = None
    timezone: str = Field(default="UTC", min_length=1, max_length=64)

    _timezone = field_validator("timezone")(_validate_timezone)
    _text = field_validator("original_text", "meal_name")(
        lambda value: _reject_control_characters(value) if value is not None else value
    )


class NutritionConfirm(VersionedUpdate):
    pass


class NutritionManualSave(VersionedUpdate):
    items: list[EstimatedNutritionItem] = Field(min_length=1, max_length=50)
    visible_assumptions: list[str] = Field(default_factory=list, max_length=30)


class NutritionItemUpdate(VersionedUpdate):
    quantity_value: Decimal | None = Field(
        default=None,
        gt=0,
        le=Decimal("100000"),
        max_digits=12,
        decimal_places=3,
    )
    quantity_unit: str | None = Field(default=None, min_length=1, max_length=32)
    portion_description: str | None = Field(default=None, max_length=255)
    estimated_grams: Decimal | None = Field(
        default=None,
        ge=0,
        le=Decimal("1000000"),
        max_digits=12,
        decimal_places=3,
    )
    calories: Decimal | None = Field(
        default=None,
        ge=0,
        le=Decimal("10000000"),
        max_digits=12,
        decimal_places=2,
    )
    protein_grams: Decimal | None = Field(
        default=None,
        ge=0,
        le=Decimal("1000000"),
        max_digits=12,
        decimal_places=3,
    )
    carbohydrate_grams: Decimal | None = Field(
        default=None,
        ge=0,
        le=Decimal("1000000"),
        max_digits=12,
        decimal_places=3,
    )
    fat_grams: Decimal | None = Field(
        default=None,
        ge=0,
        le=Decimal("1000000"),
        max_digits=12,
        decimal_places=3,
    )

    @model_validator(mode="after")
    def serving_edits_include_macros(self):
        serving_changed = any(
            value is not None
            for value in (
                self.quantity_value,
                self.quantity_unit,
                self.estimated_grams,
            )
        )
        if serving_changed and (self.calories is None or self.protein_grams is None):
            raise ValueError("Serving edits require updated calories and protein")
        return self


class NutritionItemResponse(RecordResponse):
    nutrition_log_id: int
    original_item_text: str
    normalized_name: str
    quantity_value: Decimal | None
    quantity_unit: str | None
    portion_description: str | None
    estimated_grams: Decimal | None
    calories: Decimal
    protein_grams: Decimal
    carbohydrate_grams: Decimal | None
    fat_grams: Decimal | None
    estimation_source: str
    confidence: Decimal | None
    visible_assumptions: list[str]
    user_modified: bool


class NutritionLogResponse(RecordResponse):
    meal_name: str | None
    logged_at_utc: datetime
    user_local_date: date
    timezone: str
    original_text: str
    status: str
    total_calories: Decimal
    total_protein_grams: Decimal
    total_carbohydrate_grams: Decimal | None
    total_fat_grams: Decimal | None
    estimation_source: str
    overall_confidence: Decimal | None
    visible_assumptions: list[str]
    provider_metadata: dict
    clarification_question: str | None
    confirmed_by_user: bool
    user_modified: bool
    items: list[NutritionItemResponse]


class NutritionPreferenceUpdate(VersionedUpdate):
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    calorie_target: Decimal | None = Field(
        default=None, ge=0, max_digits=12, decimal_places=2
    )
    protein_target_grams: Decimal | None = Field(
        default=None, ge=0, max_digits=12, decimal_places=3
    )
    carbohydrate_target_grams: Decimal | None = Field(
        default=None, ge=0, max_digits=12, decimal_places=3
    )
    fat_target_grams: Decimal | None = Field(
        default=None, ge=0, max_digits=12, decimal_places=3
    )
    default_milk_serving_ml: Decimal | None = Field(
        default=None,
        gt=0,
        le=5000,
        max_digits=10,
        decimal_places=2,
    )
    measurement_system: Literal["metric", "imperial"] | None = None
    nutrition_confirmation_required: bool | None = None

    _timezone = field_validator("timezone")(
        lambda value: _validate_timezone(value) if value is not None else value
    )


class NutritionPreferenceResponse(StrictSchema):
    model_config = ConfigDict(from_attributes=True, extra="forbid")
    owner_id: int
    version: int
    timezone: str
    calorie_target: Decimal | None
    protein_target_grams: Decimal | None
    carbohydrate_target_grams: Decimal | None
    fat_target_grams: Decimal | None
    default_milk_serving_ml: Decimal
    measurement_system: str
    nutrition_confirmation_required: bool
    created_at: datetime
    updated_at: datetime


class NutritionPeriodSummary(StrictSchema):
    start_date: date
    end_date: date
    confirmed_meals: int
    unestimated_meals: int
    total_calories: Decimal
    total_protein_grams: Decimal
    total_carbohydrate_grams: Decimal | None
    total_fat_grams: Decimal | None
    average_daily_calories: Decimal
    average_daily_protein_grams: Decimal
    calorie_target: Decimal | None
    protein_target_grams: Decimal | None
