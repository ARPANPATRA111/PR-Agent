"""Best-effort cleanup of processed Telegram messages."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from typing import Callable, Protocol

import httpx
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from bot import TelegramClient
from domain.scheduling import as_utc
from durable_worker import DeliveryFailure
from public_models import PublicUser, TelegramMessage

logger = logging.getLogger(__name__)
UTC = timezone.utc


class CleanupGateway(Protocol):
    async def delete(self, chat_id: int, message_id: int) -> None: ...


class TelegramCleanupGateway:
    def __init__(self, token: str):
        self.client = TelegramClient(token)

    async def delete(self, chat_id: int, message_id: int) -> None:
        try:
            result = await self.client.delete_message(chat_id, message_id)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise DeliveryFailure("telegram_cleanup_timeout") from exc
        if result.get("ok"):
            return
        code = int(result.get("error_code") or 500)
        description = str(result.get("description") or "").lower()
        if code == 400 and "message to delete not found" in description:
            return
        raise DeliveryFailure(
            f"telegram_cleanup_{code}",
            permanent=code in {400, 401, 403, 404},
        )


def queue_telegram_message(
    session: Session,
    *,
    telegram_id: int,
    chat_id: int,
    message_id: int,
    direction: str,
    purpose: str,
    processed_at: datetime,
    delete_after: datetime,
) -> TelegramMessage | None:
    """Store identifiers only; message text and model output are never retained."""
    owner = (
        session.query(PublicUser)
        .filter(PublicUser.telegram_id == telegram_id)
        .one_or_none()
    )
    if owner is None:
        return None
    existing = (
        session.query(TelegramMessage)
        .filter(
            TelegramMessage.telegram_chat_id == chat_id,
            TelegramMessage.telegram_message_id == message_id,
        )
        .one_or_none()
    )
    if existing is not None:
        if existing.deleted_at_utc is None:
            existing.processed_at_utc = processed_at
            existing.delete_after_utc = delete_after
        return existing
    record = TelegramMessage(
        owner_id=owner.id,
        telegram_chat_id=chat_id,
        telegram_message_id=message_id,
        direction=direction,
        purpose=purpose[:32],
        processed_at_utc=processed_at,
        delete_after_utc=delete_after,
        cleanup_status="pending",
    )
    session.add(record)
    session.flush()
    return record


@dataclass(frozen=True)
class CleanupClaim:
    record_id: int
    chat_id: int
    message_id: int
    attempt_count: int


class TelegramCleanupStore:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        *,
        batch_size: int = 25,
        lease_seconds: int = 120,
        max_attempts: int = 5,
        base_backoff_seconds: int = 30,
    ):
        self.session_factory = session_factory
        self.batch_size = batch_size
        self.lease_seconds = lease_seconds
        self.max_attempts = max_attempts
        self.base_backoff_seconds = base_backoff_seconds

    def claim(self, now: datetime) -> list[CleanupClaim]:
        now = as_utc(now)
        session = self.session_factory()
        try:
            with session.begin():
                terminal = (
                    session.query(TelegramMessage)
                    .filter(
                        TelegramMessage.cleanup_status == "claimed",
                        TelegramMessage.cleanup_lease_expires_at_utc <= now,
                        TelegramMessage.cleanup_attempt_count >= self.max_attempts,
                    )
                    .with_for_update(skip_locked=True)
                    .limit(self.batch_size)
                    .all()
                )
                for record in terminal:
                    record.cleanup_status = "dead_letter"
                    record.cleanup_error_category = "cleanup_lease_expired"
                    record.cleanup_lease_expires_at_utc = None

                eligible = or_(
                    and_(
                        TelegramMessage.cleanup_status.in_(["pending", "failed"]),
                        TelegramMessage.delete_after_utc <= now,
                        or_(
                            TelegramMessage.next_cleanup_attempt_at_utc.is_(None),
                            TelegramMessage.next_cleanup_attempt_at_utc <= now,
                        ),
                    ),
                    and_(
                        TelegramMessage.cleanup_status == "claimed",
                        TelegramMessage.cleanup_lease_expires_at_utc <= now,
                    ),
                )
                rows = (
                    session.query(TelegramMessage)
                    .filter(
                        eligible,
                        TelegramMessage.cleanup_attempt_count < self.max_attempts,
                    )
                    .order_by(
                        TelegramMessage.next_cleanup_attempt_at_utc,
                        TelegramMessage.id,
                    )
                    .with_for_update(skip_locked=True)
                    .limit(self.batch_size)
                    .all()
                )
                claims = []
                for record in rows:
                    record.cleanup_status = "claimed"
                    record.cleanup_attempt_count += 1
                    record.cleanup_claimed_at_utc = now
                    record.cleanup_lease_expires_at_utc = now + timedelta(
                        seconds=self.lease_seconds
                    )
                    record.next_cleanup_attempt_at_utc = None
                    claims.append(
                        CleanupClaim(
                            record_id=record.id,
                            chat_id=record.telegram_chat_id,
                            message_id=record.telegram_message_id,
                            attempt_count=record.cleanup_attempt_count,
                        )
                    )
            return claims
        finally:
            session.close()

    def mark_deleted(self, record_id: int, now: datetime) -> None:
        session = self.session_factory()
        try:
            with session.begin():
                record = session.get(TelegramMessage, record_id)
                if record is None or record.cleanup_status != "claimed":
                    return
                record.cleanup_status = "deleted"
                record.deleted_at_utc = as_utc(now)
                record.cleanup_lease_expires_at_utc = None
                record.cleanup_error_category = None
        finally:
            session.close()

    def mark_failed(
        self,
        record_id: int,
        now: datetime,
        failure: DeliveryFailure,
    ) -> None:
        session = self.session_factory()
        try:
            with session.begin():
                record = session.get(TelegramMessage, record_id)
                if record is None or record.cleanup_status != "claimed":
                    return
                terminal = (
                    failure.permanent
                    or record.cleanup_attempt_count >= self.max_attempts
                )
                record.cleanup_status = "dead_letter" if terminal else "failed"
                record.cleanup_error_category = failure.category
                record.cleanup_lease_expires_at_utc = None
                if terminal:
                    record.next_cleanup_attempt_at_utc = None
                else:
                    exponent = max(
                        0,
                        min(record.cleanup_attempt_count - 1, 8),
                    )
                    record.next_cleanup_attempt_at_utc = now + timedelta(
                        seconds=self.base_backoff_seconds * (2**exponent)
                    )
        finally:
            session.close()


class TelegramCleanupWorker:
    def __init__(
        self,
        store: TelegramCleanupStore,
        gateway: CleanupGateway,
        *,
        clock: Callable[[], datetime] | None = None,
    ):
        self.store = store
        self.gateway = gateway
        self.clock = clock or (lambda: datetime.now(UTC))

    async def run_once(self) -> int:
        claims = await asyncio.to_thread(self.store.claim, self.clock())
        await asyncio.gather(*(self._delete(claim) for claim in claims))
        return len(claims)

    async def _delete(self, claim: CleanupClaim) -> None:
        try:
            await self.gateway.delete(claim.chat_id, claim.message_id)
        except DeliveryFailure as failure:
            await asyncio.to_thread(
                self.store.mark_failed,
                claim.record_id,
                self.clock(),
                failure,
            )
        except Exception:
            logger.exception("Unexpected Telegram cleanup failure")
            await asyncio.to_thread(
                self.store.mark_failed,
                claim.record_id,
                self.clock(),
                DeliveryFailure("unexpected_cleanup_error"),
            )
        else:
            await asyncio.to_thread(
                self.store.mark_deleted,
                claim.record_id,
                self.clock(),
            )
