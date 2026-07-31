"""Standalone durable worker entry point."""

import asyncio
from datetime import datetime, timezone
import logging

from config import settings
from durable_worker import (
    DurableDeliveryStore,
    DurableWorker,
    TelegramMessageGateway,
)
from memory import get_memory_manager
from privacy import prune_operational_metadata
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
    next_prune_at = 0.0
    while True:
        processed = await worker.run_once()
        if cleanup_worker is not None:
            processed += await cleanup_worker.run_once()
        loop_time = asyncio.get_running_loop().time()
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
