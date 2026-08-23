"""Tenant-scoped deterministic domain services.

The application intentionally uses synchronous SQLAlchemy sessions. FastAPI
exposes these services through synchronous route handlers, which run in its
thread pool; Telegram handlers explicitly offload calls with ``to_thread``.
"""

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, TypeVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, or_, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from abuse_controls import QuotaService
from config import settings
from domain.errors import ConcurrentUpdate, DomainError, RecordNotFound
from domain.schemas import (
    GoalCreate,
    GoalUpdate,
    NutritionDraftCreate,
    NutritionEstimate,
    NutritionItemUpdate,
    NutritionManualSave,
    NutritionPreferenceUpdate,
    LedgerCreate,
    LedgerUpdate,
    NoteCreate,
    NoteUpdate,
    ReminderCreate,
    ReminderUpdate,
    SchedulePreferenceUpdate,
    THREE_DECIMAL_CURRENCIES,
    WorkLogCreate,
    WorkLogUpdate,
    ZERO_DECIMAL_CURRENCIES,
)
from public_models import (
    AgentAction,
    LedgerEntry,
    Note,
    NutritionItem,
    NutritionLog,
    PublicUser,
    Reminder,
    ScheduledDigest,
    TrackedGoal,
    UserPreference,
    WorkLog,
)
from domain.scheduling import next_weekly_occurrence
from nutrition.providers import (
    NutritionEstimationProvider,
    NutritionProviderUnavailable,
)

UTC = timezone.utc
ModelT = TypeVar("ModelT")


def local_datetime_to_utc(value: datetime, timezone_name: str) -> datetime:
    """Convert a wall clock value and reject nonexistent DST wall times."""
    zone = ZoneInfo(timezone_name)
    if value.tzinfo is not None:
        return value.astimezone(UTC)
    localized = value.replace(tzinfo=zone, fold=0)
    utc_value = localized.astimezone(UTC)
    round_trip = utc_value.astimezone(zone).replace(tzinfo=None)
    if round_trip != value:
        raise DomainError("The local time does not exist in this timezone.")
    return utc_value


def utc_now() -> datetime:
    return datetime.now(UTC)


def local_date_bounds_utc(
    start_date: date | None,
    end_date: date | None,
    timezone_name: str,
) -> tuple[datetime | None, datetime | None]:
    """Convert inclusive local dates into an exclusive UTC timestamp range."""
    if start_date and end_date and end_date < start_date:
        raise DomainError("end_date cannot be before start_date.")
    try:
        start = (
            local_datetime_to_utc(
                datetime.combine(start_date, datetime.min.time()),
                timezone_name,
            )
            if start_date
            else None
        )
        end = (
            local_datetime_to_utc(
                datetime.combine(end_date + timedelta(days=1), datetime.min.time()),
                timezone_name,
            )
            if end_date
            else None
        )
    except ZoneInfoNotFoundError as exc:
        raise DomainError("Enter a valid IANA timezone.") from exc
    return start, end


def amount_to_minor(amount: Decimal, currency: str) -> int:
    places = (
        0
        if currency in ZERO_DECIMAL_CURRENCIES
        else 3 if currency in THREE_DECIMAL_CURRENCIES else 2
    )
    factor = Decimal(10) ** places
    minor = amount * factor
    if minor != minor.to_integral_value():
        raise DomainError(f"{currency} amount has too many decimal places.")
    result = int(minor)
    if result <= 0 or result > 9_000_000_000_000_000_000:
        raise DomainError("Amount is outside the supported range.")
    return result


