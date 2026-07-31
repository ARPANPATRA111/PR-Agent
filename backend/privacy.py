"""Tenant-scoped export and account-deletion services."""

from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import hmac
import io
import json
import secrets
from typing import Any
import zipfile

from sqlalchemy import inspect, or_
from sqlalchemy.orm import Session

from domain.errors import RecordNotFound
from memory import (
    DailySummaryDB,
    GoalDB,
    LinkedInPostDB,
    NudgeLogDB,
    PostedReportDB,
    RawEntryDB,
    ReportFeedbackDB,
    SearchableEntryDB,
    SearchablePostDB,
    StructuredEntryDB,
    UserDB,
    WeeklySummaryDB,
)
from public_models import (
    AccountDeletionAudit,
    AccountExportRequest,
    ApplicationSession,
    DigestDelivery,
    LedgerEntry,
    Note,
    NutritionItem,
    NutritionLog,
    PublicUser,
    ProcessedTelegramUpdate,
    RateLimitBucket,
    Reminder,
    ScheduledDigest,
    TrackedGoal,
    UserPreference,
    WorkLog,
    TelegramMessage,
)

UTC = timezone.utc


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def _record(record, fields: tuple[str, ...]) -> dict[str, Any]:
    return {field: _json_value(getattr(record, field)) for field in fields}


