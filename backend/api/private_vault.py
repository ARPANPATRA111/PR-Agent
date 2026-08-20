"""Mini App-only API for end-to-end masked, application-encrypted personal facts."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated, Generator, Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from auth import TokenData, get_current_user
from config import settings
from domain.errors import ConcurrentUpdate, RecordNotFound
from domain.services import DomainServices
from memory import get_memory_manager
from public_models import PrivateFact, PrivateFactAudit
from vault_crypto import VaultCipher, VaultConfigurationError, VaultDecryptionError
from vault_policy import FactType, VaultFactInput, mask_private_fact

router = APIRouter(prefix="/api/v2/private-facts", tags=["Private facts vault"])


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class FactCreate(VaultFactInput):
    acknowledge_sensitive_storage: Literal[True]


class FactUpdate(FactCreate):
    version: int = Field(ge=1)


class FactMasked(StrictSchema):
    id: int
    record_uuid: str
    fact_type: FactType
    label: str
    masked_value: str
    version: int
    created_at: datetime
    updated_at: datetime


class FactRevealed(FactMasked):
    value: str
    notes: str | None


class VaultContext:
    def __init__(self, session: Session, owner_id: int, current_user: TokenData):
        self.session = session
        self.owner_id = owner_id
        self.current_user = current_user


def get_vault_context(
    current_user: TokenData = Depends(get_current_user),
) -> Generator[VaultContext, None, None]:
    if not settings.vault_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Private facts vault is not enabled.",
        )
    memory = get_memory_manager()
    session = memory.SessionLocal()
    try:
        owner = DomainServices(session).ensure_owner(
            telegram_id=current_user.telegram_id,
            username=current_user.username,
        )
        yield VaultContext(session, owner.id, current_user)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


Context = Annotated[VaultContext, Depends(get_vault_context)]


def _cipher() -> VaultCipher:
    try:
        return VaultCipher(settings.vault_encryption_keys)
    except VaultConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Private facts vault encryption is unavailable.",
        ) from exc


def _require_recent_auth(user: TokenData) -> None:
    if user.issued_at is None:
        raise HTTPException(status_code=401, detail="Re-authentication required.")
    issued_at = user.issued_at
    if issued_at.tzinfo is None:
        issued_at = issued_at.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - issued_at).total_seconds()
    if age < -30 or age > settings.vault_recent_auth_seconds:
        raise HTTPException(status_code=401, detail="Re-authentication required.")


def _owned(context: VaultContext, record_id: int) -> PrivateFact:
    row = (
        context.session.query(PrivateFact)
        .filter(PrivateFact.id == record_id, PrivateFact.owner_id == context.owner_id)
        .one_or_none()
    )
    if row is None:
        raise RecordNotFound()
    return row


def _mask(fact_type: str, value: str) -> str:
    return mask_private_fact(fact_type, value)


def _masked(row: PrivateFact) -> FactMasked:
    return FactMasked.model_validate(row, from_attributes=True)


def _audit(context: VaultContext, row: PrivateFact, action: str) -> None:
    context.session.add(
        PrivateFactAudit(
            owner_id=context.owner_id,
            record_uuid=row.record_uuid,
            action=action,
            channel="mini_app",
        )
    )


@router.get("", response_model=list[FactMasked])
def list_facts(context: Context):
    rows = (
        context.session.query(PrivateFact)
        .filter(PrivateFact.owner_id == context.owner_id)
        .order_by(PrivateFact.updated_at.desc())
        .all()
    )
    return [_masked(row) for row in rows]


@router.post("", response_model=FactMasked, status_code=status.HTTP_201_CREATED)
def create_fact(data: FactCreate, context: Context):
    _require_recent_auth(context.current_user)
    record_uuid = str(uuid.uuid4())
    encrypted = _cipher().encrypt(
        {"value": data.value, "notes": data.notes},
        owner_id=context.owner_id,
        record_uuid=record_uuid,
        fact_type=data.fact_type,
    )
    row = PrivateFact(
        owner_id=context.owner_id,
        record_uuid=record_uuid,
        fact_type=data.fact_type,
        label=data.label,
        masked_value=_mask(data.fact_type, data.value),
        ciphertext=encrypted.ciphertext,
        nonce=encrypted.nonce,
        key_id=encrypted.key_id,
    )
    context.session.add(row)
    context.session.flush()
    _audit(context, row, "create")
    return _masked(row)


@router.put("/{record_id}", response_model=FactMasked)
def update_fact(record_id: int, data: FactUpdate, context: Context):
    _require_recent_auth(context.current_user)
    row = _owned(context, record_id)
    if row.version != data.version:
        raise ConcurrentUpdate()
    encrypted = _cipher().encrypt(
        {"value": data.value, "notes": data.notes},
        owner_id=context.owner_id,
        record_uuid=row.record_uuid,
        fact_type=data.fact_type,
    )
    row.fact_type = data.fact_type
    row.label = data.label
    row.masked_value = _mask(data.fact_type, data.value)
    row.ciphertext = encrypted.ciphertext
    row.nonce = encrypted.nonce
    row.key_id = encrypted.key_id
    row.version += 1
    _audit(context, row, "update")
    context.session.flush()
    return _masked(row)


@router.post("/{record_id}/reveal", response_model=FactRevealed)
def reveal_fact(record_id: int, context: Context):
    _require_recent_auth(context.current_user)
    row = _owned(context, record_id)
    try:
        payload = _cipher().decrypt(
            ciphertext=row.ciphertext,
            nonce=row.nonce,
            key_id=row.key_id,
            owner_id=context.owner_id,
            record_uuid=row.record_uuid,
            fact_type=row.fact_type,
        )
    except VaultDecryptionError as exc:
        raise HTTPException(
            status_code=500, detail="Private fact could not be decrypted."
        ) from exc
    _audit(context, row, "reveal")
    return FactRevealed(
        **_masked(row).model_dump(),
        value=str(payload["value"]),
        notes=payload.get("notes"),
    )


@router.delete("/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_fact(record_id: int, context: Context):
    _require_recent_auth(context.current_user)
    row = _owned(context, record_id)
    _audit(context, row, "delete")
    context.session.delete(row)
    context.session.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
