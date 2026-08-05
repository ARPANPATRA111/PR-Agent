"""Tests for the in-process keep-alive self-ping."""

from __future__ import annotations

import asyncio

import pytest

from config import settings
from keep_alive import (
    KeepAliveLoop,
    KeepAliveUnavailable,
    build_keep_alive_loop,
    keep_alive_target_url,
)


@pytest.mark.asyncio
async def test_successful_ping_is_counted():
    loop = KeepAliveLoop(
        "https://example.invalid/health",
        interval_seconds=60,
        ping=_constant_status(200),
    )

    assert await loop.run_once() is True
    assert loop.success_total == 1
    assert loop.failure_total == 0


@pytest.mark.asyncio
async def test_error_status_is_recorded_as_failure():
    loop = KeepAliveLoop(
        "https://example.invalid/health",
        interval_seconds=60,
        ping=_constant_status(503),
    )

    assert await loop.run_once() is False
    assert loop.success_total == 0
    assert loop.failure_total == 1


@pytest.mark.asyncio
async def test_transport_error_never_propagates():
    async def explode(url: str) -> int:
        raise ConnectionError("network is unreachable")

    loop = KeepAliveLoop(
        "https://example.invalid/health",
        interval_seconds=60,
        ping=explode,
    )

    assert await loop.run_once() is False
    assert loop.failure_total == 1


@pytest.mark.asyncio
async def test_run_forever_stops_without_pinging_on_immediate_stop():
    calls: list[str] = []

    async def record(url: str) -> int:
        calls.append(url)
        return 200

    loop = KeepAliveLoop(
        "https://example.invalid/health",
        interval_seconds=30,
        ping=record,
    )
    await loop.stop()
    await asyncio.wait_for(loop.run_forever(), timeout=5)

    assert calls == []


@pytest.mark.asyncio
async def test_run_forever_pings_then_exits_when_stopped():
    started = asyncio.Event()

    async def record(url: str) -> int:
        started.set()
        return 200

    loop = KeepAliveLoop(
        "https://example.invalid/health",
        interval_seconds=0.01,
        ping=record,
    )
    task = asyncio.create_task(loop.run_forever())
    await asyncio.wait_for(started.wait(), timeout=5)
    await loop.stop()
    await asyncio.wait_for(task, timeout=5)

    assert loop.success_total >= 1


def test_target_url_appends_health_path(monkeypatch):
    monkeypatch.setattr(settings, "app_base_url", "https://api.example.com/")

    assert keep_alive_target_url() == "https://api.example.com/health"


@pytest.mark.parametrize(
    "base_url",
    [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "not-a-url",
        "",
    ],
)
def test_unusable_base_urls_are_rejected(monkeypatch, base_url):
    monkeypatch.setattr(settings, "app_base_url", base_url)

    with pytest.raises(KeepAliveUnavailable):
        keep_alive_target_url()


def test_build_requires_the_feature_flag(monkeypatch):
    monkeypatch.setattr(settings, "keep_alive_enabled", False)
    monkeypatch.setattr(settings, "app_base_url", "https://api.example.com")

    with pytest.raises(KeepAliveUnavailable):
        build_keep_alive_loop()


def test_build_returns_configured_loop(monkeypatch):
    monkeypatch.setattr(settings, "keep_alive_enabled", True)
    monkeypatch.setattr(settings, "app_base_url", "https://api.example.com")
    monkeypatch.setattr(settings, "keep_alive_interval_seconds", 600.0)

    loop = build_keep_alive_loop()

    assert loop.url == "https://api.example.com/health"
    assert loop.interval_seconds == 600.0


def _constant_status(status_code: int):
    async def ping(url: str) -> int:
        return status_code

    return ping
