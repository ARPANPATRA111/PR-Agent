"""Security-boundary tests for the public Telegram application."""

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from auth import create_session, validate_telegram_init_data
from config import settings
from memory import MemoryManager
from models import LinkedInPost, PostTone
from public_models import PublicBase


TEST_BOT_TOKEN = "123456:test-telegram-token"
TEST_WEBHOOK_SECRET = "test_webhook_secret_0123456789"
TEST_SESSION_SECRET = "test-session-signing-secret-at-least-32-bytes"


def signed_init_data(
    telegram_id: int,
    *,
    auth_date: int | None = None,
    first_name: str = "Test",
) -> str:
    values = {
        "auth_date": str(auth_date or int(time.time())),
        "query_id": "AAHdF6IQAAAAAN0XohDhrOrc",
        "user": json.dumps(
            {
                "id": telegram_id,
                "first_name": first_name,
                "username": f"user{telegram_id}",
            },
            separators=(",", ":"),
        ),
    }
    data_check_string = "\n".join(
        f"{key}={values[key]}" for key in sorted(values)
    )
    secret_key = hmac.new(
        b"WebAppData",
        TEST_BOT_TOKEN.encode(),
        hashlib.sha256,
    ).digest()
    values["hash"] = hmac.new(
        secret_key,
        data_check_string.encode(),
        hashlib.sha256,
    ).hexdigest()
    return urlencode(values)


@pytest.fixture
def secure_app(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path / 'security.db'}")
    monkeypatch.setattr(settings, "audio_temp_dir", str(tmp_path / "audio"))
    monkeypatch.setattr(settings, "telegram_bot_token", TEST_BOT_TOKEN)
    monkeypatch.setattr(settings, "telegram_webhook_secret", TEST_WEBHOOK_SECRET)
    monkeypatch.setattr(settings, "session_signing_secret", TEST_SESSION_SECRET)
    monkeypatch.setattr(settings, "telegram_auth_max_age_seconds", 300)

    memory = MemoryManager()
    PublicBase.metadata.create_all(memory.engine)
    import main

    bot_handler = Mock()
    bot_handler.handle_update = AsyncMock()
    monkeypatch.setattr(main, "get_memory_manager", lambda: memory)
    monkeypatch.setattr(main, "get_bot_handler", lambda: bot_handler)
    return main.app, memory, bot_handler


def bearer_headers(memory: MemoryManager, telegram_id: int, name: str) -> dict[str, str]:
    user = memory.get_or_create_user(telegram_id, name)
    token, _ = create_session(user.id, telegram_id, name.lower())
    return {"Authorization": f"Bearer {token}"}


