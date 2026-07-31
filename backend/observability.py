"""Privacy-safe operational counters and database health snapshots."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from public_models import (
    AgentRun,
    DigestDelivery,
    Reminder,
    ReminderDelivery,
    TelegramMessage,
    WorkerHeartbeat,
)

UTC = timezone.utc


class RuntimeMetrics:
    def __init__(self) -> None:
        self._counts: Counter[str] = Counter()
        self._lock = Lock()

    def increment(self, name: str, value: int = 1) -> None:
        with self._lock:
            self._counts[name] += value

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(sorted(self._counts.items()))


runtime_metrics = RuntimeMetrics()


def operational_snapshot(
    session: Session,
    *,
    stale_after_seconds: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(UTC)

    def count(model, *filters) -> int:
        return int(session.query(func.count(model.id)).filter(*filters).scalar() or 0)

    oldest_due = (
        session.query(func.min(Reminder.next_run_at_utc))
        .filter(
            Reminder.enabled.is_(True),
            Reminder.next_run_at_utc.is_not(None),
            Reminder.next_run_at_utc <= current,
        )
        .scalar()
    )
    if oldest_due is not None and oldest_due.tzinfo is None:
        oldest_due = oldest_due.replace(tzinfo=UTC)
    heartbeats = session.query(WorkerHeartbeat).all()

    return {
        "runtime_counters": runtime_metrics.snapshot(),
        "deliveries": {
            "reminder_failed": count(
                ReminderDelivery,
                ReminderDelivery.status.in_(["failed", "dead_letter"]),
            ),
            "digest_failed": count(
                DigestDelivery,
                DigestDelivery.status.in_(["failed", "dead_letter"]),
            ),
            "telegram_cleanup_failed": count(
                TelegramMessage,
                TelegramMessage.cleanup_status.in_(["failed", "dead_letter"]),
            ),
            "due_job_lag_seconds": (
                max(0, int((current - oldest_due).total_seconds()))
                if oldest_due is not None
                else 0
            ),
        },
        "providers": {
            "assistant_failures": count(
                AgentRun,
                AgentRun.status == "failed",
            ),
        },
        "workers": [
            {
                "worker_name": row.worker_name,
                "status": row.status,
                "processed_total": row.processed_total,
                "last_error_category": row.last_error_category,
                "stale": (
                    current
                    - (
                        row.last_seen_at_utc
                        if row.last_seen_at_utc.tzinfo is not None
                        else row.last_seen_at_utc.replace(tzinfo=UTC)
                    )
                ).total_seconds()
                > stale_after_seconds,
            }
            for row in heartbeats
        ],
        "generated_at_utc": current.isoformat(),
    }
