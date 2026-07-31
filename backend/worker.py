"""Standalone durable worker entry point."""

import asyncio
import logging

from config import settings
from durable_worker import (
    DurableDeliveryStore,
    DurableWorker,
    TelegramMessageGateway,
)
from memory import get_memory_manager
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
    logging.getLogger(__name__).info("Durable delivery worker started")
    await worker.run_forever(settings.worker_poll_interval_seconds)


if __name__ == "__main__":
    asyncio.run(main())
