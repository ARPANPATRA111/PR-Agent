"""Beta access, quotas, and bounded voice regression tests."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from abuse_controls import (
    InvalidInvite,
    InviteService,
    QuotaExceeded,
    QuotaService,
)
from config import settings
from domain.errors import DomainError
from domain.schemas import NoteCreate
from domain.services import DomainServices
from public_models import PublicBase, RateLimitBucket
from utils import transcribe_telegram_voice, validate_voice_metadata

UTC = timezone.utc


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    PublicBase.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    engine.dispose()


def test_invites_are_hashed_expiring_and_single_claimant(session_factory):
    with session_factory.begin() as session:
        alice = DomainServices(session).ensure_owner(
            telegram_id=101,
            first_name="Alice",
        )
        bob = DomainServices(session).ensure_owner(
            telegram_id=102,
            first_name="Bob",
        )
        record, code = InviteService(session).create(
            expires_at_utc=datetime.now(UTC) + timedelta(days=1)
        )
        assert code not in record.code_hash
        InviteService(session).claim(alice.id, code)
        assert InviteService(session).has_access(alice.id)
        with pytest.raises(InvalidInvite):
            InviteService(session).claim(bob.id, code)

    with session_factory.begin() as session:
        expired, expired_code = InviteService(session).create(
            expires_at_utc=datetime.now(UTC) - timedelta(seconds=1)
        )
        assert expired.code_hash != expired_code
        with pytest.raises(InvalidInvite):
            InviteService(session).claim(alice.id, expired_code)


def test_quota_is_per_owner_and_idempotently_rejects_overage(session_factory):
    with session_factory.begin() as session:
        service = DomainServices(session)
        alice = service.ensure_owner(telegram_id=201, first_name="Alice")
        bob = service.ensure_owner(telegram_id=202, first_name="Bob")
        quota = QuotaService(session)
        assert quota.require(alice.id, "test", limit=2) == 1
        assert quota.require(alice.id, "test", limit=2) == 0
        with pytest.raises(QuotaExceeded):
            quota.require(alice.id, "test", limit=2)
        assert quota.require(bob.id, "test", limit=2) == 1
        assert session.query(RateLimitBucket).count() == 2


def test_configured_text_limit_is_enforced(
    session_factory,
    monkeypatch,
):
    monkeypatch.setattr(settings, "max_text_entry_length", 64)
    with session_factory.begin() as session:
        owner = DomainServices(session).ensure_owner(
            telegram_id=301,
            first_name="Alice",
        )
        with pytest.raises(DomainError):
            DomainServices(session).create_note(
                owner.id,
                NoteCreate(body="x" * 65),
            )


def test_voice_metadata_limits(monkeypatch):
    monkeypatch.setattr(settings, "max_voice_duration_seconds", 60)
    monkeypatch.setattr(settings, "max_voice_file_size", 1024)
    validate_voice_metadata(
        duration_seconds=10,
        file_size=100,
        mime_type="audio/ogg",
    )
    with pytest.raises(ValueError):
        validate_voice_metadata(
            duration_seconds=61,
            file_size=100,
            mime_type="audio/ogg",
        )
    with pytest.raises(ValueError):
        validate_voice_metadata(
            duration_seconds=10,
            file_size=1025,
            mime_type="audio/ogg",
        )
    with pytest.raises(ValueError):
        validate_voice_metadata(
            duration_seconds=10,
            file_size=100,
            mime_type="application/octet-stream",
        )


def test_groq_upload_descriptor_normalizes_telegram_oga():
    import utils

    assert utils.groq_audio_upload_descriptor("/tmp/telegram-voice.oga") == (
        "voice.ogg",
        "audio/ogg",
    )
    assert utils.groq_audio_upload_descriptor("/tmp/telegram-voice.opus") == (
        "voice.opus",
        "audio/opus",
    )


@pytest.mark.asyncio
async def test_voice_temp_file_is_deleted_after_provider_failure(
    tmp_path,
    monkeypatch,
):
    import utils

    monkeypatch.setattr(settings, "audio_temp_dir", str(tmp_path))

    async def fake_download(file_id, bot_token):
        del file_id, bot_token
        return ".ogg", b"bounded-audio"

    async def fail_transcription(path):
        assert path
        raise RuntimeError("provider failed")

    monkeypatch.setattr(utils, "download_telegram_audio", fake_download)
    monkeypatch.setattr(utils, "transcribe_audio_groq", fail_transcription)
    with pytest.raises(RuntimeError):
        await transcribe_telegram_voice("file", "token")
    assert list(tmp_path.iterdir()) == []