class PrivacyService:
    def __init__(self, session: Session):
        self.session = session

    def export_owner_data(self, owner_id: int) -> dict[str, Any]:
        owner = (
            self.session.query(PublicUser)
            .filter(PublicUser.id == owner_id)
            .one_or_none()
        )
        if owner is None:
            raise RecordNotFound("User profile not found.")
        request = AccountExportRequest(
            owner_id=owner_id,
            status="pending",
            requested_at_utc=datetime.now(UTC),
        )
        self.session.add(request)
        self.session.flush()

        preference = (
            self.session.query(UserPreference)
            .filter(UserPreference.owner_id == owner_id)
            .one_or_none()
        )
        digest = (
            self.session.query(ScheduledDigest)
            .filter(ScheduledDigest.owner_id == owner_id)
            .one_or_none()
        )
        payload = {
            "exported_at_utc": datetime.now(UTC).isoformat(),
            "profile": _record(
                owner,
                (
                    "telegram_id",
                    "username",
                    "first_name",
                    "last_name",
                    "created_at",
                ),
            ),
            "preferences": (
                _record(
                    preference,
                    (
                        "timezone",
                        "locale",
                        "sunday_digest_enabled",
                        "calorie_target",
                        "protein_target_grams",
                        "carbohydrate_target_grams",
                        "fat_target_grams",
                        "default_milk_serving_ml",
                        "measurement_system",
                        "nutrition_confirmation_required",
                        "created_at",
                        "updated_at",
                    ),
                )
                if preference
                else {}
            ),
            "sunday_digest_schedule": (
                _record(
                    digest,
                    (
                        "timezone",
                        "weekday",
                        "scheduled_local_time",
                        "next_run_at_utc",
                        "enabled",
                    ),
                )
                if digest
                else {}
            ),
            "work_logs": [
                _record(
                    row,
                    (
                        "id",
                        "original_text",
                        "cleaned_text",
                        "category",
                        "tags",
                        "logged_at_utc",
                        "user_local_date",
                        "timezone",
                        "capture_source",
                        "created_at",
                        "updated_at",
                    ),
                )
                for row in self.session.query(WorkLog)
                .filter(WorkLog.owner_id == owner_id)
                .order_by(WorkLog.id)
            ],
            "notes": [
                _record(
                    row,
                    (
                        "id",
                        "title",
                        "body",
                        "tags",
                        "pinned",
                        "capture_source",
                        "created_at",
                        "updated_at",
                    ),
                )
                for row in self.session.query(Note)
                .filter(Note.owner_id == owner_id)
                .order_by(Note.id)
            ],
            "reminders": [
                _record(
                    row,
                    (
                        "id",
                        "title",
                        "description",
                        "timezone",
                        "schedule_type",
                        "scheduled_local_time",
                        "next_run_at_utc",
                        "recurrence_rule",
                        "enabled",
                        "last_success_at_utc",
                        "created_at",
                        "updated_at",
                    ),
                )
                for row in self.session.query(Reminder)
                .filter(Reminder.owner_id == owner_id)
                .order_by(Reminder.id)
            ],
            "ledger_entries": [
                _record(
                    row,
                    (
                        "id",
                        "direction",
                        "amount_minor",
                        "currency",
                        "category",
                        "description",
                        "transaction_at_utc",
                        "user_local_date",
                        "timezone",
                        "capture_source",
                        "created_at",
                        "updated_at",
                    ),
                )
                for row in self.session.query(LedgerEntry)
                .filter(LedgerEntry.owner_id == owner_id)
                .order_by(LedgerEntry.id)
            ],
            "nutrition_logs": [
                _record(
                    row,
                    (
                        "id",
                        "meal_name",
                        "logged_at_utc",
                        "user_local_date",
                        "timezone",
                        "original_text",
                        "status",
                        "visible_assumptions",
                        "total_calories",
                        "total_protein_grams",
                        "total_carbohydrate_grams",
                        "total_fat_grams",
                        "estimation_source",
                        "overall_confidence",
                        "confirmed_by_user",
                        "user_modified",
                        "created_at",
                        "updated_at",
                    ),
                )
                for row in self.session.query(NutritionLog)
                .filter(NutritionLog.owner_id == owner_id)
                .order_by(NutritionLog.id)
            ],
            "nutrition_items": [
                _record(
                    row,
                    (
                        "id",
                        "nutrition_log_id",
                        "original_item_text",
                        "normalized_name",
                        "quantity_value",
                        "quantity_unit",
                        "portion_description",
                        "visible_assumptions",
                        "estimated_grams",
                        "calories",
                        "protein_grams",
                        "carbohydrate_grams",
                        "fat_grams",
                        "estimation_source",
                        "confidence",
                        "user_modified",
                        "created_at",
                        "updated_at",
                    ),
                )
                for row in self.session.query(NutritionItem)
                .filter(NutritionItem.owner_id == owner_id)
                .order_by(NutritionItem.id)
            ],
            "goals": [
                _record(
                    row,
                    (
                        "id",
                        "title",
                        "description",
                        "target_value",
                        "current_value",
                        "unit",
                        "start_date",
                        "due_date",
                        "status",
                        "created_at",
                        "updated_at",
                    ),
                )
                for row in self.session.query(TrackedGoal)
                .filter(TrackedGoal.owner_id == owner_id)
                .order_by(TrackedGoal.id)
            ],
            "summary_metadata": [
                _record(
                    row,
                    (
                        "digest_week_start",
                        "status",
                        "delivered_at_utc",
                        "created_at",
                    ),
                )
                for row in self.session.query(DigestDelivery)
                .filter(DigestDelivery.owner_id == owner_id)
                .order_by(DigestDelivery.digest_week_start)
            ],
        }
        request.status = "completed"
        request.completed_at_utc = datetime.now(UTC)
        request.expires_at_utc = datetime.now(UTC) + timedelta(minutes=15)
        return payload

    @staticmethod
    def json_bytes(payload: dict[str, Any]) -> bytes:
        return json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            separators=(",", ": "),
        ).encode("utf-8")

    @staticmethod
    def csv_zip_bytes(payload: dict[str, Any]) -> bytes:
        archive_buffer = io.BytesIO()
        with zipfile.ZipFile(
            archive_buffer,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
        ) as archive:
            for name, value in payload.items():
                if name == "exported_at_utc":
                    continue
                rows = value if isinstance(value, list) else [value]
                rows = [row for row in rows if isinstance(row, dict)]
                if not rows:
                    continue
                fieldnames = list(rows[0].keys())
                text_buffer = io.StringIO(newline="")
                writer = csv.DictWriter(
                    text_buffer,
                    fieldnames=fieldnames,
                    extrasaction="ignore",
                )
                writer.writeheader()
                for row in rows:
                    writer.writerow(
                        {
                            key: (
                                json.dumps(item, ensure_ascii=False)
                                if isinstance(item, (list, dict))
                                else item
                            )
                            for key, item in row.items()
                        }
                    )
                archive.writestr(
                    f"{name}.csv",
                    text_buffer.getvalue().encode("utf-8-sig"),
                )
        return archive_buffer.getvalue()

    @staticmethod
    def identity_hash(telegram_id: int, audit_secret: str) -> str:
        return hmac.new(
            audit_secret.encode("utf-8"),
            f"telegram:{telegram_id}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def delete_account(
        self,
        owner_id: int,
        telegram_id: int,
        *,
        audit_secret: str,
    ) -> bool:
        identity_hash = self.identity_hash(telegram_id, audit_secret)
        existing_audit = (
            self.session.query(AccountDeletionAudit)
            .filter(AccountDeletionAudit.identity_hash == identity_hash)
            .one_or_none()
        )
        owner = (
            self.session.query(PublicUser)
            .filter(
                PublicUser.id == owner_id,
                PublicUser.telegram_id == telegram_id,
            )
            .with_for_update()
            .one_or_none()
        )
        if owner is None:
            if existing_audit is not None:
                return False
            raise RecordNotFound("User profile not found.")

        self.session.query(Reminder).filter(Reminder.owner_id == owner_id).update(
            {"enabled": False}, synchronize_session=False
        )
        self.session.query(ScheduledDigest).filter(
            ScheduledDigest.owner_id == owner_id
        ).update({"enabled": False}, synchronize_session=False)

        legacy_removed = self._delete_legacy_data(telegram_id)
        if existing_audit is None:
            audit = AccountDeletionAudit(
                deletion_id=secrets.token_urlsafe(24),
                identity_hash=identity_hash,
                legacy_rows_removed=legacy_removed,
            )
            self.session.add(audit)
        else:
            existing_audit.deletion_id = secrets.token_urlsafe(24)
            existing_audit.deleted_at_utc = datetime.now(UTC)
            existing_audit.legacy_rows_removed = legacy_removed
        deleted = (
            self.session.query(PublicUser)
            .filter(
                PublicUser.id == owner.id,
                PublicUser.telegram_id == telegram_id,
            )
            .delete(synchronize_session="fetch")
        )
        if deleted != 1:
            raise RecordNotFound("User profile not found.")
        self.session.flush()
        return True

    def _delete_legacy_data(self, telegram_id: int) -> int:
        tables = set(inspect(self.session.connection()).get_table_names())

        def owned_ids(model) -> list[int]:
            if model.__tablename__ not in tables:
                return []
            return [
                row[0]
                for row in self.session.query(model.id)
                .filter(model.telegram_id == telegram_id)
                .all()
            ]

        raw_ids = owned_ids(RawEntryDB)
        daily_ids = owned_ids(DailySummaryDB)
        weekly_ids = owned_ids(WeeklySummaryDB)
        post_ids = owned_ids(LinkedInPostDB)
        removed = 0
        feedback_filters = []
        if daily_ids:
            feedback_filters.append(
                (ReportFeedbackDB.report_type == "daily")
                & ReportFeedbackDB.report_id.in_(daily_ids)
            )
        if weekly_ids:
            feedback_filters.append(
                (ReportFeedbackDB.report_type == "weekly")
                & ReportFeedbackDB.report_id.in_(weekly_ids)
            )
        if post_ids:
            feedback_filters.append(
                (ReportFeedbackDB.report_type == "linkedin")
                & ReportFeedbackDB.report_id.in_(post_ids)
            )
        if feedback_filters and ReportFeedbackDB.__tablename__ in tables:
            removed += (
                self.session.query(ReportFeedbackDB)
                .filter(or_(*feedback_filters))
                .delete(synchronize_session=False)
            )
        if raw_ids and StructuredEntryDB.__tablename__ in tables:
            removed += (
                self.session.query(StructuredEntryDB)
                .filter(StructuredEntryDB.raw_entry_id.in_(raw_ids))
                .delete(synchronize_session=False)
            )
        for model in (SearchableEntryDB, SearchablePostDB):
            if model.__tablename__ not in tables:
                continue
            removed += (
                self.session.query(model)
                .filter(model.telegram_id == telegram_id)
                .delete(synchronize_session=False)
            )
        for model in (
            LinkedInPostDB,
            PostedReportDB,
            WeeklySummaryDB,
            DailySummaryDB,
            GoalDB,
            NudgeLogDB,
            RawEntryDB,
        ):
            if model.__tablename__ not in tables:
                continue
            removed += (
                self.session.query(model)
                .filter(model.telegram_id == telegram_id)
                .delete(synchronize_session=False)
            )
        if UserDB.__tablename__ in tables:
            removed += (
                self.session.query(UserDB)
                .filter(UserDB.telegram_id == telegram_id)
                .delete(synchronize_session=False)
            )
        return removed


