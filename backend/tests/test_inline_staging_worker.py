import asyncio

import pytest
from pydantic import ValidationError

from config import Settings
from inline_staging_worker import InlineStagingDeliveryLoop


class ControlledWorker:
    def __init__(self):
        self.calls = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def run_once(self):
        self.calls += 1
        self.started.set()
        await self.release.wait()
        return 1


def staging_settings(**overrides):
    values = {
        "app_env": "staging",
        "app_base_url": "https://pr-agent-r24-staging-api.onrender.com",
        "frontend_base_url": "https://pr-agent-r24-staging-web.onrender.com",
        "public_v2_enabled": True,
        "inline_staging_worker_enabled": True,
        "database_url": "postgresql://staging.example.invalid/pr_agent",
        "session_signing_secret": "s" * 32,
        "telegram_bot_token": "123456:test-token",
        "telegram_webhook_secret": "w" * 24,
        "telegram_webhook_url": (
            "https://pr-agent-r24-staging-api.onrender.com/webhook"
        ),
        "telegram_mini_app_url": ("https://pr-agent-r24-staging-web.onrender.com"),
        "cors_origins": "https://pr-agent-r24-staging-web.onrender.com",
        "debug": False,
        "disable_ssl_verify": False,
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


def test_inline_mode_is_staging_only_and_mutually_exclusive():
    with pytest.raises(ValidationError, match="allowed only in staging"):
        staging_settings(app_env="production")
    with pytest.raises(ValidationError, match="mutually exclusive"):
        staging_settings(reminder_worker_enabled=True)
    with pytest.raises(ValidationError, match="requires PUBLIC_V2_ENABLED"):
        staging_settings(public_v2_enabled=False)


@pytest.mark.asyncio
async def test_inline_sweeps_do_not_overlap():
    worker = ControlledWorker()
    loop = InlineStagingDeliveryLoop(worker, poll_interval_seconds=5)
    first = asyncio.create_task(loop.run_once())
    await worker.started.wait()
    assert await loop.run_once() == 0
    worker.release.set()
    assert await first == 1
    assert worker.calls == 1


@pytest.mark.asyncio
async def test_loop_catches_up_on_start_wakes_and_stops_cleanly():
    statuses = []

    class Worker:
        def __init__(self):
            self.calls = 0

        async def run_once(self):
            self.calls += 1
            return 1

    worker = Worker()
    loop = InlineStagingDeliveryLoop(
        worker,
        poll_interval_seconds=60,
        heartbeat=lambda status, total, error: statuses.append((status, total, error)),
    )
    task = asyncio.create_task(loop.run_forever())
    for _ in range(50):
        if worker.calls >= 1:
            break
        await asyncio.sleep(0.001)
    assert worker.calls == 1

    loop.request_sweep()
    for _ in range(50):
        if worker.calls >= 2:
            break
        await asyncio.sleep(0.001)
    assert worker.calls == 2

    await loop.stop()
    await asyncio.wait_for(task, timeout=1)
    assert statuses[0][0] == "starting"
    assert statuses[-1][0] == "stopped"
