from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import api.private_vault as vault_api
from auth import TokenData, get_current_user
from config import settings
from domain.errors import DomainError
from public_models import PrivateFact, PrivateFactAudit, PublicBase
from vault_crypto import VaultCipher, VaultDecryptionError


def _client(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, record):
        del record
        connection.execute("PRAGMA foreign_keys=ON")

    PublicBase.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    class Memory:
        SessionLocal = factory

    identity = {"telegram_id": 1001, "issued_at": datetime.now(timezone.utc)}

    async def user():
        return TokenData(
            user_id=1,
            telegram_id=identity["telegram_id"],
            username="vault_test",
            csrf_token="csrf",
            exp=datetime.now(timezone.utc) + timedelta(minutes=5),
            issued_at=identity["issued_at"],
            jti="test-session",
        )

    monkeypatch.setattr(vault_api, "get_memory_manager", lambda: Memory())
    monkeypatch.setattr(settings, "vault_enabled", True)
    monkeypatch.setattr(
        settings,
        "vault_encryption_keys",
        "primary:a2tra2tra2tra2tra2tra2tra2tra2tra2tra2tra2s=",
    )
    app = FastAPI()
    app.include_router(vault_api.router)
    app.dependency_overrides[get_current_user] = user

    @app.exception_handler(DomainError)
    async def domain_error(request: Request, exc: DomainError):
        del request
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.public_message},
        )

    return TestClient(app), identity, factory, engine


def test_vault_encrypts_masks_reveals_and_audits(monkeypatch):
    client, identity, factory, engine = _client(monkeypatch)
    payload = {
        "fact_type": "bank_account",
        "label": "SBI scholarship account",
        "value": "123456789012",
        "notes": "Main branch",
        "acknowledge_sensitive_storage": True,
    }
    created = client.post("/api/v2/private-facts", json=payload)
    assert created.status_code == 201
    record = created.json()
    assert record["masked_value"] == "••••••9012"
    assert "value" not in record

    session = factory()
    row = session.query(PrivateFact).one()
    assert b"123456789012" not in row.ciphertext
    assert row.nonce != b""
    session.close()

    revealed = client.post(f"/api/v2/private-facts/{record['id']}/reveal")
    assert revealed.status_code == 200
    assert revealed.json()["value"] == payload["value"]
    assert revealed.json()["notes"] == "Main branch"

    session = factory()
    assert [row.action for row in session.query(PrivateFactAudit).all()] == [
        "create",
        "reveal",
    ]
    session.close()
    engine.dispose()


def test_vault_is_tenant_scoped_and_requires_recent_auth(monkeypatch):
    client, identity, factory, engine = _client(monkeypatch)
    created = client.post(
        "/api/v2/private-facts",
        json={
            "fact_type": "academic_score",
            "label": "Semester 4 CGPA",
            "value": "8.72",
            "acknowledge_sensitive_storage": True,
        },
    ).json()
    identity["telegram_id"] = 2002
    assert client.get("/api/v2/private-facts").json() == []
    assert (
        client.post(f"/api/v2/private-facts/{created['id']}/reveal").status_code == 404
    )

    identity["telegram_id"] = 1001
    identity["issued_at"] = datetime.now(timezone.utc) - timedelta(minutes=10)
    assert (
        client.post(f"/api/v2/private-facts/{created['id']}/reveal").status_code == 401
    )
    engine.dispose()


def test_vault_rejects_full_aadhaar_and_unsupported_secrets(monkeypatch):
    client, identity, factory, engine = _client(monkeypatch)
    base = {"acknowledge_sensitive_storage": True}
    full_aadhaar = client.post(
        "/api/v2/private-facts",
        json={
            **base,
            "fact_type": "other_permitted",
            "label": "Government ID",
            "value": "1234 5678 9012",
        },
    )
    password = client.post(
        "/api/v2/private-facts",
        json={
            **base,
            "fact_type": "other_permitted",
            "label": "Email password",
            "value": "not-safe-here",
        },
    )
    assert full_aadhaar.status_code == password.status_code == 422
    leaked_label = client.post(
        "/api/v2/private-facts",
        json={
            **base,
            "fact_type": "other_permitted",
            "label": "Account 123456789",
            "value": "safe-value-field",
        },
    )
    assert leaked_label.status_code == 422
    engine.dispose()


def test_cipher_detects_tampering():
    cipher = VaultCipher("v1:a2tra2tra2tra2tra2tra2tra2tra2tra2tra2tra2s=")
    encrypted = cipher.encrypt(
        {"value": "secret", "notes": None},
        owner_id=1,
        record_uuid="uuid",
        fact_type="other_permitted",
    )
    damaged = bytes([encrypted.ciphertext[0] ^ 1]) + encrypted.ciphertext[1:]
    try:
        cipher.decrypt(
            ciphertext=damaged,
            nonce=encrypted.nonce,
            key_id=encrypted.key_id,
            owner_id=1,
            record_uuid="uuid",
            fact_type="other_permitted",
        )
    except VaultDecryptionError:
        pass
    else:
        raise AssertionError("Tampering should fail authenticated decryption")
