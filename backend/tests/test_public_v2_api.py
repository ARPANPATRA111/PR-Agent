from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import api.public_v2 as public_api
from auth import TokenData, get_current_user
from domain.errors import DomainError
from public_models import PublicBase
from nutrition.providers import NutritionProviderUnavailable


@pytest.fixture()
def api_client(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, connection_record):
        del connection_record
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    PublicBase.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    class Memory:
        SessionLocal = factory

    monkeypatch.setattr(public_api, "get_memory_manager", lambda: Memory())
    app = FastAPI()
    app.include_router(public_api.router)

    @app.exception_handler(DomainError)
    async def handle_domain_error(request: Request, exc: DomainError):
        del request
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.public_message},
        )

    identity = {
        "telegram_id": 1001,
        "issued_at": datetime.now(timezone.utc),
    }

    async def authenticated_user():
        return TokenData(
            user_id=1,
            telegram_id=identity["telegram_id"],
            username=f"user_{identity['telegram_id']}",
            csrf_token="csrf",
            exp=datetime.now(timezone.utc) + timedelta(minutes=5),
            issued_at=identity["issued_at"],
            jti="test-session",
        )

    app.dependency_overrides[get_current_user] = authenticated_user
    try:
        yield TestClient(app), identity
    finally:
        engine.dispose()


def test_api_crud_uses_authenticated_owner_and_hides_other_records(api_client):
    client, identity = api_client
    created = client.post(
        "/api/v2/notes",
        json={
            "body": "Tenant A private note",
            "idempotency_key": "api-note-key-a",
        },
    )
    assert created.status_code == 201
    note = created.json()

    owner_override = client.post(
        "/api/v2/notes",
        json={"body": "bad", "owner_id": 999},
    )
    assert owner_override.status_code == 422

    identity["telegram_id"] = 2002
    hidden_get = client.get(f"/api/v2/notes/{note['id']}")
    hidden_patch = client.patch(
        f"/api/v2/notes/{note['id']}",
        json={"version": note["version"], "body": "stolen"},
    )
    hidden_delete = client.delete(f"/api/v2/notes/{note['id']}")
    assert (
        hidden_get.status_code,
        hidden_patch.status_code,
        hidden_delete.status_code,
    ) == (404, 404, 404)
    assert hidden_get.json() == hidden_patch.json() == hidden_delete.json()

    identity["telegram_id"] = 1001
    updated = client.patch(
        f"/api/v2/notes/{note['id']}",
        json={"version": note["version"], "pinned": True},
    )
    assert updated.status_code == 200
    assert updated.json()["pinned"] is True
    assert updated.json()["version"] == 2
    assert client.delete(f"/api/v2/notes/{note['id']}").status_code == 204


def test_every_public_record_family_is_hidden_from_another_owner(api_client):
    """Prove isolation at the HTTP boundary, not only in service unit tests."""
    client, identity = api_client
    future = datetime.now(timezone.utc) + timedelta(days=1)
    created = {
        "work-logs": client.post(
            "/api/v2/work-logs",
            json={"original_text": "Alice work", "timezone": "Asia/Kolkata"},
        ),
        "notes": client.post(
            "/api/v2/notes",
            json={"body": "Alice note"},
        ),
        "ledger": client.post(
            "/api/v2/ledger",
            json={
                "direction": "expense",
                "amount": "9",
                "currency": "INR",
                "description": "Alice expense",
            },
        ),
        "goals": client.post(
            "/api/v2/goals",
            json={"title": "Alice goal", "target_value": "1"},
        ),
        "reminders": client.post(
            "/api/v2/reminders",
            json={
                "title": "Alice reminder",
                "schedule_type": "once",
                "start_at_local": future.isoformat(),
                "timezone": "UTC",
            },
        ),
        "nutrition": client.post(
            "/api/v2/nutrition",
            json={
                "original_text": "50 g paneer",
                "meal_name": "lunch",
                "timezone": "Asia/Kolkata",
            },
        ),
    }
    assert {name: response.status_code for name, response in created.items()} == {
        "work-logs": 201,
        "notes": 201,
        "ledger": 201,
        "goals": 201,
        "reminders": 201,
        "nutrition": 201,
    }

    records = {name: response.json() for name, response in created.items()}
    identity["telegram_id"] = 2002

    for family in ("work-logs", "notes", "ledger", "goals", "reminders"):
        record = records[family]
        assert client.get(f"/api/v2/{family}/{record['id']}").status_code == 404
        assert client.delete(f"/api/v2/{family}/{record['id']}").status_code == 404

    assert client.get("/api/v2/work-logs").json() == []
    assert client.get("/api/v2/notes").json() == []
    assert client.get("/api/v2/ledger").json() == []
    assert client.get("/api/v2/goals").json() == []
    assert client.get("/api/v2/reminders").json() == []
    assert client.get("/api/v2/ledger/summary").json() == []

    nutrition = records["nutrition"]
    assert client.get(f"/api/v2/nutrition/{nutrition['id']}").status_code == 404
    assert (
        client.post(
            f"/api/v2/nutrition/{nutrition['id']}/confirm",
            json={"version": nutrition["version"]},
        ).status_code
        == 404
    )
    assert client.delete(f"/api/v2/nutrition/{nutrition['id']}").status_code == 404
    assert client.get("/api/v2/nutrition").json() == []
    assert "Alice" not in client.get("/api/v2/account/export?format=json").text


