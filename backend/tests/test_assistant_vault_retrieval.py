"""Natural-language vault lookup keeps identity and decryption in trusted code."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from assistant import ActorContext, BoundedAssistant
from config import settings
from domain.services import DomainServices
from nutrition.providers import get_nutrition_provider
from public_models import AgentPendingAction, PrivateFact, PrivateFactAudit, PublicBase
from vault_crypto import VaultCipher

ALICE = ActorContext(telegram_id=101, first_name="Alice")
BOB = ActorContext(telegram_id=202, first_name="Bob")
KEYS = "primary:a2tra2tra2tra2tra2tra2tra2tra2tra2tra2tra2s="


class FakeProvider:
    provider_name = "fake"
    model_name = "test"

    def __init__(self, label: str):
        self.label = label

    def classify(self, text, *, context=None):
        del text, context
        return {
            "confidence": 0.99,
            "actions": [{"kind": "retrieve_private_fact", "label": self.label}],
        }


@pytest.fixture()
def vault_db(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, record):
        del record
        connection.execute("PRAGMA foreign_keys=ON")

    PublicBase.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(settings, "vault_encryption_keys", KEYS)
    monkeypatch.setattr(settings, "vault_enabled", True)
    yield factory
    engine.dispose()


def seed_fact(factory, actor: ActorContext, label: str, value: str) -> int:
    with factory() as session:
        owner = DomainServices(session).ensure_owner(
            telegram_id=actor.telegram_id,
            first_name=actor.first_name,
        )
        record_uuid = str(uuid.uuid4())
        encrypted = VaultCipher(KEYS).encrypt(
            {"value": value, "notes": None},
            owner_id=owner.id,
            record_uuid=record_uuid,
            fact_type="academic_score",
        )
        row = PrivateFact(
            owner_id=owner.id,
            record_uuid=record_uuid,
            fact_type="academic_score",
            label=label,
            masked_value="Stored score",
            ciphertext=encrypted.ciphertext,
            nonce=encrypted.nonce,
            key_id=encrypted.key_id,
        )
        session.add(row)
        session.commit()
        return row.id


def build(factory, label: str) -> BoundedAssistant:
    return BoundedAssistant(
        factory,
        FakeProvider(label),
        get_nutrition_provider("reference"),
    )


def test_vault_value_is_revealed_only_after_owner_confirmation(vault_db):
    alice_id = seed_fact(vault_db, ALICE, "Sixth semester CGPA", "8.74")
    seed_fact(vault_db, BOB, "Sixth semester CGPA", "9.99")
    assistant = build(vault_db, "Sixth semester CGPA")

    review = assistant.handle(ALICE, "what is my sixth semester CGPA", update_id=1)
    assert review.status == "confirmation"
    assert "8.74" not in review.text
    assert "Stored score" in review.text

    revealed = assistant.confirm(ALICE, review.pending_id)
    assert revealed.status == "completed"
    assert "8.74" in revealed.text
    assert "9.99" not in revealed.text
    with vault_db() as session:
        audit = session.query(PrivateFactAudit).one()
        assert audit.channel == "telegram"
        assert audit.owner_id == session.get(PrivateFact, alice_id).owner_id


def test_cancelling_vault_reveal_never_decrypts(vault_db):
    seed_fact(vault_db, ALICE, "SBI account", "123456789012")
    assistant = build(vault_db, "SBI account")

    review = assistant.handle(ALICE, "show my SBI account", update_id=2)
    assistant.cancel(ALICE, review.pending_id)

    with vault_db() as session:
        assert session.query(PrivateFactAudit).count() == 0


def test_vault_lookup_understands_mobile_number_alias(vault_db):
    seed_fact(vault_db, ALICE, "Mobile No.", "+919876543210")
    assistant = build(vault_db, "mobile number")

    review = assistant.handle(ALICE, "what is my mobile number", update_id=3)

    assert review.status == "confirmation"
    assert "Mobile No." in review.text


def test_explicit_voice_style_vault_save_is_encrypted_before_review(vault_db):
    class ProviderMustNotSeeSecret:
        provider_name = "forbidden"
        model_name = "forbidden"

        def classify(self, text, *, context=None):
            del text, context
            raise AssertionError("vault values must not reach the intent provider")

    assistant = BoundedAssistant(
        vault_db,
        ProviderMustNotSeeSecret(),
        get_nutrition_provider("reference"),
    )
    secret = "+91 98765 43210"

    review = assistant.handle(
        ALICE,
        f"save my mobile number as {secret} in my vault",
        update_id=4,
        review_required=True,
    )

    assert review.status == "confirmation"
    assert secret not in review.text
    with vault_db() as session:
        pending = session.query(AgentPendingAction).one()
        assert secret not in str(pending.proposed_arguments)
        assert session.query(PrivateFact).count() == 0

    saved = assistant.confirm(ALICE, review.pending_id)
    assert saved.status == "completed"
    with vault_db() as session:
        row = session.query(PrivateFact).one()
        payload = VaultCipher(KEYS).decrypt(
            ciphertext=row.ciphertext,
            nonce=row.nonce,
            key_id=row.key_id,
            owner_id=row.owner_id,
            record_uuid=row.record_uuid,
            fact_type=row.fact_type,
        )
        assert payload["value"] == "+919876543210"
        assert session.query(PrivateFactAudit).one().channel == "telegram"
