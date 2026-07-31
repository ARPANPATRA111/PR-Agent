"""Standalone durable worker entry point."""

import asyncio
from datetime import datetime, timezone
import logging
import os
import uuid

from config import settings
from durable_worker import (
    DurableDeliveryStore,
    DurableWorker,
    TelegramMessageGateway,
)
from memory import get_memory_manager
from privacy import prune_operational_metadata
from public_models import WorkerHeartbeat
from telegram_cleanup import (
    TelegramCleanupGateway,
    TelegramCleanupStore,
    TelegramCleanupWorker,
)
from utils import setup_logging


async def main() -> None:
    setup_logging()
    if not settings.public_v2_enabled:
        raise RuntimeError("PUBLIC_V2_ENABLED must be true for the durable worker")
    if not settings.reminder_worker_enabled:
        raise RuntimeError(
            "REMINDER_WORKER_ENABLED must be true for the durable worker"
        )
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required for the durable worker")
    memory = get_memory_manager()
    store = DurableDeliveryStore(
        memory.SessionLocal,
        batch_size=settings.worker_batch_size,
        lease_seconds=settings.worker_lease_seconds,
        max_attempts=settings.worker_max_attempts,
        base_backoff_seconds=settings.worker_base_backoff_seconds,
    )
    worker = DurableWorker(
        store,
        TelegramMessageGateway(settings.telegram_bot_token),
    )
    cleanup_worker = (
        TelegramCleanupWorker(
            TelegramCleanupStore(
                memory.SessionLocal,
                batch_size=settings.worker_batch_size,
                lease_seconds=settings.worker_lease_seconds,
                max_attempts=settings.worker_max_attempts,
                base_backoff_seconds=settings.worker_base_backoff_seconds,
            ),
            TelegramCleanupGateway(settings.telegram_bot_token),
        )
        if settings.message_cleanup_enabled
        else None
    )
    logging.getLogger(__name__).info("Durable delivery worker started")
    instance_id = (
        f"{os.environ.get('HOSTNAME', 'worker')[:80]}:" f"{uuid.uuid4().hex[:12]}"
    )
    processed_total = 0

    def heartbeat(
        *,
        status: str = "running",
        error_category: str | None = None,
    ) -> None:
        with memory.get_session() as session:
            row = (
                session.query(WorkerHeartbeat)
                .filter(
                    WorkerHeartbeat.worker_name == "delivery",
                    WorkerHeartbeat.instance_id == instance_id,
                )
                .one_or_none()
            )
            if row is None:
                row = WorkerHeartbeat(
                    worker_name="delivery",
                    instance_id=instance_id,
                    status=status,
                )
                session.add(row)
            row.status = status
            row.last_seen_at_utc = datetime.now(timezone.utc)
            row.processed_total = processed_total
            row.last_error_category = error_category

    await asyncio.to_thread(heartbeat, status="starting")
    next_prune_at = 0.0
    next_heartbeat_at = 0.0
    while True:
        try:
            processed = await worker.run_once()
            if cleanup_worker is not None:
                processed += await cleanup_worker.run_once()
            processed_total += processed
        except Exception as exc:
            await asyncio.to_thread(
                heartbeat,
                status="failed",
                error_category=type(exc).__name__[:64],
            )
            raise
        loop_time = asyncio.get_running_loop().time()
        if loop_time >= next_heartbeat_at:
            await asyncio.to_thread(heartbeat)
            next_heartbeat_at = loop_time + settings.worker_heartbeat_interval_seconds
        if loop_time >= next_prune_at:

            def prune() -> None:
                with memory.get_session() as session:
                    prune_operational_metadata(
                        session,
                        now=datetime.now(timezone.utc),
                        retention_days=settings.operational_metadata_retention_days,
                    )

            await asyncio.to_thread(prune)
            next_prune_at = loop_time + settings.operational_prune_interval_seconds
        if processed == 0:
            await asyncio.sleep(settings.worker_poll_interval_seconds)


if __name__ == "__main__":
    asyncio.run(main())