def test_api_core_create_list_and_money_summary(api_client):
    client, _ = api_client
    work_log = client.post(
        "/api/v2/work-logs",
        json={
            "original_text": "<script>not rendered as HTML</script>",
            "tags": ["security"],
            "timezone": "Asia/Kolkata",
        },
    )
    assert work_log.status_code == 201
    assert (
        client.get("/api/v2/work-logs?tag=security").json()[0]["original_text"]
        == "<script>not rendered as HTML</script>"
    )

    expense = client.post(
        "/api/v2/ledger",
        json={
            "direction": "expense",
            "amount": "240.50",
            "currency": "INR",
            "description": "Dinner",
        },
    )
    income = client.post(
        "/api/v2/ledger",
        json={
            "direction": "income",
            "amount": "5",
            "currency": "USD",
            "description": "Refund",
        },
    )
    assert expense.status_code == income.status_code == 201
    assert client.get("/api/v2/ledger/summary").json() == [
        {"currency": "INR", "expense_minor": 24050, "income_minor": 0},
        {"currency": "USD", "expense_minor": 0, "income_minor": 500},
    ]

    goal = client.post(
        "/api/v2/goals",
        json={"title": "Ship public beta", "target_value": "1"},
    )
    assert goal.status_code == 201
    assert client.get("/api/v2/goals?status=active").json()[0]["id"] == (
        goal.json()["id"]
    )

    reminder_at = datetime.now(timezone.utc) + timedelta(days=1)
    reminder = client.post(
        "/api/v2/reminders",
        json={
            "title": "Review beta",
            "schedule_type": "once",
            "start_at_local": reminder_at.isoformat(),
            "timezone": "UTC",
        },
    )
    assert reminder.status_code == 201
    assert client.get("/api/v2/reminders?enabled=true").json()[0]["id"] == (
        reminder.json()["id"]
    )


def test_legacy_telegram_timezone_alias_is_canonicalized(api_client):
    client, _ = api_client
    work = client.post(
        "/api/v2/work-logs",
        json={
            "original_text": "Logged from an older Telegram WebView",
            "timezone": "Asia/Calcutta",
        },
    )
    ledger = client.post(
        "/api/v2/ledger",
        json={
            "direction": "expense",
            "amount": "120",
            "currency": "INR",
            "description": "Lunch",
            "timezone": "Asia/Calcutta",
        },
    )

    assert work.status_code == ledger.status_code == 201
    assert work.json()["timezone"] == "Asia/Kolkata"
    assert ledger.json()["timezone"] == "Asia/Kolkata"


