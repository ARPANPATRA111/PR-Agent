"""Additive public-v2 persistence model.

Legacy ORM tables remain in ``memory.py`` until the beta migration has been
verified. Production schema changes for these models are owned by Alembic.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import declarative_base, relationship


NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

PublicBase = declarative_base(
    metadata=MetaData(naming_convention=NAMING_CONVENTION)
)


def utc_timestamp():
    return func.now()


class TimestampMixin:
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=utc_timestamp(),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=utc_timestamp(),
        onupdate=utc_timestamp(),
    )
    version = Column(
        Integer,
        nullable=False,
        server_default="1",
    )


class PublicUser(PublicBase):
    """Public identity row, backfilled additively from legacy users."""

    __tablename__ = "app_users"

    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, nullable=False, unique=True, index=True)
    username = Column(String(255), nullable=True)
    first_name = Column(String(255), nullable=False)
    last_name = Column(String(255), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=utc_timestamp(),
    )
    last_active = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=utc_timestamp(),
    )
    streak = Column(Integer, nullable=False, server_default="0")
    total_entries = Column(Integer, nullable=False, server_default="0")
    preferences = Column(JSON, nullable=False, server_default="{}")


class UserPreference(PublicBase, TimestampMixin):
    __tablename__ = "user_preferences"

    owner_id = Column(
        Integer,
        ForeignKey("app_users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    timezone = Column(String(64), nullable=False, server_default="UTC")
    locale = Column(String(16), nullable=True)
    sunday_digest_enabled = Column(
        Boolean,
        nullable=False,
        server_default="false",
    )
    calorie_target = Column(Numeric(12, 2), nullable=True)
    protein_target_grams = Column(Numeric(12, 3), nullable=True)
    carbohydrate_target_grams = Column(Numeric(12, 3), nullable=True)
    fat_target_grams = Column(Numeric(12, 3), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "calorie_target IS NULL OR calorie_target >= 0",
            name="calorie_target_nonnegative",
        ),
        CheckConstraint(
            "protein_target_grams IS NULL OR protein_target_grams >= 0",
            name="protein_target_nonnegative",
        ),
        CheckConstraint(
            "carbohydrate_target_grams IS NULL OR carbohydrate_target_grams >= 0",
            name="carbohydrate_target_nonnegative",
        ),
        CheckConstraint(
            "fat_target_grams IS NULL OR fat_target_grams >= 0",
            name="fat_target_nonnegative",
        ),
    )


class WorkLog(PublicBase, TimestampMixin):
    __tablename__ = "work_logs"

    id = Column(Integer, primary_key=True)
    owner_id = Column(
        Integer,
        ForeignKey("app_users.id", ondelete="CASCADE"),
        nullable=False,
    )
    original_text = Column(Text, nullable=False)
    cleaned_text = Column(Text, nullable=True)
    category = Column(String(64), nullable=True)
    tags = Column(JSON, nullable=False, default=list, server_default="[]")
    logged_at_utc = Column(DateTime(timezone=True), nullable=False)
    user_local_date = Column(Date, nullable=False)
    timezone = Column(String(64), nullable=False)
    capture_source = Column(String(32), nullable=False)
    voice_file_id = Column(String(255), nullable=True)
    legacy_raw_entry_id = Column(Integer, nullable=True, unique=True)
    idempotency_key = Column(String(128), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "idempotency_key",
            name="uq_work_logs_owner_id_idempotency_key",
        ),
        Index(
            "ix_work_logs_owner_id_logged_at_utc",
            "owner_id",
            "logged_at_utc",
        ),
        Index(
            "ix_work_logs_owner_id_user_local_date",
            "owner_id",
            "user_local_date",
        ),
        Index(
            "ix_work_logs_owner_id_category",
            "owner_id",
            "category",
        ),
    )


class Note(PublicBase, TimestampMixin):
    __tablename__ = "notes"

    id = Column(Integer, primary_key=True)
    owner_id = Column(
        Integer,
        ForeignKey("app_users.id", ondelete="CASCADE"),
        nullable=False,
    )
    title = Column(String(255), nullable=False)
    body = Column(Text, nullable=False)
    tags = Column(JSON, nullable=False, default=list, server_default="[]")
    pinned = Column(Boolean, nullable=False, server_default="false")
    capture_source = Column(String(32), nullable=False)
    idempotency_key = Column(String(128), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "idempotency_key",
            name="uq_notes_owner_id_idempotency_key",
        ),
        Index("ix_notes_owner_id_pinned", "owner_id", "pinned"),
        Index("ix_notes_owner_id_updated_at", "owner_id", "updated_at"),
    )


class Reminder(PublicBase, TimestampMixin):
    __tablename__ = "reminders"

    id = Column(Integer, primary_key=True)
    owner_id = Column(
        Integer,
        ForeignKey("app_users.id", ondelete="CASCADE"),
        nullable=False,
    )
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    timezone = Column(String(64), nullable=False)
    schedule_type = Column(String(16), nullable=False)
    scheduled_local_time = Column(String(8), nullable=True)
    next_run_at_utc = Column(DateTime(timezone=True), nullable=True)
    recurrence_rule = Column(JSON, nullable=True)
    enabled = Column(Boolean, nullable=False, server_default="true")
    last_run_at_utc = Column(DateTime(timezone=True), nullable=True)
    last_success_at_utc = Column(DateTime(timezone=True), nullable=True)
    retry_count = Column(Integer, nullable=False, server_default="0")
    last_error_category = Column(String(64), nullable=True)
    idempotency_key = Column(String(128), nullable=True)

    deliveries = relationship(
        "ReminderDelivery",
        back_populates="reminder",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        CheckConstraint(
            "schedule_type IN ('once', 'daily', 'weekly')",
            name="schedule_type_supported",
        ),
        CheckConstraint("retry_count >= 0", name="retry_count_nonnegative"),
        UniqueConstraint(
            "owner_id",
            "idempotency_key",
            name="uq_reminders_owner_id_idempotency_key",
        ),
        Index(
            "ix_reminders_owner_id_enabled_next_run_at_utc",
            "owner_id",
            "enabled",
            "next_run_at_utc",
        ),
    )


class ReminderDelivery(PublicBase, TimestampMixin):
    __tablename__ = "reminder_deliveries"

    id = Column(Integer, primary_key=True)
    owner_id = Column(
        Integer,
        ForeignKey("app_users.id", ondelete="CASCADE"),
        nullable=False,
    )
    reminder_id = Column(
        Integer,
        ForeignKey("reminders.id", ondelete="CASCADE"),
        nullable=False,
    )
    scheduled_occurrence_at_utc = Column(
        DateTime(timezone=True),
        nullable=False,
    )
    idempotency_key = Column(String(160), nullable=False, unique=True)
    status = Column(String(24), nullable=False, server_default="pending")
    attempt_count = Column(Integer, nullable=False, server_default="0")
    delivered_at_utc = Column(DateTime(timezone=True), nullable=True)
    last_error_category = Column(String(64), nullable=True)

    reminder = relationship("Reminder", back_populates="deliveries")

    __table_args__ = (
        UniqueConstraint(
            "reminder_id",
            "scheduled_occurrence_at_utc",
            name="uq_reminder_delivery_occurrence",
        ),
        CheckConstraint(
            "status IN ('pending', 'claimed', 'sent', 'failed', 'cancelled')",
            name="status_supported",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="attempt_count_nonnegative",
        ),
        Index(
            "ix_reminder_deliveries_owner_id_status",
            "owner_id",
            "status",
        ),
    )


class LedgerEntry(PublicBase, TimestampMixin):
    __tablename__ = "ledger_entries"

    id = Column(Integer, primary_key=True)
    owner_id = Column(
        Integer,
        ForeignKey("app_users.id", ondelete="CASCADE"),
        nullable=False,
    )
    direction = Column(String(8), nullable=False)
    amount_minor = Column(BigInteger, nullable=False)
    currency = Column(String(3), nullable=False)
    category = Column(String(64), nullable=True)
    description = Column(Text, nullable=False)
    transaction_at_utc = Column(DateTime(timezone=True), nullable=False)
    user_local_date = Column(Date, nullable=False)
    timezone = Column(String(64), nullable=False)
    capture_source = Column(String(32), nullable=False)
    idempotency_key = Column(String(128), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "direction IN ('expense', 'income')",
            name="direction_supported",
        ),
        CheckConstraint("amount_minor > 0", name="amount_positive"),
        CheckConstraint(
            "currency = UPPER(currency) AND length(currency) = 3",
            name="currency_iso_format",
        ),
        UniqueConstraint(
            "owner_id",
            "idempotency_key",
            name="uq_ledger_entries_owner_id_idempotency_key",
        ),
        Index(
            "ix_ledger_entries_owner_id_transaction_at_utc",
            "owner_id",
            "transaction_at_utc",
        ),
        Index(
            "ix_ledger_entries_owner_id_user_local_date_currency",
            "owner_id",
            "user_local_date",
            "currency",
        ),
        Index(
            "ix_ledger_entries_owner_id_category",
            "owner_id",
            "category",
        ),
    )


class NutritionLog(PublicBase, TimestampMixin):
    __tablename__ = "nutrition_logs"

    id = Column(Integer, primary_key=True)
    owner_id = Column(
        Integer,
        ForeignKey("app_users.id", ondelete="CASCADE"),
        nullable=False,
    )
    meal_name = Column(String(128), nullable=True)
    logged_at_utc = Column(DateTime(timezone=True), nullable=False)
    user_local_date = Column(Date, nullable=False)
    timezone = Column(String(64), nullable=False)
    original_text = Column(Text, nullable=False)
    total_calories = Column(Numeric(12, 2), nullable=False, server_default="0")
    total_protein_grams = Column(
        Numeric(12, 3),
        nullable=False,
        server_default="0",
    )
    total_carbohydrate_grams = Column(Numeric(12, 3), nullable=True)
    total_fat_grams = Column(Numeric(12, 3), nullable=True)
    estimation_source = Column(String(64), nullable=False)
    overall_confidence = Column(Numeric(5, 4), nullable=True)
    confirmed_by_user = Column(Boolean, nullable=False, server_default="false")
    user_modified = Column(Boolean, nullable=False, server_default="false")
    idempotency_key = Column(String(128), nullable=True)

    items = relationship(
        "NutritionItem",
        back_populates="nutrition_log",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        CheckConstraint("total_calories >= 0", name="calories_nonnegative"),
        CheckConstraint(
            "total_protein_grams >= 0",
            name="protein_nonnegative",
        ),
        CheckConstraint(
            "total_carbohydrate_grams IS NULL OR total_carbohydrate_grams >= 0",
            name="carbohydrate_nonnegative",
        ),
        CheckConstraint(
            "total_fat_grams IS NULL OR total_fat_grams >= 0",
            name="fat_nonnegative",
        ),
        CheckConstraint(
            "overall_confidence IS NULL OR "
            "(overall_confidence >= 0 AND overall_confidence <= 1)",
            name="confidence_range",
        ),
        UniqueConstraint(
            "owner_id",
            "idempotency_key",
            name="uq_nutrition_logs_owner_id_idempotency_key",
        ),
        Index(
            "ix_nutrition_logs_owner_id_logged_at_utc",
            "owner_id",
            "logged_at_utc",
        ),
        Index(
            "ix_nutrition_logs_owner_id_user_local_date",
            "owner_id",
            "user_local_date",
        ),
    )


class NutritionItem(PublicBase, TimestampMixin):
    __tablename__ = "nutrition_items"

    id = Column(Integer, primary_key=True)
    nutrition_log_id = Column(
        Integer,
        ForeignKey("nutrition_logs.id", ondelete="CASCADE"),
        nullable=False,
    )
    owner_id = Column(
        Integer,
        ForeignKey("app_users.id", ondelete="CASCADE"),
        nullable=False,
    )
    original_item_text = Column(Text, nullable=False)
    normalized_name = Column(String(255), nullable=False)
    quantity_value = Column(Numeric(12, 3), nullable=True)
    quantity_unit = Column(String(32), nullable=True)
    portion_description = Column(String(255), nullable=True)
    estimated_grams = Column(Numeric(12, 3), nullable=True)
    calories = Column(Numeric(12, 2), nullable=False)
    protein_grams = Column(Numeric(12, 3), nullable=False)
    carbohydrate_grams = Column(Numeric(12, 3), nullable=True)
    fat_grams = Column(Numeric(12, 3), nullable=True)
    estimation_source = Column(String(64), nullable=False)
    confidence = Column(Numeric(5, 4), nullable=True)
    user_modified = Column(Boolean, nullable=False, server_default="false")

    nutrition_log = relationship("NutritionLog", back_populates="items")

    __table_args__ = (
        CheckConstraint(
            "quantity_value IS NULL OR quantity_value > 0",
            name="quantity_positive",
        ),
        CheckConstraint(
            "estimated_grams IS NULL OR estimated_grams >= 0",
            name="estimated_grams_nonnegative",
        ),
        CheckConstraint("calories >= 0", name="calories_nonnegative"),
        CheckConstraint("protein_grams >= 0", name="protein_nonnegative"),
        CheckConstraint(
            "carbohydrate_grams IS NULL OR carbohydrate_grams >= 0",
            name="carbohydrate_nonnegative",
        ),
        CheckConstraint(
            "fat_grams IS NULL OR fat_grams >= 0",
            name="fat_nonnegative",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="confidence_range",
        ),
        Index(
            "ix_nutrition_items_owner_id_nutrition_log_id",
            "owner_id",
            "nutrition_log_id",
        ),
    )


class TrackedGoal(PublicBase, TimestampMixin):
    # The legacy ``goals`` table is intentionally retained unchanged.
    __tablename__ = "tracked_goals"

    id = Column(Integer, primary_key=True)
    owner_id = Column(
        Integer,
        ForeignKey("app_users.id", ondelete="CASCADE"),
        nullable=False,
    )
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    target_value = Column(Numeric(18, 4), nullable=True)
    current_value = Column(Numeric(18, 4), nullable=False, server_default="0")
    unit = Column(String(32), nullable=True)
    start_date = Column(Date, nullable=False)
    due_date = Column(Date, nullable=True)
    status = Column(String(16), nullable=False, server_default="active")
    idempotency_key = Column(String(128), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'paused', 'completed')",
            name="status_supported",
        ),
        CheckConstraint(
            "target_value IS NULL OR target_value >= 0",
            name="target_nonnegative",
        ),
        CheckConstraint(
            "current_value >= 0",
            name="current_nonnegative",
        ),
        CheckConstraint(
            "due_date IS NULL OR due_date >= start_date",
            name="due_date_after_start",
        ),
        UniqueConstraint(
            "owner_id",
            "idempotency_key",
            name="uq_tracked_goals_owner_id_idempotency_key",
        ),
        Index("ix_tracked_goals_owner_id_status", "owner_id", "status"),
        Index("ix_tracked_goals_owner_id_due_date", "owner_id", "due_date"),
    )


class TelegramMessage(PublicBase, TimestampMixin):
    __tablename__ = "telegram_messages"

    id = Column(Integer, primary_key=True)
    owner_id = Column(
        Integer,
        ForeignKey("app_users.id", ondelete="CASCADE"),
        nullable=False,
    )
    telegram_chat_id = Column(BigInteger, nullable=False)
    telegram_message_id = Column(BigInteger, nullable=False)
    direction = Column(String(8), nullable=False)
    purpose = Column(String(32), nullable=False)
    processed_at_utc = Column(DateTime(timezone=True), nullable=True)
    delete_after_utc = Column(DateTime(timezone=True), nullable=True)
    deleted_at_utc = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "telegram_chat_id",
            "telegram_message_id",
            name="uq_telegram_messages_chat_message",
        ),
        CheckConstraint(
            "direction IN ('inbound', 'outbound')",
            name="direction_supported",
        ),
        Index(
            "ix_telegram_messages_owner_id_delete_after_utc",
            "owner_id",
            "delete_after_utc",
        ),
    )


class ApplicationSession(PublicBase):
    __tablename__ = "sessions"

    id = Column(String(64), primary_key=True)
    owner_id = Column(
        Integer,
        ForeignKey("app_users.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash = Column(String(64), nullable=False, unique=True)
    expires_at_utc = Column(DateTime(timezone=True), nullable=False)
    revoked_at_utc = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=utc_timestamp(),
    )

    __table_args__ = (
        Index(
            "ix_sessions_owner_id_expires_at_utc",
            "owner_id",
            "expires_at_utc",
        ),
    )


class InviteCode(PublicBase, TimestampMixin):
    __tablename__ = "invite_codes"

    id = Column(Integer, primary_key=True)
    code_hash = Column(String(64), nullable=False, unique=True)
    created_by_owner_id = Column(
        Integer,
        ForeignKey("app_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    claimed_by_owner_id = Column(
        Integer,
        ForeignKey("app_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    expires_at_utc = Column(DateTime(timezone=True), nullable=True)
    claimed_at_utc = Column(DateTime(timezone=True), nullable=True)
    enabled = Column(Boolean, nullable=False, server_default="true")


class ScheduledDigest(PublicBase, TimestampMixin):
    __tablename__ = "scheduled_digests"

    id = Column(Integer, primary_key=True)
    owner_id = Column(
        Integer,
        ForeignKey("app_users.id", ondelete="CASCADE"),
        nullable=False,
    )
    timezone = Column(String(64), nullable=False)
    weekday = Column(Integer, nullable=False, server_default="6")
    scheduled_local_time = Column(String(8), nullable=False)
    next_run_at_utc = Column(DateTime(timezone=True), nullable=True)
    enabled = Column(Boolean, nullable=False, server_default="false")

    __table_args__ = (
        CheckConstraint(
            "weekday >= 0 AND weekday <= 6",
            name="weekday_range",
        ),
        UniqueConstraint("owner_id", name="uq_scheduled_digests_owner_id"),
        Index(
            "ix_scheduled_digests_owner_id_enabled_next_run_at_utc",
            "owner_id",
            "enabled",
            "next_run_at_utc",
        ),
    )


class DigestDelivery(PublicBase, TimestampMixin):
    __tablename__ = "digest_deliveries"

    id = Column(Integer, primary_key=True)
    owner_id = Column(
        Integer,
        ForeignKey("app_users.id", ondelete="CASCADE"),
        nullable=False,
    )
    digest_week_start = Column(Date, nullable=False)
    idempotency_key = Column(String(128), nullable=False, unique=True)
    status = Column(String(24), nullable=False, server_default="pending")
    delivered_at_utc = Column(DateTime(timezone=True), nullable=True)
    last_error_category = Column(String(64), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "digest_week_start",
            name="uq_digest_deliveries_owner_week",
        ),
        Index(
            "ix_digest_deliveries_owner_id_digest_week_start",
            "owner_id",
            "digest_week_start",
        ),
    )


class AccountExportRequest(PublicBase, TimestampMixin):
    __tablename__ = "account_export_requests"

    id = Column(Integer, primary_key=True)
    owner_id = Column(
        Integer,
        ForeignKey("app_users.id", ondelete="CASCADE"),
        nullable=False,
    )
    status = Column(String(24), nullable=False, server_default="pending")
    requested_at_utc = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=utc_timestamp(),
    )
    completed_at_utc = Column(DateTime(timezone=True), nullable=True)
    expires_at_utc = Column(DateTime(timezone=True), nullable=True)
    object_key = Column(String(512), nullable=True)
    last_error_category = Column(String(64), nullable=True)

    __table_args__ = (
        Index(
            "ix_account_export_requests_owner_id_requested_at_utc",
            "owner_id",
            "requested_at_utc",
        ),
    )


class ProcessedTelegramUpdate(PublicBase):
    __tablename__ = "telegram_update_receipts"

    id = Column(Integer, primary_key=True)
    update_id = Column(BigInteger, nullable=False, unique=True)
    status = Column(String(32), nullable=False, server_default="processing")
    received_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=utc_timestamp(),
    )
    completed_at = Column(DateTime(timezone=True), nullable=True)
    retry_count = Column(Integer, nullable=False, server_default="0")
    error_category = Column(String(64), nullable=True)


class RateLimitBucket(PublicBase):
    __tablename__ = "api_rate_limit_buckets"

    id = Column(Integer, primary_key=True)
    subject_key = Column(String(128), nullable=False)
    scope = Column(String(64), nullable=False)
    window_start = Column(DateTime(timezone=True), nullable=False)
    request_count = Column(Integer, nullable=False, server_default="0")
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=utc_timestamp(),
    )

    __table_args__ = (
        UniqueConstraint(
            "subject_key",
            "scope",
            "window_start",
            name="uq_rate_limit_subject_scope_window",
        ),
        Index(
            "ix_rate_limit_buckets_subject_key_scope_window_start",
            "subject_key",
            "scope",
            "window_start",
        ),
    )