def prune_operational_metadata(
    session: Session,
    *,
    now: datetime,
    retention_days: int,
) -> int:
    """Idempotently remove expired operational rows, never user records."""
    cutoff = now - timedelta(days=retention_days)
    removed = (
        session.query(AccountExportRequest)
        .filter(AccountExportRequest.expires_at_utc <= now)
        .delete(synchronize_session=False)
    )
    removed += (
        session.query(ApplicationSession)
        .filter(
            or_(
                ApplicationSession.expires_at_utc <= now,
                (
                    ApplicationSession.revoked_at_utc.is_not(None)
                    & (ApplicationSession.revoked_at_utc <= cutoff)
                ),
            )
        )
        .delete(synchronize_session=False)
    )
    removed += (
        session.query(TelegramMessage)
        .filter(
            TelegramMessage.cleanup_status.in_(["deleted", "dead_letter", "cancelled"]),
            TelegramMessage.updated_at <= cutoff,
        )
        .delete(synchronize_session=False)
    )
    removed += (
        session.query(ProcessedTelegramUpdate)
        .filter(
            ProcessedTelegramUpdate.status != "processing",
            ProcessedTelegramUpdate.received_at <= cutoff,
        )
        .delete(synchronize_session=False)
    )
    removed += (
        session.query(RateLimitBucket)
        .filter(RateLimitBucket.window_start <= now - timedelta(days=2))
        .delete(synchronize_session=False)
    )
    return removed
