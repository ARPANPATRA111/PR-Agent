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

    identity = {"telegram_id": 1001}

    async def authenticated_user():
        return TokenData(
            user_id=1,
            telegram_id=identity["telegram_id"],
            username=f"user_{identity['telegram_id']}",
            csrf_token="csrf",
            exp=datetime.now(timezone.utc) + timedelta(minutes=5),
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
