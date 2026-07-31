"""Database-backed beta access and per-owner quota controls."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import secrets

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from domain.errors import DomainError
from public_models import InviteCode, RateLimitBucket

UTC = timezone.utc


class BetaAccessRequired(DomainError):
    status_code = 403
    public_message = "Beta access is required."


class InvalidInvite(DomainError):
    status_code = 403
    public_message = "The invite code is invalid, expired, or already claimed."


class QuotaExceeded(DomainError):
    status_code = 429
    public_message = "This usage limit has been reached. Try again later."


class InviteService:
    def __init__(self, session: Session):
        self.session = session

    @staticmethod
    def hash_code(code: str) -> str:
        return hashlib.sha256(code.strip().encode("utf-8")).hexdigest()

    def create(
        self,
        *,
        expires_at_utc: datetime | None = None,
        created_by_owner_id: int | None = None,
    ) -> tuple[InviteCode, str]:
        code = secrets.token_urlsafe(24)
        record = InviteCode(
            code_hash=self.hash_code(code),
            expires_at_utc=expires_at_utc,
            created_by_owner_id=created_by_owner_id,
            enabled=True,
        )
        self.session.add(record)
        self.session.flush()
        return record, code

    def claim(
        self,
        owner_id: int,
        code: str,
        *,
        now: datetime | None = None,
    ) -> InviteCode:
        current = now or datetime.now(UTC)
        record = (
            self.session.query(InviteCode)
            .filter(InviteCode.code_hash == self.hash_code(code))
            .with_for_update()
            .one_or_none()
        )
        if (
            record is None
            or not record.enabled
            or (
                record.expires_at_utc is not None
                and self._aware(record.expires_at_utc) <= current
            )
            or (
                record.claimed_by_owner_id is not None
                and record.claimed_by_owner_id != owner_id
            )
        ):
            raise InvalidInvite()
        record.claimed_by_owner_id = owner_id
        record.claimed_at_utc = current
        self.session.flush()
        return record

    def has_access(self, owner_id: int, *, now: datetime | None = None) -> bool:
        del now
        return (
            self.session.query(InviteCode.id)
            .filter(
                InviteCode.claimed_by_owner_id == owner_id,
                InviteCode.enabled.is_(True),
            )
            .first()
            is not None
        )

    @staticmethod
    def _aware(value: datetime) -> datetime:
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class QuotaService:
    """Consume integer units in UTC minute/day windows."""

    def __init__(self, session: Session):
        self.session = session

    def require(
        self,
        owner_id: int,
        scope: str,
        *,
        limit: int,
        units: int = 1,
        period: str = "day",
        now: datetime | None = None,
    ) -> int:
        if limit <= 0 or units <= 0:
            raise ValueError("Quota limit and units must be positive")
        current = now or datetime.now(UTC)
        window_start = (
            current.replace(second=0, microsecond=0)
            if period == "minute"
            else current.replace(hour=0, minute=0, second=0, microsecond=0)
        )
        subject_key = f"owner:{owner_id}"
        record = (
            self.session.query(RateLimitBucket)
            .filter(
                RateLimitBucket.subject_key == subject_key,
                RateLimitBucket.scope == scope,
                RateLimitBucket.window_start == window_start,
            )
            .with_for_update()
            .one_or_none()
        )
        if record is None:
            if units > limit:
                raise QuotaExceeded()
            record = RateLimitBucket(
                subject_key=subject_key,
                scope=scope,
                window_start=window_start,
                request_count=units,
                updated_at=current,
            )
            try:
                with self.session.begin_nested():
                    self.session.add(record)
                    self.session.flush()
                return limit - units
            except IntegrityError:
                record = (
                    self.session.query(RateLimitBucket)
                    .filter(
                        RateLimitBucket.subject_key == subject_key,
                        RateLimitBucket.scope == scope,
                        RateLimitBucket.window_start == window_start,
                    )
                    .with_for_update()
                    .one()
                )
        if record.request_count + units > limit:
            raise QuotaExceeded()
        record.request_count += units
        record.updated_at = current
        return limit - record.request_count


def invite_expiry(days: int) -> datetime:
    return datetime.now(UTC) + timedelta(days=days)