class DomainServices:
    """Business operations shared by HTTP routes and Telegram commands."""

    def __init__(self, session: Session):
        self.session = session

    @staticmethod
    def _require_text_size(*values: str | None) -> None:
        if any(
            value is not None and len(value) > settings.max_text_entry_length
            for value in values
        ):
            raise DomainError("That text entry is longer than the configured limit.")

    def ensure_owner(
        self,
        *,
        telegram_id: int,
        first_name: str = "Telegram user",
        last_name: str | None = None,
        username: str | None = None,
    ) -> PublicUser:
        owner = (
            self.session.query(PublicUser)
            .filter(PublicUser.telegram_id == telegram_id)
            .one_or_none()
        )
        if owner is not None:
            owner.last_active = func.now()
            if username is not None:
                owner.username = username[:255]
        else:
            owner = PublicUser(
                telegram_id=telegram_id,
                first_name=(first_name or "Telegram user")[:255],
                last_name=last_name[:255] if last_name else None,
                username=username[:255] if username else None,
            )
            self.session.add(owner)
            try:
                self.session.flush()
            except IntegrityError:
                self.session.rollback()
                owner = (
                    self.session.query(PublicUser)
                    .filter(PublicUser.telegram_id == telegram_id)
                    .one()
                )
        preference = (
            self.session.query(UserPreference)
            .filter(UserPreference.owner_id == owner.id)
            .one_or_none()
        )
        if preference is None:
            preference = UserPreference(
                owner_id=owner.id,
                timezone=settings.timezone,
            )
            self.session.add(preference)
            self.session.flush()
        elif (
            preference.timezone == "UTC"
            and preference.version == 1
            and settings.timezone != "UTC"
        ):
            # Upgrade only untouched legacy defaults; never overwrite a timezone
            # that the user has explicitly saved.
            preference.timezone = settings.timezone
            preference.version += 1
            self.session.flush()
        digest = (
            self.session.query(ScheduledDigest)
            .filter(ScheduledDigest.owner_id == owner.id)
            .one_or_none()
        )
        if digest is None:
            self.session.add(
                ScheduledDigest(
                    owner_id=owner.id,
                    timezone=(preference.timezone if preference else settings.timezone),
                    weekday=6,
                    scheduled_local_time="20:00:00",
                    enabled=False,
                )
            )
            self.session.flush()
        elif (
            digest.timezone == "UTC"
            and digest.version == 1
            and settings.timezone != "UTC"
        ):
            digest.timezone = preference.timezone
            digest.version += 1
            self.session.flush()
        return owner

    def get_owner_by_telegram_id(self, telegram_id: int) -> PublicUser:
        owner = (
            self.session.query(PublicUser)
            .filter(PublicUser.telegram_id == telegram_id)
            .one_or_none()
        )
        if owner is None:
            raise RecordNotFound("User profile not found.")
        return owner

    @staticmethod
    def _idempotent_existing(
        session: Session,
        model: type[ModelT],
        owner_id: int,
        key: str | None,
    ) -> ModelT | None:
        if key is None:
            return None
        return (
            session.query(model)
            .filter(model.owner_id == owner_id, model.idempotency_key == key)
            .one_or_none()
        )

    def _flush_idempotent(
        self,
        model: type[ModelT],
        owner_id: int,
        key: str | None,
        record: ModelT,
    ) -> ModelT:
        self.session.add(record)
        try:
            self.session.flush()
            return record
        except IntegrityError:
            self.session.rollback()
            existing = self._idempotent_existing(
                self.session,
                model,
                owner_id,
                key,
            )
            if existing is None:
                raise
            return existing

    def _allocate_public_id(self, owner_id: int, record_type: str) -> int:
        """Atomically allocate a stable sequence number inside one owner/type."""
        value = self.session.execute(
            text(
                "INSERT INTO owner_record_counters "
                "(owner_id, record_type, last_value) "
                "VALUES (:owner_id, :record_type, 1) "
                "ON CONFLICT (owner_id, record_type) DO UPDATE "
                "SET last_value = owner_record_counters.last_value + 1 "
                "RETURNING last_value"
            ),
            {"owner_id": owner_id, "record_type": record_type},
        ).scalar_one()
        return int(value)

    @staticmethod
    def _require_owned(
        session: Session,
        model: type[ModelT],
        owner_id: int,
        record_id: int,
    ) -> ModelT:
        record = (
            session.query(model)
            .filter(model.id == record_id, model.owner_id == owner_id)
            .one_or_none()
        )
        if record is None:
            raise RecordNotFound()
        return record

    @staticmethod
    def _require_owned_public(
        session: Session,
        model: type[ModelT],
        owner_id: int,
        public_id: int,
    ) -> ModelT:
        record = (
            session.query(model)
            .filter(model.public_id == public_id, model.owner_id == owner_id)
            .one_or_none()
        )
        if record is None:
            raise RecordNotFound()
        return record

    def resolve_public_record_id(
        self,
        owner_id: int,
        record_type: str,
        public_id: int,
    ) -> int:
        """Resolve an external owner-scoped id to its private database key."""
        models = {
            "work_log": WorkLog,
            "note": Note,
            "ledger_entry": LedgerEntry,
            "nutrition_log": NutritionLog,
        }
        model = models.get(record_type)
        if model is None:
            return public_id
        return self._require_owned_public(
            self.session,
            model,
            owner_id,
            public_id,
        ).id

    def _versioned_update(
        self,
        model: type[ModelT],
        owner_id: int,
        record_id: int,
        expected_version: int,
        values: dict[str, Any],
    ) -> ModelT:
        values["version"] = model.version + 1
        values["updated_at"] = func.now()
        result = self.session.execute(
            update(model)
            .where(
                model.id == record_id,
                model.owner_id == owner_id,
                model.version == expected_version,
            )
            .values(**values)
        )
        if result.rowcount == 0:
            exists = (
                self.session.query(model.id)
                .filter(model.id == record_id, model.owner_id == owner_id)
                .first()
            )
            if exists is None:
                raise RecordNotFound()
            raise ConcurrentUpdate()
        self.session.flush()
        return self._require_owned(self.session, model, owner_id, record_id)

    @staticmethod
    def _delete_owned(
        session: Session,
        model: type[ModelT],
        owner_id: int,
        record_id: int,
    ) -> None:
        deleted = (
            session.query(model)
            .filter(model.id == record_id, model.owner_id == owner_id)
            .delete(synchronize_session=False)
        )
        if deleted == 0:
            raise RecordNotFound()

    @staticmethod
    def _clear_agent_reference(
        session: Session,
        owner_id: int,
        record_type: str,
        record_id: int,
    ) -> None:
        session.query(AgentAction).filter(
            AgentAction.owner_id == owner_id,
            AgentAction.record_type == record_type,
            AgentAction.record_id == record_id,
        ).update(
            {
                "record_type": None,
                "record_id": None,
            },
            synchronize_session=False,
        )

    # Work logs
    def create_work_log(self, owner_id: int, data: WorkLogCreate) -> WorkLog:
        existing = self._idempotent_existing(
            self.session,
            WorkLog,
            owner_id,
            data.idempotency_key,
        )
        if existing is not None:
            return existing
        self._require_text_size(data.original_text, data.cleaned_text)
        QuotaService(self.session).require(
            owner_id,
            "text_entries",
            limit=settings.per_user_daily_text_limit,
        )
        logged_at = (
            local_datetime_to_utc(data.logged_at_local, data.timezone)
            if data.logged_at_local
            else utc_now()
        )
        record = WorkLog(
            owner_id=owner_id,
            public_id=self._allocate_public_id(owner_id, "work_log"),
            original_text=data.original_text,
            cleaned_text=data.cleaned_text,
            category=data.category.lower() if data.category else None,
            tags=data.tags,
            logged_at_utc=logged_at,
            user_local_date=logged_at.astimezone(ZoneInfo(data.timezone)).date(),
            timezone=data.timezone,
            capture_source=data.capture_source,
            voice_file_id=data.voice_file_id,
            idempotency_key=data.idempotency_key,
        )
        return self._flush_idempotent(
            WorkLog,
            owner_id,
            data.idempotency_key,
            record,
        )

    def get_work_log(self, owner_id: int, record_id: int) -> WorkLog:
        return self._require_owned(self.session, WorkLog, owner_id, record_id)

    def get_work_log_by_public_id(self, owner_id: int, public_id: int) -> WorkLog:
        return self._require_owned_public(self.session, WorkLog, owner_id, public_id)

    def list_work_logs(
        self,
        owner_id: int,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        start_at_utc: datetime | None = None,
        end_at_utc: datetime | None = None,
        tag: str | None = None,
        category: str | None = None,
        search: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[WorkLog]:
        query = self.session.query(WorkLog).filter(WorkLog.owner_id == owner_id)
        if start_date:
            query = query.filter(WorkLog.user_local_date >= start_date)
        if end_date:
            query = query.filter(WorkLog.user_local_date <= end_date)
        if start_at_utc:
            query = query.filter(WorkLog.logged_at_utc >= start_at_utc)
        if end_at_utc:
            query = query.filter(WorkLog.logged_at_utc <= end_at_utc)
        if category:
            query = query.filter(WorkLog.category == category.lower())
        if search:
            pattern = f"%{search[:200]}%"
            query = query.filter(
                or_(
                    WorkLog.original_text.ilike(pattern),
                    WorkLog.cleaned_text.ilike(pattern),
                )
            )
        rows = (
            query.order_by(WorkLog.logged_at_utc.desc())
            .offset(offset)
            .limit(min(limit * 4 if tag else limit, 400))
            .all()
        )
        if tag:
            normalized = tag.strip().lower()
            rows = [row for row in rows if normalized in (row.tags or [])]
        return rows[:limit]

    def aggregate_work_logs(
        self,
        owner_id: int,
        start_date: date,
        end_date: date,
    ) -> dict[str, Any]:
        rows = (
            self.session.query(WorkLog)
            .filter(
                WorkLog.owner_id == owner_id,
                WorkLog.user_local_date >= start_date,
                WorkLog.user_local_date <= end_date,
            )
            .all()
        )
        daily: dict[str, int] = defaultdict(int)
        categories: dict[str, int] = defaultdict(int)
        for row in rows:
            daily[row.user_local_date.isoformat()] += 1
            categories[row.category or "uncategorized"] += 1
        return {
            "total": len(rows),
            "daily": dict(sorted(daily.items())),
            "categories": dict(sorted(categories.items())),
        }

    def update_work_log(
        self,
        owner_id: int,
        record_id: int,
        data: WorkLogUpdate,
    ) -> WorkLog:
        current = self.get_work_log(owner_id, record_id)
        values = data.model_dump(exclude={"version"}, exclude_unset=True)
        if values.get("category"):
            values["category"] = values["category"].lower()
        logged_at_local = values.pop("logged_at_local", None)
        timezone_name = values.get("timezone", current.timezone)
        if logged_at_local is not None:
            logged_at = local_datetime_to_utc(logged_at_local, timezone_name)
            values["logged_at_utc"] = logged_at
            values["user_local_date"] = logged_at.astimezone(
                ZoneInfo(timezone_name)
            ).date()
        elif "timezone" in values:
            aware = current.logged_at_utc
            if aware.tzinfo is None:
                aware = aware.replace(tzinfo=UTC)
            values["user_local_date"] = aware.astimezone(ZoneInfo(timezone_name)).date()
        return self._versioned_update(
            WorkLog,
            owner_id,
            record_id,
            data.version,
            values,
        )

    def delete_work_log(self, owner_id: int, record_id: int) -> None:
        self._delete_owned(self.session, WorkLog, owner_id, record_id)
        self._clear_agent_reference(
            self.session,
            owner_id,
            "work_log",
            record_id,
        )

    # Notes
    def create_note(self, owner_id: int, data: NoteCreate) -> Note:
        existing = self._idempotent_existing(
            self.session, Note, owner_id, data.idempotency_key
        )
        if existing is not None:
            return existing
        self._require_text_size(data.title, data.body)
        QuotaService(self.session).require(
            owner_id,
            "text_entries",
            limit=settings.per_user_daily_text_limit,
        )
        title = data.title or data.body.splitlines()[0][:80]
        record = Note(
            owner_id=owner_id,
            public_id=self._allocate_public_id(owner_id, "note"),
            title=title,
            body=data.body,
            tags=data.tags,
            pinned=data.pinned,
            capture_source=data.capture_source,
            idempotency_key=data.idempotency_key,
        )
        return self._flush_idempotent(Note, owner_id, data.idempotency_key, record)

    def get_note(self, owner_id: int, record_id: int) -> Note:
        return self._require_owned(self.session, Note, owner_id, record_id)

    def get_note_by_public_id(self, owner_id: int, public_id: int) -> Note:
        return self._require_owned_public(self.session, Note, owner_id, public_id)

    def list_notes(
        self,
        owner_id: int,
        *,
        search: str | None = None,
        tag: str | None = None,
        pinned: bool | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        timezone_name: str = "UTC",
        start_at_utc: datetime | None = None,
        end_at_utc: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Note]:
        query = self.session.query(Note).filter(Note.owner_id == owner_id)
        date_start_at_utc, date_end_at_utc = local_date_bounds_utc(
            start_date,
            end_date,
            timezone_name,
        )
        if date_start_at_utc:
            query = query.filter(Note.created_at >= date_start_at_utc)
        if date_end_at_utc:
            query = query.filter(Note.created_at < date_end_at_utc)
        if start_at_utc:
            query = query.filter(Note.created_at >= start_at_utc)
        if end_at_utc:
            query = query.filter(Note.created_at <= end_at_utc)
        if search:
            pattern = f"%{search[:200]}%"
            query = query.filter(
                or_(Note.title.ilike(pattern), Note.body.ilike(pattern))
            )
        if pinned is not None:
            query = query.filter(Note.pinned == pinned)
        rows = (
            query.order_by(Note.pinned.desc(), Note.updated_at.desc())
            .offset(offset)
            .limit(min(limit * 4 if tag else limit, 400))
            .all()
        )
        if tag:
            normalized = tag.strip().lower()
            rows = [row for row in rows if normalized in (row.tags or [])]
        return rows[:limit]

    def update_note(self, owner_id: int, record_id: int, data: NoteUpdate) -> Note:
        values = data.model_dump(exclude={"version"}, exclude_unset=True)
        return self._versioned_update(Note, owner_id, record_id, data.version, values)

    def delete_note(self, owner_id: int, record_id: int) -> None:
        self._delete_owned(self.session, Note, owner_id, record_id)
        self._clear_agent_reference(self.session, owner_id, "note", record_id)

    # Ledger
    def create_ledger_entry(self, owner_id: int, data: LedgerCreate) -> LedgerEntry:
        existing = self._idempotent_existing(
            self.session, LedgerEntry, owner_id, data.idempotency_key
        )
        if existing is not None:
            return existing
        self._require_text_size(data.description)
        QuotaService(self.session).require(
            owner_id,
            "text_entries",
            limit=settings.per_user_daily_text_limit,
        )
        transacted_at = (
            local_datetime_to_utc(data.transaction_at_local, data.timezone)
            if data.transaction_at_local
            else utc_now()
        )
        record = LedgerEntry(
            owner_id=owner_id,
            public_id=self._allocate_public_id(owner_id, "ledger_entry"),
            direction=data.direction,
            amount_minor=amount_to_minor(data.amount, data.currency),
            currency=data.currency,
            category=data.category.lower() if data.category else None,
            description=data.description,
            transaction_at_utc=transacted_at,
            user_local_date=transacted_at.astimezone(ZoneInfo(data.timezone)).date(),
            timezone=data.timezone,
            capture_source=data.capture_source,
            idempotency_key=data.idempotency_key,
        )
        return self._flush_idempotent(
            LedgerEntry, owner_id, data.idempotency_key, record
        )

    def get_ledger_entry(self, owner_id: int, record_id: int) -> LedgerEntry:
        return self._require_owned(self.session, LedgerEntry, owner_id, record_id)

    def get_ledger_entry_by_public_id(
        self, owner_id: int, public_id: int
    ) -> LedgerEntry:
        return self._require_owned_public(
            self.session, LedgerEntry, owner_id, public_id
        )

    def list_ledger_entries(
        self,
        owner_id: int,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        category: str | None = None,
        direction: str | None = None,
        search: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[LedgerEntry]:
        query = self.session.query(LedgerEntry).filter(LedgerEntry.owner_id == owner_id)
        if start_date:
            query = query.filter(LedgerEntry.user_local_date >= start_date)
        if end_date:
            query = query.filter(LedgerEntry.user_local_date <= end_date)
        if category:
            query = query.filter(LedgerEntry.category == category.lower())
        if direction:
            query = query.filter(LedgerEntry.direction == direction)
        if search:
            pattern = f"%{search[:200]}%"
            query = query.filter(
                or_(
                    LedgerEntry.description.ilike(pattern),
                    LedgerEntry.category.ilike(pattern),
                )
            )
        return (
            query.order_by(LedgerEntry.transaction_at_utc.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

    def summarize_ledger(
        self,
        owner_id: int,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[dict[str, Any]]:
        query = self.session.query(
            LedgerEntry.currency,
            LedgerEntry.direction,
            func.sum(LedgerEntry.amount_minor),
        ).filter(LedgerEntry.owner_id == owner_id)
        if start_date:
            query = query.filter(LedgerEntry.user_local_date >= start_date)
        if end_date:
            query = query.filter(LedgerEntry.user_local_date <= end_date)
        grouped: dict[str, dict[str, Any]] = {}
        for currency, direction, total in query.group_by(
            LedgerEntry.currency, LedgerEntry.direction
        ):
            grouped.setdefault(
                currency,
                {
                    "currency": currency,
                    "expense_minor": 0,
                    "income_minor": 0,
                },
            )[f"{direction}_minor"] = int(total)
        return [grouped[key] for key in sorted(grouped)]

    def analyze_expenses(
        self,
        owner_id: int,
        *,
        start_date: date,
        end_date: date,
        search: str | None = None,
    ) -> dict[str, Any]:
        """Return exact owned expense totals and category aggregates."""
        query = self.session.query(LedgerEntry).filter(
            LedgerEntry.owner_id == owner_id,
            LedgerEntry.direction == "expense",
            LedgerEntry.user_local_date >= start_date,
            LedgerEntry.user_local_date <= end_date,
        )
        if search:
            pattern = f"%{search[:200]}%"
            query = query.filter(
                or_(
                    LedgerEntry.description.ilike(pattern),
                    LedgerEntry.category.ilike(pattern),
                )
            )
        rows = query.order_by(LedgerEntry.transaction_at_utc.desc()).all()
        totals: dict[str, dict[str, int]] = defaultdict(
            lambda: {"amount_minor": 0, "count": 0}
        )
        categories: dict[tuple[str, str], dict[str, Any]] = defaultdict(
            lambda: {"amount_minor": 0, "count": 0}
        )
        for row in rows:
            totals[row.currency]["amount_minor"] += row.amount_minor
            totals[row.currency]["count"] += 1
            category = row.category or "uncategorized"
            bucket = categories[(row.currency, category)]
            bucket["amount_minor"] += row.amount_minor
            bucket["count"] += 1
        return {
            "entries": rows,
            "totals": [
                {"currency": currency, **values}
                for currency, values in sorted(totals.items())
            ],
            "categories": [
                {"currency": currency, "category": category, **values}
                for (currency, category), values in sorted(categories.items())
            ],
        }

    def update_ledger_entry(
        self, owner_id: int, record_id: int, data: LedgerUpdate
    ) -> LedgerEntry:
        current = self.get_ledger_entry(owner_id, record_id)
        values = data.model_dump(exclude={"version"}, exclude_unset=True)
        if values.get("category"):
            values["category"] = values["category"].lower()
        amount = values.pop("amount", None)
        currency = values.get("currency", current.currency)
        if amount is not None:
            values["amount_minor"] = amount_to_minor(amount, currency)
        elif "currency" in values:
            raise DomainError("Changing currency also requires an amount.")
        transaction_local = values.pop("transaction_at_local", None)
        timezone_name = values.get("timezone", current.timezone)
        if transaction_local is not None:
            transacted_at = local_datetime_to_utc(transaction_local, timezone_name)
            values["transaction_at_utc"] = transacted_at
            values["user_local_date"] = transacted_at.astimezone(
                ZoneInfo(timezone_name)
            ).date()
        return self._versioned_update(
            LedgerEntry, owner_id, record_id, data.version, values
        )

    def delete_ledger_entry(self, owner_id: int, record_id: int) -> None:
        self._delete_owned(self.session, LedgerEntry, owner_id, record_id)
        self._clear_agent_reference(
            self.session,
            owner_id,
            "ledger_entry",
            record_id,
        )

    # Goals
    def create_goal(self, owner_id: int, data: GoalCreate) -> TrackedGoal:
        existing = self._idempotent_existing(
            self.session, TrackedGoal, owner_id, data.idempotency_key
        )
        if existing is not None:
            return existing
        self._require_text_size(data.title, data.description)
        QuotaService(self.session).require(
            owner_id,
            "text_entries",
            limit=settings.per_user_daily_text_limit,
        )
        record = TrackedGoal(
            owner_id=owner_id,
            title=data.title,
            description=data.description,
            target_value=data.target_value,
            current_value=data.current_value,
            unit=data.unit,
            start_date=data.start_date,
            due_date=data.due_date,
            status="active",
            idempotency_key=data.idempotency_key,
        )
        return self._flush_idempotent(
            TrackedGoal, owner_id, data.idempotency_key, record
        )

    def get_goal(self, owner_id: int, record_id: int) -> TrackedGoal:
        return self._require_owned(self.session, TrackedGoal, owner_id, record_id)

    def list_goals(
        self,
        owner_id: int,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[TrackedGoal]:
        query = self.session.query(TrackedGoal).filter(TrackedGoal.owner_id == owner_id)
        if status:
            query = query.filter(TrackedGoal.status == status)
        return (
            query.order_by(TrackedGoal.updated_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

    def update_goal(
        self, owner_id: int, record_id: int, data: GoalUpdate
    ) -> TrackedGoal:
        current = self.get_goal(owner_id, record_id)
        values = data.model_dump(exclude={"version"}, exclude_unset=True)
        start = values.get("start_date", current.start_date)
        due = values.get("due_date", current.due_date)
        if due is not None and due < start:
            raise DomainError("Due date cannot be before start date.")
        return self._versioned_update(
            TrackedGoal, owner_id, record_id, data.version, values
        )

    def delete_goal(self, owner_id: int, record_id: int) -> None:
        self._delete_owned(self.session, TrackedGoal, owner_id, record_id)
        self._clear_agent_reference(self.session, owner_id, "goal", record_id)

    # Reminders
    @staticmethod
    def _next_reminder_run(data: ReminderCreate) -> datetime:
        first = local_datetime_to_utc(data.start_at_local, data.timezone)
        now = utc_now()
        if data.schedule_type == "once":
            if first <= now:
                raise DomainError("A one-time reminder must be in the future.")
            return first

        zone = ZoneInfo(data.timezone)
        local_now = now.astimezone(zone)
        requested_time = data.start_at_local.time().replace(tzinfo=None)
        if data.schedule_type == "daily":
            candidate_date = max(
                data.start_at_local.date(),
                local_now.date(),
            )
            candidate = datetime.combine(candidate_date, requested_time)
            candidate_utc = local_datetime_to_utc(candidate, data.timezone)
            if candidate_utc <= now:
                candidate = datetime.combine(
                    candidate_date + timedelta(days=1), requested_time
                )
            return local_datetime_to_utc(candidate, data.timezone)

        weekday = data.weekday if data.weekday is not None else first.weekday()
        days_ahead = (weekday - local_now.weekday()) % 7
        candidate_date = max(
            data.start_at_local.date(),
            local_now.date() + timedelta(days=days_ahead),
        )
        while candidate_date.weekday() != weekday:
            candidate_date += timedelta(days=1)
        candidate = datetime.combine(candidate_date, requested_time)
        candidate_utc = local_datetime_to_utc(candidate, data.timezone)
        if candidate_utc <= now:
            candidate += timedelta(days=7)
        return local_datetime_to_utc(candidate, data.timezone)

    def create_reminder(self, owner_id: int, data: ReminderCreate) -> Reminder:
        existing = self._idempotent_existing(
            self.session, Reminder, owner_id, data.idempotency_key
        )
        if existing is not None:
            return existing
        self._require_text_size(data.title, data.description)
        reminder_count = (
            self.session.query(func.count(Reminder.id))
            .filter(
                Reminder.owner_id == owner_id,
                Reminder.enabled.is_(True),
            )
            .scalar()
            or 0
        )
        if reminder_count >= settings.max_reminders_per_user:
            from abuse_controls import QuotaExceeded

            raise QuotaExceeded("The active reminder limit has been reached.")
        QuotaService(self.session).require(
            owner_id,
            "text_entries",
            limit=settings.per_user_daily_text_limit,
        )
        next_run = self._next_reminder_run(data)
        recurrence = (
            None
            if data.schedule_type == "once"
            else {
                "frequency": data.schedule_type,
                **({"weekday": data.weekday} if data.schedule_type == "weekly" else {}),
            }
        )
        record = Reminder(
            owner_id=owner_id,
            title=data.title,
            description=data.description,
            timezone=data.timezone,
            schedule_type=data.schedule_type,
            scheduled_local_time=data.start_at_local.strftime("%H:%M:%S"),
            next_run_at_utc=next_run,
            recurrence_rule=recurrence,
            enabled=True,
            idempotency_key=data.idempotency_key,
        )
        return self._flush_idempotent(Reminder, owner_id, data.idempotency_key, record)

    def get_reminder(self, owner_id: int, record_id: int) -> Reminder:
        return self._require_owned(self.session, Reminder, owner_id, record_id)

    def list_reminders(
        self,
        owner_id: int,
        *,
        enabled: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Reminder]:
        query = self.session.query(Reminder).filter(Reminder.owner_id == owner_id)
        if enabled is not None:
            query = query.filter(Reminder.enabled == enabled)
        return (
            query.order_by(Reminder.next_run_at_utc.asc())
            .offset(offset)
            .limit(limit)
            .all()
        )

    def update_reminder(
        self, owner_id: int, record_id: int, data: ReminderUpdate
    ) -> Reminder:
        current = self.get_reminder(owner_id, record_id)
        values = data.model_dump(
            exclude={"version", "start_at_local", "weekday"},
            exclude_unset=True,
        )
        if data.weekday is not None and data.start_at_local is None:
            raise DomainError(
                "Changing a weekly weekday also requires a new local time."
            )
        if data.start_at_local is not None:
            create_data = ReminderCreate(
                title=data.title or current.title,
                description=(
                    data.description
                    if data.description is not None
                    else current.description
                ),
                schedule_type=current.schedule_type,
                start_at_local=data.start_at_local,
                timezone=data.timezone or current.timezone,
                weekday=(
                    data.weekday
                    if data.weekday is not None
                    else (current.recurrence_rule or {}).get("weekday")
                ),
            )
            values["next_run_at_utc"] = self._next_reminder_run(create_data)
            values["scheduled_local_time"] = data.start_at_local.strftime("%H:%M:%S")
            values["timezone"] = create_data.timezone
            if current.schedule_type == "weekly":
                values["recurrence_rule"] = {
                    "frequency": "weekly",
                    "weekday": create_data.weekday,
                }
        return self._versioned_update(
            Reminder, owner_id, record_id, data.version, values
        )

    def delete_reminder(self, owner_id: int, record_id: int) -> None:
        self._delete_owned(self.session, Reminder, owner_id, record_id)
        self._clear_agent_reference(
            self.session,
            owner_id,
            "reminder",
            record_id,
        )

    # Durable per-user schedule preferences
    def get_schedule_preferences(self, owner_id: int) -> dict[str, Any]:
        preference = (
            self.session.query(UserPreference)
            .filter(UserPreference.owner_id == owner_id)
            .one_or_none()
        )
        if preference is None:
            preference = UserPreference(
                owner_id=owner_id,
                timezone=settings.timezone,
            )
            self.session.add(preference)
            self.session.flush()
        digest = (
            self.session.query(ScheduledDigest)
            .filter(ScheduledDigest.owner_id == owner_id)
            .one_or_none()
        )
        if digest is None:
            digest = ScheduledDigest(
                owner_id=owner_id,
                timezone=preference.timezone,
                weekday=6,
                scheduled_local_time="20:00:00",
                enabled=preference.sunday_digest_enabled,
            )
            self.session.add(digest)
            self.session.flush()
        return {
            "preference_version": preference.version,
            "digest_version": digest.version,
            "timezone": preference.timezone,
            "sunday_digest_enabled": digest.enabled,
            "sunday_digest_time": digest.scheduled_local_time,
            "next_digest_at_utc": digest.next_run_at_utc,
        }

    def update_schedule_preferences(
        self,
        owner_id: int,
        data: SchedulePreferenceUpdate,
    ) -> dict[str, Any]:
        current = self.get_schedule_preferences(owner_id)
        if (
            current["preference_version"] != data.preference_version
            or current["digest_version"] != data.digest_version
        ):
            raise ConcurrentUpdate(
                "Schedule settings changed elsewhere. Reload and try again."
            )
        preference = (
            self.session.query(UserPreference)
            .filter(UserPreference.owner_id == owner_id)
            .one()
        )
        digest = (
            self.session.query(ScheduledDigest)
            .filter(ScheduledDigest.owner_id == owner_id)
            .one()
        )
        local_time = data.sunday_digest_time.replace(tzinfo=None)
        preference.timezone = data.timezone
        preference.sunday_digest_enabled = data.sunday_digest_enabled
        preference.version += 1
        digest.timezone = data.timezone
        digest.weekday = 6
        digest.scheduled_local_time = local_time.isoformat()
        digest.enabled = data.sunday_digest_enabled
        digest.next_run_at_utc = (
            next_weekly_occurrence(
                timezone_name=data.timezone,
                weekday=6,
                scheduled_local_time=local_time.isoformat(),
                after_utc=utc_now(),
            )
            if data.sunday_digest_enabled
            else None
        )
        digest.version += 1
        self.session.flush()
        return self.get_schedule_preferences(owner_id)

    # Nutrition
    def get_nutrition_preferences(self, owner_id: int) -> UserPreference:
        preference = (
            self.session.query(UserPreference)
            .filter(UserPreference.owner_id == owner_id)
            .one_or_none()
        )
        if preference is None:
            self.session.add(
                UserPreference(owner_id=owner_id, timezone=settings.timezone)
            )
            self.session.flush()
            preference = (
                self.session.query(UserPreference)
                .filter(UserPreference.owner_id == owner_id)
                .one()
            )
        return preference

    def update_nutrition_preferences(
        self,
        owner_id: int,
        data: NutritionPreferenceUpdate,
    ) -> UserPreference:
        self.get_nutrition_preferences(owner_id)
        values = data.model_dump(exclude={"version"}, exclude_unset=True)
        values["version"] = UserPreference.version + 1
        values["updated_at"] = func.now()
        result = self.session.execute(
            update(UserPreference)
            .where(
                UserPreference.owner_id == owner_id,
                UserPreference.version == data.version,
            )
            .values(**values)
        )
        if result.rowcount == 0:
            raise ConcurrentUpdate()
        self.session.flush()
        return self.get_nutrition_preferences(owner_id)

    def create_nutrition_draft(
        self,
        owner_id: int,
        data: NutritionDraftCreate,
    ) -> NutritionLog:
        existing = self._idempotent_existing(
            self.session,
            NutritionLog,
            owner_id,
            data.idempotency_key,
        )
        if existing is not None:
            return existing
        self._require_text_size(data.original_text, data.meal_name)
        logged_at = (
            local_datetime_to_utc(data.logged_at_local, data.timezone)
            if data.logged_at_local
            else utc_now()
        )
        record = NutritionLog(
            owner_id=owner_id,
            public_id=self._allocate_public_id(owner_id, "nutrition_log"),
            meal_name=data.meal_name,
            logged_at_utc=logged_at,
            user_local_date=logged_at.astimezone(ZoneInfo(data.timezone)).date(),
            timezone=data.timezone,
            original_text=data.original_text,
            status="draft",
            visible_assumptions=[],
            provider_metadata={},
            clarification_question=None,
            total_calories=Decimal("0"),
            total_protein_grams=Decimal("0"),
            total_carbohydrate_grams=Decimal("0"),
            total_fat_grams=Decimal("0"),
            estimation_source="pending",
            confirmed_by_user=False,
            user_modified=False,
            idempotency_key=data.idempotency_key,
        )
        return self._flush_idempotent(
            NutritionLog,
            owner_id,
            data.idempotency_key,
            record,
        )

    def estimate_nutrition_draft(
        self,
        owner_id: int,
        data: NutritionDraftCreate,
        provider: NutritionEstimationProvider,
    ) -> NutritionLog:
        draft = self.create_nutrition_draft(owner_id, data)
        if draft.estimation_source != "pending":
            return draft
        QuotaService(self.session).require(
            owner_id,
            "nutrition_estimations",
            limit=settings.per_user_daily_nutrition_limit,
        )
        preferences = self.get_nutrition_preferences(owner_id)
        try:
            estimate = provider.estimate(
                data.original_text,
                default_milk_serving_ml=preferences.default_milk_serving_ml,
                measurement_system=preferences.measurement_system,
            )
            estimate = NutritionEstimate.model_validate(estimate)
        except NutritionProviderUnavailable:
            draft.estimation_source = "provider_unavailable"
            draft.provider_metadata = {
                "status": "unavailable",
                "retryable": True,
            }
            draft.clarification_question = (
                "Estimation is unavailable. Save as an unestimated food note "
                "or enter calories and protein manually."
            )
            draft.version += 1
            self.session.flush()
            return draft
        except Exception:
            draft.estimation_source = "provider_invalid"
            draft.provider_metadata = {
                "status": "invalid_response",
                "retryable": True,
            }
            draft.clarification_question = (
                "The nutrition estimate could not be validated. Enter values "
                "manually or try again later."
            )
            draft.version += 1
            self.session.flush()
            return draft

        self._replace_nutrition_items(owner_id, draft, estimate)
        draft.estimation_source = (
            f"{estimate.provider_name}:{estimate.provider_version}"
        )
        draft.provider_metadata = {
            "provider": estimate.provider_name,
            "version": estimate.provider_version,
        }
        draft.visible_assumptions = estimate.visible_assumptions
        draft.overall_confidence = estimate.confidence
        draft.clarification_question = estimate.clarification_question
        draft.version += 1
        if (
            not estimate.clarification_required
            and estimate.confidence is not None
            and estimate.confidence < Decimal("0.5")
        ):
            draft.clarification_question = (
                "This estimate has low confidence. Please edit or confirm the "
                "serving details."
            )
        if (
            not estimate.clarification_required
            and draft.clarification_question is None
            and not preferences.nutrition_confirmation_required
        ):
            draft.status = "confirmed"
            draft.confirmed_by_user = False
        self.session.flush()
        return draft

    def apply_manual_nutrition(
        self,
        owner_id: int,
        record_id: int,
        data: NutritionManualSave,
        *,
        confirm: bool = True,
    ) -> NutritionLog:
        draft = self.get_nutrition_log(owner_id, record_id)
        if draft.version != data.version:
            raise ConcurrentUpdate()
        estimate = NutritionEstimate(
            items=data.items,
            visible_assumptions=data.visible_assumptions,
            provider_name="manual",
            provider_version="user",
            confidence=Decimal("1"),
        )
        self._replace_nutrition_items(owner_id, draft, estimate)
        draft.estimation_source = "manual"
        draft.provider_metadata = {"provider": "manual"}
        draft.visible_assumptions = data.visible_assumptions
        draft.clarification_question = None
        draft.status = "confirmed" if confirm else "draft"
        draft.confirmed_by_user = confirm
        draft.user_modified = True
        draft.version += 1
        self.session.flush()
        return draft

    def _replace_nutrition_items(
        self,
        owner_id: int,
        draft: NutritionLog,
        estimate: NutritionEstimate,
    ) -> None:
        (
            self.session.query(NutritionItem)
            .filter(
                NutritionItem.owner_id == owner_id,
                NutritionItem.nutrition_log_id == draft.id,
            )
            .delete(synchronize_session=False)
        )
        for item in estimate.items:
            self.session.add(
                NutritionItem(
                    nutrition_log_id=draft.id,
                    owner_id=owner_id,
                    original_item_text=item.original_item_text,
                    normalized_name=item.normalized_name,
                    quantity_value=item.quantity_value,
                    quantity_unit=item.quantity_unit,
                    portion_description=item.portion_description,
                    estimated_grams=item.estimated_grams,
                    calories=item.calories,
                    protein_grams=item.protein_grams,
                    carbohydrate_grams=item.carbohydrate_grams,
                    fat_grams=item.fat_grams,
                    estimation_source=(
                        f"{estimate.provider_name}:{estimate.provider_version}"
                    ),
                    confidence=item.confidence,
                    visible_assumptions=item.visible_assumptions,
                    user_modified=estimate.provider_name == "manual",
                )
            )
        self.session.flush()
        self._recalculate_nutrition_totals(draft)

    def _recalculate_nutrition_totals(self, log: NutritionLog) -> None:
        items = (
            self.session.query(NutritionItem)
            .filter(
                NutritionItem.owner_id == log.owner_id,
                NutritionItem.nutrition_log_id == log.id,
            )
            .all()
        )
        log.total_calories = sum((item.calories for item in items), Decimal("0"))
        log.total_protein_grams = sum(
            (item.protein_grams for item in items), Decimal("0")
        )
        log.total_carbohydrate_grams = sum(
            (item.carbohydrate_grams or Decimal("0") for item in items),
            Decimal("0"),
        )
        log.total_fat_grams = sum(
            (item.fat_grams or Decimal("0") for item in items),
            Decimal("0"),
        )

    def get_nutrition_log(
        self,
        owner_id: int,
        record_id: int,
    ) -> NutritionLog:
        return self._require_owned(self.session, NutritionLog, owner_id, record_id)

    def get_nutrition_log_by_public_id(
        self,
        owner_id: int,
        public_id: int,
    ) -> NutritionLog:
        return self._require_owned_public(
            self.session, NutritionLog, owner_id, public_id
        )

    def list_nutrition_logs(
        self,
        owner_id: int,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        start_at_utc: datetime | None = None,
        end_at_utc: datetime | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[NutritionLog]:
        query = self.session.query(NutritionLog).filter(
            NutritionLog.owner_id == owner_id
        )
        if start_date:
            query = query.filter(NutritionLog.user_local_date >= start_date)
        if end_date:
            query = query.filter(NutritionLog.user_local_date <= end_date)
        if start_at_utc:
            query = query.filter(NutritionLog.logged_at_utc >= start_at_utc)
        if end_at_utc:
            query = query.filter(NutritionLog.logged_at_utc <= end_at_utc)
        if status:
            query = query.filter(NutritionLog.status == status)
        return (
            query.order_by(NutritionLog.logged_at_utc.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

    def confirm_nutrition_log(
        self,
        owner_id: int,
        record_id: int,
        version: int,
    ) -> NutritionLog:
        log = self.get_nutrition_log(owner_id, record_id)
        if log.version != version:
            raise ConcurrentUpdate()
        if not log.items:
            raise DomainError(
                "Add estimated or manual nutrition items before confirming."
            )
        if log.clarification_question:
            raise DomainError(
                "Resolve the clarification or edit values before confirming."
            )
        log.status = "confirmed"
        log.confirmed_by_user = True
        log.version += 1
        self.session.flush()
        return log

    def save_unestimated_nutrition_log(
        self,
        owner_id: int,
        record_id: int,
        version: int,
    ) -> NutritionLog:
        log = self.get_nutrition_log(owner_id, record_id)
        if log.version != version:
            raise ConcurrentUpdate()
        log.status = "unestimated"
        log.estimation_source = "unestimated"
        log.clarification_question = None
        log.version += 1
        self.session.flush()
        return log

    def update_nutrition_item(
        self,
        owner_id: int,
        log_id: int,
        item_id: int,
        data: NutritionItemUpdate,
    ) -> NutritionLog:
        log = self.get_nutrition_log(owner_id, log_id)
        item = (
            self.session.query(NutritionItem)
            .filter(
                NutritionItem.id == item_id,
                NutritionItem.nutrition_log_id == log_id,
                NutritionItem.owner_id == owner_id,
            )
            .one_or_none()
        )
        if item is None:
            raise RecordNotFound()
        values = data.model_dump(exclude={"version"}, exclude_unset=True)
        values["user_modified"] = True
        self._versioned_update(
            NutritionItem,
            owner_id,
            item_id,
            data.version,
            values,
        )
        log.user_modified = True
        log.confirmed_by_user = True
        log.clarification_question = None
        log.version += 1
        self._recalculate_nutrition_totals(log)
        self.session.flush()
        return log

    def get_nutrition_item(
        self,
        owner_id: int,
        log_id: int,
        item_id: int,
    ) -> NutritionItem:
        item = (
            self.session.query(NutritionItem)
            .filter(
                NutritionItem.id == item_id,
                NutritionItem.nutrition_log_id == log_id,
                NutritionItem.owner_id == owner_id,
            )
            .one_or_none()
        )
        if item is None:
            raise RecordNotFound()
        return item

    def delete_nutrition_item(
        self,
        owner_id: int,
        log_id: int,
        item_id: int,
    ) -> NutritionLog:
        log = self.get_nutrition_log(owner_id, log_id)
        deleted = (
            self.session.query(NutritionItem)
            .filter(
                NutritionItem.id == item_id,
                NutritionItem.nutrition_log_id == log_id,
                NutritionItem.owner_id == owner_id,
            )
            .delete(synchronize_session=False)
        )
        if deleted == 0:
            raise RecordNotFound()
        self.session.flush()
        self._recalculate_nutrition_totals(log)
        if not log.items:
            log.status = "unestimated"
            log.estimation_source = "unestimated"
        log.user_modified = True
        log.version += 1
        self.session.flush()
        return log

    def delete_nutrition_log(self, owner_id: int, record_id: int) -> None:
        self._delete_owned(self.session, NutritionLog, owner_id, record_id)
        self._clear_agent_reference(
            self.session,
            owner_id,
            "nutrition_log",
            record_id,
        )

    def summarize_nutrition(
        self,
        owner_id: int,
        start_date: date,
        end_date: date,
    ) -> dict[str, Any]:
        if end_date < start_date:
            raise DomainError("end_date cannot be before start_date.")
        logs = (
            self.session.query(NutritionLog)
            .filter(
                NutritionLog.owner_id == owner_id,
                NutritionLog.user_local_date >= start_date,
                NutritionLog.user_local_date <= end_date,
                NutritionLog.status.in_(("confirmed", "unestimated")),
            )
            .all()
        )
        confirmed = [log for log in logs if log.status == "confirmed"]
        days = Decimal((end_date - start_date).days + 1)
        calories = sum((log.total_calories for log in confirmed), Decimal("0"))
        protein = sum((log.total_protein_grams for log in confirmed), Decimal("0"))
        carbohydrate = sum(
            (log.total_carbohydrate_grams or Decimal("0") for log in confirmed),
            Decimal("0"),
        )
        fat = sum(
            (log.total_fat_grams or Decimal("0") for log in confirmed),
            Decimal("0"),
        )
        preferences = self.get_nutrition_preferences(owner_id)
        return {
            "start_date": start_date,
            "end_date": end_date,
            "confirmed_meals": len(confirmed),
            "unestimated_meals": len(logs) - len(confirmed),
            "total_calories": calories,
            "total_protein_grams": protein,
            "total_carbohydrate_grams": carbohydrate,
            "total_fat_grams": fat,
            "average_daily_calories": calories / days,
            "average_daily_protein_grams": protein / days,
            "calorie_target": preferences.calorie_target,
            "protein_target_grams": preferences.protein_target_grams,
        }
