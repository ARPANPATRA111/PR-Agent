"""Best-effort durable delivery loop for a sleeping free staging API.

This module deliberately reuses the production delivery store and worker. It
changes only where polling runs, not claiming, retries, or idempotency.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timezone
import logging
import os
import uuid

from config import settings
from durable_worker import DurableDeliveryStore, DurableWorker, TelegramMessageGateway
from memory import get_memory_manager
from privacy import prune_operational_metadata
from public_models import WorkerHeartbeat
from telegram_cleanup import (
    TelegramCleanupGateway,
    TelegramCleanupStore,
    TelegramCleanupWorker,
)

logger = logging.getLogger(__name__)


class InlineStagingDeliveryLoop:
    """Run one non-overlapping delivery sweep at a bounded awake-time cadence."""

    def __init__(
        self,
        worker: DurableWorker,
        *,
        poll_interval_seconds: float,
        cleanup_worker: TelegramCleanupWorker | None = None,
        heartbeat: Callable[[str, int, str | None], None] | None = None,
        prune: Callable[[], None] | None = None,
        prune_interval_seconds: float = 3600,
    ):
        self.worker = worker
        self.cleanup_worker = cleanup_worker
        self.poll_interval_seconds = poll_interval_seconds
        self.heartbeat = heartbeat
        self.prune = prune
        self.prune_interval_seconds = prune_interval_seconds
        self.processed_total = 0
        self._next_prune_at = 0.0
        self._sweep_lock = asyncio.Lock()
        self._wake_event = asyncio.Event()
        self._stop_event = asyncio.Event()

    def request_sweep(self) -> None:
        """Wake the loop after valid Telegram or authenticated API activity."""
        self._wake_event.set()

    async def _heartbeat(
        self,
        status: str,
        error_category: str | None = None,
    ) -> None:
        if self.heartbeat is not None:
            await asyncio.to_thread(
                self.heartbeat,
                status,
                self.processed_total,
                error_category,
            )

    async def run_once(self) -> int:
        """Run one bounded sweep, returning immediately if one is in progress."""
        if self._sweep_lock.locked():
            return 0
        async with self._sweep_lock:
            processed = await self.worker.run_once()
            if self.cleanup_worker is not None:
                processed += await self.cleanup_worker.run_once()
            self.processed_total += processed

            loop_time = asyncio.get_running_loop().time()
            if self.prune is not None and loop_time >= self._next_prune_at:
                await asyncio.to_thread(self.prune)
                self._next_prune_at = loop_time + self.prune_interval_seconds
            await self._heartbeat("running")
            return processed

    async def run_forever(self) -> None:
        """Catch up at startup, poll only while awake, and stop cleanly."""
        await self._heartbeat("starting")
        logger.warning(
            "Free staging inline delivery started; scheduled delivery is best-effort"
        )
        try:
            while not self._stop_event.is_set():
                self._wake_event.clear()
                try:
                    await self.run_once()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.exception("Inline staging delivery sweep failed")
                    await self._heartbeat("failed", type(exc).__name__[:64])
                if self._stop_event.is_set():
                    break
                try:
                    await asyncio.wait_for(
                        self._wake_event.wait(),
                        timeout=self.poll_interval_seconds,
                    )
                except asyncio.TimeoutError:
                    pass
        finally:
            await self._heartbeat("stopped")
            logger.info("Free staging inline delivery stopped")

    async def run_one_shot(self) -> int:
        """Run a CLI-requested sweep without leaving a live heartbeat behind."""
        await self._heartbeat("starting")
        try:
            return await self.run_once()
        finally:
            await self._heartbeat("stopped")

    async def stop(self) -> None:
        self._stop_event.set()
        self._wake_event.set()


def build_inline_staging_loop() -> InlineStagingDeliveryLoop:
    """Build the concrete staging loop after configuration validation."""
    if not settings.inline_staging_worker_enabled:
        raise RuntimeError("Inline staging delivery is disabled")
    if settings.app_env != "staging":
        raise RuntimeError("Inline staging delivery may run only in staging")
    if settings.reminder_worker_enabled:
        raise RuntimeError("Dedicated and inline delivery workers cannot run together")
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required for inline delivery")

    memory = get_memory_manager()
    store = DurableDeliveryStore(
        memory.SessionLocal,
        batch_size=settings.worker_batch_size,
        lease_seconds=settings.worker_lease_seconds,
        max_attempts=settings.worker_max_attempts,
        base_backoff_seconds=settings.worker_base_backoff_seconds,
    )
    worker = DurableWorker(store, TelegramMessageGateway(settings.telegram_bot_token))
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
    instance_id = f"{os.environ.get('HOSTNAME', 'web')[:80]}:{uuid.uuid4().hex[:12]}"

    def heartbeat(
        status: str, processed_total: int, error_category: str | None
    ) -> None:
        with memory.get_session() as session:
            row = (
                session.query(WorkerHeartbeat)
                .filter(
                    WorkerHeartbeat.worker_name == "inline-staging",
                    WorkerHeartbeat.instance_id == instance_id,
                )
                .one_or_none()
            )
            if row is None:
                row = WorkerHeartbeat(
                    worker_name="inline-staging",
                    instance_id=instance_id,
                    status=status,
                )
                session.add(row)
            row.status = status
            row.last_seen_at_utc = datetime.now(timezone.utc)
            row.processed_total = processed_total
            row.last_error_category = error_category

    def prune() -> None:
        with memory.get_session() as session:
            prune_operational_metadata(
                session,
                now=datetime.now(timezone.utc),
                retention_days=settings.operational_metadata_retention_days,
            )

    return InlineStagingDeliveryLoop(
        worker,
        poll_interval_seconds=settings.inline_staging_poll_interval_seconds,
        cleanup_worker=cleanup_worker,
        heartbeat=heartbeat,
        prune=prune,
        prune_interval_seconds=settings.operational_prune_interval_seconds,
    )