def test_telegram_init_data_accepts_valid_signature(monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", TEST_BOT_TOKEN)
    result = validate_telegram_init_data(signed_init_data(101))
    assert result["telegram_id"] == 101


@pytest.mark.parametrize("mutation", ["signature", "user", "expired"])
def test_telegram_init_data_rejects_tampering(monkeypatch, mutation):
    monkeypatch.setattr(settings, "telegram_bot_token", TEST_BOT_TOKEN)
    monkeypatch.setattr(settings, "telegram_auth_max_age_seconds", 300)
    data = signed_init_data(
        101,
        auth_date=int(time.time()) - 301 if mutation == "expired" else None,
    )
    if mutation == "signature":
        data = data[:-1] + ("0" if data[-1] != "0" else "1")
    elif mutation == "user":
        data = data.replace("%3A101%2C", "%3A999%2C")

    with pytest.raises(HTTPException) as exc:
        validate_telegram_init_data(data)
    assert exc.value.status_code == 401


def test_private_api_rejects_missing_auth(secure_app):
    app, _, _ = secure_app
    response = TestClient(app).get("/api/settings")
    assert response.status_code == 401


def test_mini_app_auth_issues_http_only_session(secure_app):
    app, _, _ = secure_app
    client = TestClient(app)
    response = client.post(
        "/api/auth/telegram",
        json={"init_data": signed_init_data(101)},
    )

    assert response.status_code == 200
    assert response.json()["user"]["telegram_id"] == 101
    assert settings.session_cookie_name in response.cookies
    assert "HttpOnly" in response.headers["set-cookie"]
    assert response.headers["cache-control"] == "no-store"

    valid = signed_init_data(102)
    forged = valid[:-1] + ("0" if valid[-1] != "0" else "1")
    assert client.post(
        "/api/auth/telegram",
        json={"init_data": forged},
    ).status_code == 401


def test_server_identity_overrides_arbitrary_telegram_id(secure_app):
    app, memory, _ = secure_app
    memory.get_or_create_user(202, "Other")
    memory.update_user_preferences(202, {"display_name": "Other account"})
    headers = bearer_headers(memory, 101, "Alice")
    memory.update_user_preferences(101, {"display_name": "Alice account"})

    response = TestClient(app).get(
        "/api/settings?telegram_id=202",
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["display_name"] == "Alice account"


def test_tenant_cannot_read_edit_or_delete_another_users_post(secure_app):
    app, memory, _ = secure_app
    memory.get_or_create_user(202, "Bob")
    post_id = memory.save_linkedin_post(
        LinkedInPost(
            telegram_id=202,
            tone=PostTone.PROFESSIONAL,
            content="Bob's private note",
        )
    )
    alice_headers = bearer_headers(memory, 101, "Alice")
    client = TestClient(app)

    assert client.get(f"/api/posts/{post_id}", headers=alice_headers).status_code == 404
    assert client.put(
        f"/api/posts/{post_id}",
        headers=alice_headers,
        json={"content": "tampered"},
    ).status_code == 404
    assert client.delete(f"/api/posts/{post_id}", headers=alice_headers).status_code == 404
    assert memory.get_post(post_id, 202).content == "Bob's private note"


def test_cookie_mutation_requires_csrf(secure_app):
    app, memory, _ = secure_app
    user = memory.get_or_create_user(101, "Alice")
    token, csrf = create_session(user.id, 101, "alice")
    client = TestClient(app)
    client.cookies.set(settings.session_cookie_name, token)

    rejected = client.put(
        "/api/settings",
        json={"display_name": "Changed"},
    )
    accepted = client.put(
        "/api/settings",
        headers={"X-CSRF-Token": csrf},
        json={"display_name": "Changed"},
    )
    assert rejected.status_code == 403
    assert accepted.status_code == 200


def test_webhook_secret_and_duplicate_update(secure_app):
    app, _, bot_handler = secure_app
    client = TestClient(app)
    update = {
        "update_id": 5001,
        "message": {
            "message_id": 1,
            "date": int(time.time()),
            "chat": {"id": 101, "type": "private"},
            "from": {"id": 101, "first_name": "Alice"},
            "text": "hello",
        },
    }

    assert client.post("/webhook", json=update).status_code == 401
    assert client.post(
        "/webhook",
        json=update,
        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
    ).status_code == 401

    first = client.post(
        "/webhook",
        json=update,
        headers={"X-Telegram-Bot-Api-Secret-Token": TEST_WEBHOOK_SECRET},
    )
    duplicate = client.post(
        "/webhook",
        json=update,
        headers={"X-Telegram-Bot-Api-Secret-Token": TEST_WEBHOOK_SECRET},
    )
    assert first.status_code == 200
    assert first.json()["duplicate"] is False
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True
    bot_handler.handle_update.assert_awaited_once()


def test_public_control_routes_are_absent(secure_app):
    app, memory, _ = secure_app
    client = TestClient(app)
    headers = bearer_headers(memory, 101, "Alice")
    for method, path in [
        ("post", "/webhook/set"),
        ("get", "/webhook/info"),
        ("delete", "/webhook/delete"),
        ("post", "/api/admin/nudge"),
        ("post", "/api/auth/request-code"),
        ("post", "/api/auth/verify"),
    ]:
        assert client.request(method, path, headers=headers).status_code == 404
