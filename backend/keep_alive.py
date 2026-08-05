"""Best-effort self-ping that keeps a free web service from idling out.

Render suspends a free web service after a period with no inbound HTTP traffic.
Database activity does not count toward that timer, so a scheduled job inside
PostgreSQL cannot prevent the suspension. This loop instead issues a real HTTP
request to the service's own public URL, which travels through the platform
edge and resets the idle timer the same way user traffic does.

The loop can only keep an already-running process awake. It cannot wake a
service that has already slept, because nothing is running to send the request.
An external scheduled ping remains necessary for that; see docs/KEEP_ALIVE.md.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import logging
from urllib.parse import urlparse

import httpx

from config import settings
from observability import runtime_metrics

logger = logging.getLogger(__name__)

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}

Pinger = Callable[[str], Awaitable[int]]


class KeepAliveUnavailable(RuntimeError):
    """Raised when self-pinging is disabled or cannot be performed safely."""


async def _http_head(url: str) -> int:
    """Send one lightweight liveness request and return its status code."""
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(settings.keep_alive_timeout_seconds),
        follow_redirects=True,
        verify=not settings.disable_ssl_verify,
    ) as client:
        response = await client.head(url)
        return response.status_code


class KeepAliveLoop:
    """Ping the service's own public health endpoint on a bounded cadence."""

    def __init__(
        self,
        url: str,
        *,
        interval_seconds: float,
        ping: Pinger | None = None,
    ):
        self.url = url
        self.interval_seconds = interval_seconds
        self.ping = ping or _http_head
        self.success_total = 0
        self.failure_total = 0
        self._stop_event = asyncio.Event()

    async def run_once(self) -> bool:
        """Send one ping, absorbing every failure so the loop cannot die."""
        try:
            status_code = await self.ping(self.url)
        except Exception as exc:
            self.failure_total += 1
            runtime_metrics.increment("keep_alive_failures")
            logger.warning(
                "Keep-alive ping failed",
                extra={"keep_alive_error": type(exc).__name__[:64]},
            )
            return False
        if status_code >= 400:
            self.failure_total += 1
            runtime_metrics.increment("keep_alive_failures")
            logger.warning(
                "Keep-alive ping returned an error status",
                extra={"keep_alive_status": status_code},
            )
            return False
        self.success_total += 1
        runtime_metrics.increment("keep_alive_pings")
        logger.debug("Keep-alive ping succeeded")
        return True

    async def run_forever(self) -> None:
        """Ping on a fixed cadence until the application shuts down."""
        logger.info(
            "Keep-alive self-ping started",
            extra={"keep_alive_interval_seconds": self.interval_seconds},
        )
        try:
            while not self._stop_event.is_set():
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=self.interval_seconds,
                    )
                except asyncio.TimeoutError:
                    pass
                if self._stop_event.is_set():
                    break
                try:
                    await self.run_once()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Keep-alive sweep failed unexpectedly")
        finally:
            logger.info("Keep-alive self-ping stopped")

    async def stop(self) -> None:
        self._stop_event.set()


def keep_alive_target_url() -> str:
    """Resolve and validate the public URL this deployment should ping."""
    base_url = (settings.app_base_url or "").strip().rstrip("/")
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise KeepAliveUnavailable(
            "APP_BASE_URL must be an absolute http(s) URL to self-ping"
        )
    if parsed.hostname in LOCAL_HOSTS:
        raise KeepAliveUnavailable(
            "A loopback APP_BASE_URL never reaches the platform edge"
        )
    return f"{base_url}/health"


def build_keep_alive_loop() -> KeepAliveLoop:
    """Build the configured loop after validating that pinging is meaningful."""
    if not settings.keep_alive_enabled:
        raise KeepAliveUnavailable("Keep-alive self-pinging is disabled")
    return KeepAliveLoop(
        keep_alive_target_url(),
        interval_seconds=settings.keep_alive_interval_seconds,
    )