def test_schedule_preferences_are_versioned_and_sunday_only(api_client):
    client, _ = api_client
    current = client.get("/api/v2/schedule-preferences")
    assert current.status_code == 200
    settings = current.json()
    assert settings["sunday_digest_enabled"] is False

    updated = client.patch(
        "/api/v2/schedule-preferences",
        json={
            "preference_version": settings["preference_version"],
            "digest_version": settings["digest_version"],
            "timezone": "Asia/Kolkata",
            "sunday_digest_enabled": True,
            "sunday_digest_time": "20:00:00",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["sunday_digest_enabled"] is True
    assert updated.json()["next_digest_at_utc"] is not None

    stale = client.patch(
        "/api/v2/schedule-preferences",
        json={
            "preference_version": settings["preference_version"],
            "digest_version": settings["digest_version"],
            "timezone": "UTC",
            "sunday_digest_enabled": False,
            "sunday_digest_time": "20:00:00",
        },
    )
    assert stale.status_code == 409


def test_account_export_is_downloadable_and_tenant_scoped(api_client):
    client, identity = api_client
    assert (
        client.post(
            "/api/v2/notes",
            json={
                "body": "Alice export only",
                "idempotency_key": "export-alice-note",
            },
        ).status_code
        == 201
    )
    response = client.get("/api/v2/account/export?format=json")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "attachment" in response.headers["content-disposition"]
    assert response.json()["notes"][0]["body"] == "Alice export only"

    identity["telegram_id"] = 2002
    bob = client.get("/api/v2/account/export?format=json")
    assert bob.status_code == 200
    assert bob.json()["notes"] == []
    assert "Alice export only" not in bob.text

    csv_response = client.get("/api/v2/account/export?format=csv")
    assert csv_response.status_code == 200
    assert csv_response.headers["content-type"] == "application/zip"


def test_account_delete_requires_recent_explicit_confirmation(api_client):
    client, identity = api_client
    invalid = client.request(
        "DELETE",
        "/api/v2/account",
        json={"confirmation": "delete it", "acknowledge": True},
    )
    assert invalid.status_code == 422

    identity["issued_at"] = datetime.now(timezone.utc) - timedelta(hours=1)
    stale = client.request(
        "DELETE",
        "/api/v2/account",
        json={
            "confirmation": "DELETE MY ACCOUNT",
            "acknowledge": True,
        },
    )
    assert stale.status_code == 403

    identity["issued_at"] = datetime.now(timezone.utc)
    deleted = client.request(
        "DELETE",
        "/api/v2/account",
        json={
            "confirmation": "DELETE MY ACCOUNT",
            "acknowledge": True,
        },
    )
    assert deleted.status_code == 204


def test_api_invalid_inputs_are_clear_422_responses(api_client):
    client, _ = api_client
    invalid_amount = client.post(
        "/api/v2/ledger",
        json={
            "direction": "expense",
            "amount": "0",
            "currency": "INR",
            "description": "invalid",
        },
    )
    invalid_currency = client.post(
        "/api/v2/ledger",
        json={
            "direction": "expense",
            "amount": "1",
            "currency": "ZZZ",
            "description": "invalid",
        },
    )
    long_note = client.post(
        "/api/v2/notes",
        json={"body": "x" * 10_001},
    )
    assert invalid_amount.status_code == 422
    assert invalid_currency.status_code == 422
    assert long_note.status_code == 422


def test_nutrition_preview_confirm_edit_summary_and_isolation(api_client):
    client, identity = api_client
    preview = client.post(
        "/api/v2/nutrition",
        json={
            "original_text": "50 g paneer and one glass of milk",
            "meal_name": "lunch",
            "timezone": "Asia/Kolkata",
            "idempotency_key": "api-food-key-1",
        },
    )
    assert preview.status_code == 201
    draft = preview.json()
    assert draft["status"] == "draft"
    assert len(draft["items"]) == 2
    assert any("250" in value for value in draft["visible_assumptions"])

    identity["telegram_id"] = 2002
    assert client.get(f"/api/v2/nutrition/{draft['id']}").status_code == 404
    identity["telegram_id"] = 1001

    confirmed = client.post(
        f"/api/v2/nutrition/{draft['id']}/confirm",
        json={"version": draft["version"]},
    )
    assert confirmed.status_code == 200
    confirmed_data = confirmed.json()
    assert confirmed_data["status"] == "confirmed"

    item = confirmed_data["items"][0]
    edited = client.patch(
        f"/api/v2/nutrition/{draft['id']}/items/{item['id']}",
        json={
            "version": item["version"],
            "protein_grams": "25.000",
        },
    )
    assert edited.status_code == 200
    assert edited.json()["user_modified"] is True
    local_date = edited.json()["user_local_date"]
    summary = client.get(
        "/api/v2/nutrition/summary",
        params={"start_date": local_date, "end_date": local_date},
    )
    assert summary.status_code == 200
    assert summary.json()["confirmed_meals"] == 1

    preferences = client.get("/api/v2/nutrition/preferences").json()
    targets = client.patch(
        "/api/v2/nutrition/preferences",
        json={
            "version": preferences["version"],
            "calorie_target": "2000",
            "protein_target_grams": "100",
        },
    )
    assert targets.status_code == 200
    assert targets.json()["calorie_target"] == "2000.00"
    assert client.delete(f"/api/v2/nutrition/{draft['id']}").status_code == 204


def test_nutrition_provider_failure_preserves_draft(
    api_client,
    monkeypatch,
):
    client, _ = api_client

    class Unavailable:
        def estimate(self, description, **kwargs):
            del description, kwargs
            raise NutritionProviderUnavailable("timeout")

    monkeypatch.setattr(
        public_api,
        "get_nutrition_provider",
        lambda name: Unavailable(),
    )
    response = client.post(
        "/api/v2/nutrition",
        json={"original_text": "100 g paneer", "timezone": "UTC"},
    )
    assert response.status_code == 201
    assert response.json()["original_text"] == "100 g paneer"
    assert response.json()["estimation_source"] == "provider_unavailable"
