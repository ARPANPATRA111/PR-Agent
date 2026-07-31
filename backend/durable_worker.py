"""PostgreSQL-backed reminder and Sunday-digest delivery worker."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from html import escape
import logging
from typing import Awaitable, Callable, Protocol
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from bot import TelegramClient
from domain.scheduling import (
    as_utc,
    next_reminder_occurrence,
    next_weekly_occurrence,
)
from public_models import (
    DigestDelivery,
    LedgerEntry,
    Note,
    NutritionLog,
    PublicUser,
    Reminder,
    ReminderDelivery,
    ScheduledDigest,
    TrackedGoal,
    WorkLog,
)

logger = logging.getLogger(__name__)
UTC = timezone.utc


class DeliveryFailure(Exception):
    def __init__(self, category: str, *, permanent: bool = False):
        super().__init__(category)
        self.category = category[:64]
        self.permanent = permanent


class MessageGateway(Protocol):
    async def send(self, chat_id: int, text: str) -> int | None: ...


class DigestNarrator(Protocol):
    async def narrate(self, snapshot: dict, fallback: str) -> str: ...


class TelegramMessageGateway:
    """Classify Telegram failures without exposing token details to the worker."""

    def __init__(self, token: str):
        self.client = TelegramClient(token)

    async def send(self, chat_id: int, text: str) -> int | None:
        try:
            result = await self.client.send_message(chat_id, text)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise DeliveryFailure("telegram_timeout") from exc
        if result.get("ok"):
            message = result.get("result") or {}
            message_id = message.get("message_id")
            return int(message_id) if message_id is not None else None
        code = int(result.get("error_code") or 500)
        category = f"telegram_{code}"
        raise DeliveryFailure(
            category,
            permanent=code in {400, 401, 403, 404},
        )


@dataclass(frozen=True)
class ReminderClaim:
    delivery_id: int
    reminder_id: int
    owner_id: int
    chat_id: int
    title: str
    description: str | None
    attempt_count: int


@dataclass(frozen=True)
class DigestClaim:
    delivery_id: int
    owner_id: int
    chat_id: int
    digest_week_start: date
    attempt_count: int
    message_text: str | None


def _message_id(value: int | None) -> int | None:
    return int(value) if value is not None else None


class DurableDeliveryStore:
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

    def _lease_until(self, now: datetime) -> datetime:
        return now + timedelta(seconds=self.lease_seconds)

    def _retry_at(self, now: datetime, attempt_count: int) -> datetime:
        exponent = max(0, min(attempt_count - 1, 8))
        return now + timedelta(seconds=self.base_backoff_seconds * (2**exponent))

    def claim_reminders(self, now: datetime) -> list[ReminderClaim]:
        now = as_utc(now)
        claims: list[ReminderClaim] = []
        session = self.session_factory()
        try:
            with session.begin():
                due = (
                    session.query(Reminder)
                    .filter(
                        Reminder.enabled.is_(True),
                        Reminder.next_run_at_utc.is_not(None),
                        Reminder.next_run_at_utc <= now,
                    )
                    .order_by(Reminder.next_run_at_utc, Reminder.id)
                    .with_for_update(skip_locked=True)
                    .limit(self.batch_size)
                    .all()
                )
                for reminder in due:
                    occurrence = as_utc(reminder.next_run_at_utc)
                    existing = (
                        session.query(ReminderDelivery.id)
                        .filter(
                            ReminderDelivery.reminder_id == reminder.id,
                            ReminderDelivery.scheduled_occurrence_at_utc == occurrence,
                        )
                        .first()
                    )
                    if existing is not None:
                        reminder.next_run_at_utc = next_reminder_occurrence(
                            reminder,
                            max(now, occurrence),
                        )
                        continue
                    delivery = ReminderDelivery(
                        owner_id=reminder.owner_id,
                        reminder_id=reminder.id,
                        scheduled_occurrence_at_utc=occurrence,
                        idempotency_key=(
                            f"reminder:{reminder.id}:{occurrence.isoformat()}"
                        ),
                        status="claimed",
                        attempt_count=1,
                        claimed_at_utc=now,
                        lease_expires_at_utc=self._lease_until(now),
                    )
                    session.add(delivery)
                    reminder.next_run_at_utc = next_reminder_occurrence(
                        reminder,
                        max(now, occurrence),
                    )
                    session.flush()
                    owner = session.get(PublicUser, reminder.owner_id)
                    if owner is not None:
                        claims.append(
                            ReminderClaim(
                                delivery_id=delivery.id,
                                reminder_id=reminder.id,
                                owner_id=reminder.owner_id,
                                chat_id=owner.telegram_id,
                                title=reminder.title,
                                description=reminder.description,
                                attempt_count=1,
                            )
                        )

                remaining = self.batch_size - len(claims)
                if remaining > 0:
                    expired_terminal = (
                        session.query(ReminderDelivery)
                        .join(
                            Reminder,
                            Reminder.id == ReminderDelivery.reminder_id,
                        )
                        .filter(
                            ReminderDelivery.status == "claimed",
                            ReminderDelivery.lease_expires_at_utc <= now,
                            ReminderDelivery.attempt_count >= self.max_attempts,
                        )
                        .with_for_update(skip_locked=True)
                        .limit(remaining)
                        .all()
                    )
                    for delivery in expired_terminal:
                        delivery.status = "dead_letter"
                        delivery.last_error_category = "claim_lease_expired"
                        delivery.lease_expires_at_utc = None
                        if delivery.reminder.schedule_type == "once":
                            delivery.reminder.enabled = False
                    eligible = or_(
                        and_(
                            ReminderDelivery.status.in_(["pending", "failed"]),
                            or_(
                                ReminderDelivery.next_attempt_at_utc.is_(None),
                                ReminderDelivery.next_attempt_at_utc <= now,
                            ),
                        ),
                        and_(
                            ReminderDelivery.status == "claimed",
                            ReminderDelivery.lease_expires_at_utc <= now,
                        ),
                    )
                    retries = (
                        session.query(ReminderDelivery)
                        .join(
                            Reminder,
                            Reminder.id == ReminderDelivery.reminder_id,
                        )
                        .filter(
                            eligible,
                            Reminder.enabled.is_(True),
                            ReminderDelivery.attempt_count < self.max_attempts,
                        )
                        .order_by(
                            ReminderDelivery.next_attempt_at_utc,
                            ReminderDelivery.id,
                        )
                        .with_for_update(skip_locked=True)
                        .limit(remaining)
                        .all()
                    )
                    for delivery in retries:
                        reminder = delivery.reminder
                        owner = session.get(PublicUser, delivery.owner_id)
                        if owner is None:
                            delivery.status = "cancelled"
                            continue
                        delivery.status = "claimed"
                        delivery.attempt_count += 1
                        delivery.claimed_at_utc = now
                        delivery.lease_expires_at_utc = self._lease_until(now)
                        delivery.next_attempt_at_utc = None
                        claims.append(
                            ReminderClaim(
                                delivery_id=delivery.id,
                                reminder_id=reminder.id,
                                owner_id=delivery.owner_id,
                                chat_id=owner.telegram_id,
                                title=reminder.title,
                                description=reminder.description,
                                attempt_count=delivery.attempt_count,
                            )
                        )
            return claims
        finally:
            session.close()

    def reminder_claim_is_active(self, delivery_id: int) -> bool:
        session = self.session_factory()
        try:
            return (
                session.query(ReminderDelivery.id)
                .join(Reminder, Reminder.id == ReminderDelivery.reminder_id)
                .filter(
                    ReminderDelivery.id == delivery_id,
                    ReminderDelivery.status == "claimed",
                    Reminder.enabled.is_(True),
                )
                .first()
                is not None
            )
        finally:
            session.close()

    def cancel_reminder_claim(self, delivery_id: int) -> None:
        session = self.session_factory()
        try:
            with session.begin():
                delivery = session.get(ReminderDelivery, delivery_id)
                if delivery is not None and delivery.status == "claimed":
                    delivery.status = "cancelled"
                    delivery.lease_expires_at_utc = None
        finally:
            session.close()

    def mark_reminder_success(
        self,
        delivery_id: int,
        now: datetime,
        telegram_message_id: int | None,
    ) -> None:
        session = self.session_factory()
        try:
            with session.begin():
                delivery = session.get(ReminderDelivery, delivery_id)
                if delivery is None or delivery.status != "claimed":
                    return
                delivery.status = "sent"
                delivery.delivered_at_utc = as_utc(now)
                delivery.telegram_message_id = _message_id(telegram_message_id)
                delivery.lease_expires_at_utc = None
                delivery.last_error_category = None
                reminder = session.get(Reminder, delivery.reminder_id)
                if reminder is not None:
                    reminder.last_run_at_utc = as_utc(now)
                    reminder.last_success_at_utc = as_utc(now)
                    reminder.retry_count = 0
                    reminder.last_error_category = None
                    if reminder.schedule_type == "once":
                        reminder.enabled = False
        finally:
            session.close()

    def mark_reminder_failure(
        self,
        delivery_id: int,
        now: datetime,
        failure: DeliveryFailure,
    ) -> None:
        session = self.session_factory()
        try:
            with session.begin():
                delivery = session.get(ReminderDelivery, delivery_id)
                if delivery is None or delivery.status != "claimed":
                    return
                terminal = (
                    failure.permanent or delivery.attempt_count >= self.max_attempts
                )
                delivery.status = "dead_letter" if terminal else "failed"
                delivery.last_error_category = failure.category
                delivery.lease_expires_at_utc = None
                delivery.next_attempt_at_utc = (
                    None if terminal else self._retry_at(now, delivery.attempt_count)
                )
                reminder = session.get(Reminder, delivery.reminder_id)
                if reminder is not None:
                    reminder.last_run_at_utc = as_utc(now)
                    reminder.retry_count = delivery.attempt_count
                    reminder.last_error_category = failure.category
                    if terminal and reminder.schedule_type == "once":
                        reminder.enabled = False
        finally:
            session.close()

    def claim_digests(self, now: datetime) -> list[DigestClaim]:
        now = as_utc(now)
        claims: list[DigestClaim] = []
        session = self.session_factory()
        try:
            with session.begin():
                due = (
                    session.query(ScheduledDigest)
                    .filter(
                        ScheduledDigest.enabled.is_(True),
                        ScheduledDigest.next_run_at_utc.is_not(None),
                        ScheduledDigest.next_run_at_utc <= now,
                    )
                    .order_by(
                        ScheduledDigest.next_run_at_utc,
                        ScheduledDigest.id,
                    )
                    .with_for_update(skip_locked=True)
                    .limit(self.batch_size)
                    .all()
                )
                for schedule in due:
                    occurrence = as_utc(schedule.next_run_at_utc)
                    local_date = occurrence.astimezone(
                        ZoneInfo(schedule.timezone)
                    ).date()
                    week_start = local_date - timedelta(days=6)
                    existing = (
                        session.query(DigestDelivery.id)
                        .filter(
                            DigestDelivery.owner_id == schedule.owner_id,
                            DigestDelivery.digest_week_start == week_start,
                        )
                        .first()
                    )
                    if existing is not None:
                        schedule.next_run_at_utc = next_weekly_occurrence(
                            timezone_name=schedule.timezone,
                            weekday=schedule.weekday,
                            scheduled_local_time=schedule.scheduled_local_time,
                            after_utc=max(now, occurrence),
                        )
                        continue
                    delivery = DigestDelivery(
                        owner_id=schedule.owner_id,
                        scheduled_digest_id=schedule.id,
                        scheduled_occurrence_at_utc=occurrence,
                        digest_week_start=week_start,
                        idempotency_key=(
                            f"digest:{schedule.owner_id}:{week_start.isoformat()}"
                        ),
                        status="claimed",
                        attempt_count=1,
                        claimed_at_utc=now,
                        lease_expires_at_utc=self._lease_until(now),
                    )
                    session.add(delivery)
                    schedule.next_run_at_utc = next_weekly_occurrence(
                        timezone_name=schedule.timezone,
                        weekday=schedule.weekday,
                        scheduled_local_time=schedule.scheduled_local_time,
                        after_utc=max(now, occurrence),
                    )
                    session.flush()
                    owner = session.get(PublicUser, schedule.owner_id)
                    if owner is not None:
                        claims.append(
                            DigestClaim(
                                delivery_id=delivery.id,
                                owner_id=schedule.owner_id,
                                chat_id=owner.telegram_id,
                                digest_week_start=week_start,
                                attempt_count=1,
                                message_text=None,
                            )
                        )

                remaining = self.batch_size - len(claims)
                if remaining > 0:
                    expired_terminal = (
                        session.query(DigestDelivery)
                        .filter(
                            DigestDelivery.status == "claimed",
                            DigestDelivery.lease_expires_at_utc <= now,
                            DigestDelivery.attempt_count >= self.max_attempts,
                        )
                        .with_for_update(skip_locked=True)
                        .limit(remaining)
                        .all()
                    )
                    for delivery in expired_terminal:
                        delivery.status = "dead_letter"
                        delivery.last_error_category = "claim_lease_expired"
                        delivery.lease_expires_at_utc = None
                    eligible = or_(
                        and_(
                            DigestDelivery.status.in_(["pending", "failed"]),
                            or_(
                                DigestDelivery.next_attempt_at_utc.is_(None),
                                DigestDelivery.next_attempt_at_utc <= now,
                            ),
                        ),
                        and_(
                            DigestDelivery.status == "claimed",
                            DigestDelivery.lease_expires_at_utc <= now,
                        ),
                    )
                    retries = (
                        session.query(DigestDelivery)
                        .join(
                            ScheduledDigest,
                            ScheduledDigest.id == DigestDelivery.scheduled_digest_id,
                        )
                        .filter(
                            eligible,
                            ScheduledDigest.enabled.is_(True),
                            DigestDelivery.attempt_count < self.max_attempts,
                        )
                        .order_by(
                            DigestDelivery.next_attempt_at_utc,
                            DigestDelivery.id,
                        )
                        .with_for_update(skip_locked=True)
                        .limit(remaining)
                        .all()
                    )
                    for delivery in retries:
                        owner = session.get(PublicUser, delivery.owner_id)
                        if owner is None:
                            delivery.status = "cancelled"
                            continue
                        delivery.status = "claimed"
                        delivery.attempt_count += 1
                        delivery.claimed_at_utc = now
                        delivery.lease_expires_at_utc = self._lease_until(now)
                        delivery.next_attempt_at_utc = None
                        claims.append(
                            DigestClaim(
                                delivery_id=delivery.id,
                                owner_id=delivery.owner_id,
                                chat_id=owner.telegram_id,
                                digest_week_start=delivery.digest_week_start,
                                attempt_count=delivery.attempt_count,
                                message_text=delivery.message_text,
                            )
                        )
            return claims
        finally:
            session.close()

    def digest_claim_is_active(self, delivery_id: int) -> bool:
        session = self.session_factory()
        try:
            return (
                session.query(DigestDelivery.id)
                .join(
                    ScheduledDigest,
                    ScheduledDigest.id == DigestDelivery.scheduled_digest_id,
                )
                .filter(
                    DigestDelivery.id == delivery_id,
                    DigestDelivery.status == "claimed",
                    ScheduledDigest.enabled.is_(True),
                )
                .first()
                is not None
            )
        finally:
            session.close()

    def cancel_digest_claim(self, delivery_id: int) -> None:
        session = self.session_factory()
        try:
            with session.begin():
                delivery = session.get(DigestDelivery, delivery_id)
                if delivery is not None and delivery.status == "claimed":
                    delivery.status = "cancelled"
                    delivery.lease_expires_at_utc = None
        finally:
            session.close()

    def build_digest_snapshot(
        self,
        owner_id: int,
        week_start: date,
    ) -> dict:
        session = self.session_factory()
        try:
            preference = (
                session.query(ScheduledDigest)
                .filter(ScheduledDigest.owner_id == owner_id)
                .one()
            )
            zone = ZoneInfo(preference.timezone)
            start_local = datetime.combine(
                week_start,
                datetime.min.time(),
                tzinfo=zone,
            )
            end_local = start_local + timedelta(days=7)
            start_utc = start_local.astimezone(UTC)
            end_utc = end_local.astimezone(UTC)
            work = (
                session.query(WorkLog)
                .filter(
                    WorkLog.owner_id == owner_id,
                    WorkLog.logged_at_utc >= start_utc,
                    WorkLog.logged_at_utc < end_utc,
                )
                .order_by(WorkLog.logged_at_utc)
                .all()
            )
            note_count = (
                session.query(func.count(Note.id))
                .filter(
                    Note.owner_id == owner_id,
                    Note.created_at >= start_utc,
                    Note.created_at < end_utc,
                )
                .scalar()
                or 0
            )
            goals_updated = (
                session.query(func.count(TrackedGoal.id))
                .filter(
                    TrackedGoal.owner_id == owner_id,
                    TrackedGoal.updated_at >= start_utc,
                    TrackedGoal.updated_at < end_utc,
                )
                .scalar()
                or 0
            )
            pending_reminders = (
                session.query(func.count(Reminder.id))
                .filter(
                    Reminder.owner_id == owner_id,
                    Reminder.enabled.is_(True),
                )
                .scalar()
                or 0
            )
            ledger_rows = (
                session.query(
                    LedgerEntry.currency,
                    LedgerEntry.direction,
                    func.sum(LedgerEntry.amount_minor),
                )
                .filter(
                    LedgerEntry.owner_id == owner_id,
                    LedgerEntry.transaction_at_utc >= start_utc,
                    LedgerEntry.transaction_at_utc < end_utc,
                )
                .group_by(LedgerEntry.currency, LedgerEntry.direction)
                .all()
            )
            nutrition = (
                session.query(
                    func.count(NutritionLog.id),
                    func.sum(NutritionLog.total_calories),
                    func.sum(NutritionLog.total_protein_grams),
                )
                .filter(
                    NutritionLog.owner_id == owner_id,
                    NutritionLog.status == "confirmed",
                    NutritionLog.logged_at_utc >= start_utc,
                    NutritionLog.logged_at_utc < end_utc,
                )
                .one()
            )
            money: dict[str, dict[str, int]] = {}
            for currency, direction, total in ledger_rows:
                money.setdefault(
                    currency,
                    {"income_minor": 0, "expense_minor": 0},
                )[
                    f"{direction}_minor"
                ] = int(total or 0)
            return {
                "week_start": week_start.isoformat(),
                "week_end": (week_start + timedelta(days=6)).isoformat(),
                "work_count": len(work),
                "work_items": [
                    (item.cleaned_text or item.original_text)[:160] for item in work[:5]
                ],
                "note_count": int(note_count),
                "goals_updated": int(goals_updated),
                "pending_reminders": int(pending_reminders),
                "money": money,
                "nutrition": {
                    "confirmed_meals": int(nutrition[0] or 0),
                    "calories": str(nutrition[1] or Decimal("0")),
                    "protein_grams": str(nutrition[2] or Decimal("0")),
                },
            }
        finally:
            session.close()

    def store_digest_message(
        self,
        delivery_id: int,
        snapshot: dict,
        message: str,
    ) -> None:
        session = self.session_factory()
        try:
            with session.begin():
                delivery = session.get(DigestDelivery, delivery_id)
                if delivery is not None and delivery.status == "claimed":
                    delivery.payload_snapshot = snapshot
                    delivery.message_text = message[:4000]
        finally:
            session.close()

    def mark_digest_success(
        self,
        delivery_id: int,
        now: datetime,
        telegram_message_id: int | None,
    ) -> None:
        session = self.session_factory()
        try:
            with session.begin():
                delivery = session.get(DigestDelivery, delivery_id)
                if delivery is None or delivery.status != "claimed":
                    return
                delivery.status = "sent"
                delivery.delivered_at_utc = as_utc(now)
                delivery.telegram_message_id = _message_id(telegram_message_id)
                delivery.lease_expires_at_utc = None
                delivery.last_error_category = None
                delivery.message_text = None
                delivery.payload_snapshot = None
        finally:
            session.close()

    def mark_digest_failure(
        self,
        delivery_id: int,
        now: datetime,
        failure: DeliveryFailure,
    ) -> None:
        session = self.session_factory()
        try:
            with session.begin():
                delivery = session.get(DigestDelivery, delivery_id)
                if delivery is None or delivery.status != "claimed":
                    return
                terminal = (
                    failure.permanent or delivery.attempt_count >= self.max_attempts
                )
                delivery.status = "dead_letter" if terminal else "failed"
                delivery.last_error_category = failure.category
                delivery.lease_expires_at_utc = None
                delivery.next_attempt_at_utc = (
                    None if terminal else self._retry_at(now, delivery.attempt_count)
                )
                if terminal:
                    delivery.message_text = None
                    delivery.payload_snapshot = None
        finally:
            session.close()


def format_reminder(claim: ReminderClaim) -> str:
    text = f"⏰ <b>Reminder</b>\n{escape(claim.title)}"
    if claim.description:
        text += f"\n\n{escape(claim.description)}"
    return text


def format_digest(snapshot: dict) -> str:
    lines = [
        "📅 <b>Your private Sunday summary</b>",
        f"{snapshot['week_start']} to {snapshot['week_end']}",
        "",
        f"Work logs: {snapshot['work_count']}",
        f"Notes created: {snapshot['note_count']}",
        f"Goals updated: {snapshot['goals_updated']}",
        f"Pending reminders: {snapshot['pending_reminders']}",
    ]
    if snapshot["work_items"]:
        lines.append("")
        lines.append("<b>Work highlights</b>")
        lines.extend(f"• {escape(item)}" for item in snapshot["work_items"])
    if snapshot["money"]:
        lines.append("")
        lines.append("<b>Money</b>")
        for currency, totals in sorted(snapshot["money"].items()):
            lines.append(
                f"• {currency}: income {totals['income_minor']} / "
                f"expense {totals['expense_minor']} minor units"
            )
    nutrition = snapshot["nutrition"]
    if nutrition["confirmed_meals"]:
        lines.extend(
            [
                "",
                "<b>Approximate nutrition logged</b>",
                f"• Calories: {nutrition['calories']} kcal",
                f"• Protein: {nutrition['protein_grams']} g",
            ]
        )
    lines.extend(
        [
            "",
            "A neutral summary of records you chose to save. " "Nothing was published.",
        ]
    )
    return "\n".join(lines)[:4000]


class DurableWorker:
    def __init__(
        self,
        store: DurableDeliveryStore,
        gateway: MessageGateway,
        *,
        narrator: DigestNarrator | None = None,
        clock: Callable[[], datetime] | None = None,
    ):
        self.store = store
        self.gateway = gateway
        self.narrator = narrator
        self.clock = clock or (lambda: datetime.now(UTC))

    async def run_once(self) -> int:
        reminder_claims = await asyncio.to_thread(
            self.store.claim_reminders,
            self.clock(),
        )
        await asyncio.gather(
            *(self._deliver_reminder(claim) for claim in reminder_claims)
        )

        digest_claims = await asyncio.to_thread(
            self.store.claim_digests,
            self.clock(),
        )
        await asyncio.gather(*(self._deliver_digest(claim) for claim in digest_claims))
        return len(reminder_claims) + len(digest_claims)

    async def _deliver_reminder(self, claim: ReminderClaim) -> None:
        active = await asyncio.to_thread(
            self.store.reminder_claim_is_active,
            claim.delivery_id,
        )
        if not active:
            await asyncio.to_thread(
                self.store.cancel_reminder_claim,
                claim.delivery_id,
            )
            return
        try:
            message_id = await self.gateway.send(
                claim.chat_id,
                format_reminder(claim),
            )
        except DeliveryFailure as failure:
            await asyncio.to_thread(
                self.store.mark_reminder_failure,
                claim.delivery_id,
                self.clock(),
                failure,
            )
        except Exception:
            logger.exception("Unexpected reminder delivery failure")
            await asyncio.to_thread(
                self.store.mark_reminder_failure,
                claim.delivery_id,
                self.clock(),
                DeliveryFailure("unexpected_delivery_error"),
            )
        else:
            await asyncio.to_thread(
                self.store.mark_reminder_success,
                claim.delivery_id,
                self.clock(),
                message_id,
            )

    async def _deliver_digest(self, claim: DigestClaim) -> None:
        active = await asyncio.to_thread(
            self.store.digest_claim_is_active,
            claim.delivery_id,
        )
        if not active:
            await asyncio.to_thread(
                self.store.cancel_digest_claim,
                claim.delivery_id,
            )
            return
        message = claim.message_text
        try:
            if not message:
                snapshot = await asyncio.to_thread(
                    self.store.build_digest_snapshot,
                    claim.owner_id,
                    claim.digest_week_start,
                )
                fallback = format_digest(snapshot)
                if self.narrator is not None:
                    try:
                        message = await self.narrator.narrate(
                            snapshot,
                            fallback,
                        )
                    except Exception:
                        logger.warning(
                            "Digest narrator failed; using deterministic fallback",
                            exc_info=True,
                        )
                        message = fallback
                else:
                    message = fallback
                if not message or len(message) > 4000:
                    message = fallback
                await asyncio.to_thread(
                    self.store.store_digest_message,
                    claim.delivery_id,
                    snapshot,
                    message,
                )
            message_id = await self.gateway.send(claim.chat_id, message)
        except DeliveryFailure as failure:
            await asyncio.to_thread(
                self.store.mark_digest_failure,
                claim.delivery_id,
                self.clock(),
                failure,
            )
        except Exception:
            logger.exception("Unexpected digest delivery failure")
            await asyncio.to_thread(
                self.store.mark_digest_failure,
                claim.delivery_id,
                self.clock(),
                DeliveryFailure("unexpected_delivery_error"),
            )
        else:
            await asyncio.to_thread(
                self.store.mark_digest_success,
                claim.delivery_id,
                self.clock(),
                message_id,
            )

    async def run_forever(self, poll_interval_seconds: float) -> None:
        while True:
            processed = await self.run_once()
            if processed == 0:
                await asyncio.sleep(poll_interval_seconds)
