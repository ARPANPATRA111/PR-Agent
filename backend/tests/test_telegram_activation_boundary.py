"""Pre-bot staging must be deployable without constructing Telegram clients."""

from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from config import Settings, settings


def staging_settings(**overrides):
    values = {
        "_env_file": None,
        "app_env": "staging",
        "app_base_url": "https://pr-agent-r24-staging-api.onrender.com",
        "frontend_base_url": "https://pr-agent-r24-staging-web.onrender.com",
        "cors_origins": "https://pr-agent-r24-staging-web.onrender.com",
        "public_v2_enabled": True,
        "inline_staging_worker_enabled": True,
        "database_url": "postgresql://staging.example.invalid/pr_agent",
        "session_signing_secret": "s" * 32,
        "debug": False,
        "disable_ssl_verify": False,
    }
    values.update(overrides)
    return Settings(**values)


def test_staging_configuration_accepts_disabled_telegram_without_credentials():
    configured = staging_settings()
    assert configured.telegram_integration_enabled is False
    assert configured.telegram_bot_token == ""


def test_enabling_telegram_requires_all_credentials():
    with pytest.raises(ValidationError, match="TELEGRAM_BOT_TOKEN"):
        staging_settings(telegram_integration_enabled=True)


def test_cleanup_and_dedicated_delivery_require_telegram():
    with pytest.raises(ValidationError, match="MESSAGE_CLEANUP_ENABLED"):
        staging_settings(message_cleanup_enabled=True)
    with pytest.raises(ValidationError, match="REMINDER_WORKER_ENABLED"):
        staging_settings(
            inline_staging_worker_enabled=False,
            reminder_worker_enabled=True,
        )


def test_disabled_lifespan_retains_pending_work_and_never_builds_client(monkeypatch):
    import inline_staging_worker
    import main

    build = Mock(side_effect=AssertionError("delivery client must not be constructed"))
    pending = ["reminder-1"]
    monkeypatch.setattr(inline_staging_worker, "build_inline_staging_loop", build)
    monkeypatch.setattr(main, "get_memory_manager", Mock())
    monkeypatch.setattr(settings, "public_v2_enabled", True)
    monkeypatch.setattr(settings, "inline_staging_worker_enabled", True)
    monkeypatch.setattr(settings, "telegram_integration_enabled", False)

    with TestClient(main.app):
        assert main.app.state.telegram_delivery_status == "awaiting_telegram"

    build.assert_not_called()
    assert pending == ["reminder-1"]


def test_disabled_webhook_and_mini_app_auth_do_not_touch_telegram(monkeypatch):
    import main

    bot_handler = Mock()
    bot_handler.handle_update = Mock()
    monkeypatch.setattr(main, "get_bot_handler", Mock(return_value=bot_handler))
    monkeypatch.setattr(
        main,
        "get_memory_manager",
        Mock(side_effect=AssertionError("disabled integration must not touch storage")),
    )
    monkeypatch.setattr(settings, "telegram_integration_enabled", False)
    client = TestClient(main.app)

    webhook = client.post(
        "/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "ignored"},
        json={"update_id": 9001},
    )
    auth = client.post("/api/auth/telegram", json={"init_data": "ignored"})

    assert webhook.status_code == 503
    assert auth.status_code == 503
    main.get_bot_handler.assert_not_called()
    main.get_memory_manager.assert_not_called()
