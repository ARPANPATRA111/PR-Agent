"""Application-layer authenticated encryption for the private facts vault."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class VaultConfigurationError(RuntimeError):
    pass


class VaultDecryptionError(RuntimeError):
    pass


@dataclass(frozen=True)
class EncryptedValue:
    ciphertext: bytes
    nonce: bytes
    key_id: str


class VaultCipher:
    """AES-256-GCM key ring with the first configured key used for writes."""

    def __init__(self, encoded_keys: str):
        keys: dict[str, bytes] = {}
        order: list[str] = []
        for raw_entry in encoded_keys.split(","):
            entry = raw_entry.strip()
            if not entry:
                continue
            try:
                key_id, encoded = entry.split(":", 1)
                key_id = key_id.strip()
                if not key_id or len(key_id) > 32:
                    raise ValueError
                key = base64.urlsafe_b64decode(encoded.strip().encode("ascii"))
            except (ValueError, UnicodeEncodeError) as exc:
                raise VaultConfigurationError(
                    "Invalid vault key configuration"
                ) from exc
            if len(key) != 32 or key_id in keys:
                raise VaultConfigurationError("Invalid vault key configuration")
            keys[key_id] = key
            order.append(key_id)
        if not order:
            raise VaultConfigurationError("No vault encryption key is configured")
        self._keys = keys
        self.active_key_id = order[0]

    @staticmethod
    def associated_data(owner_id: int, record_uuid: str, fact_type: str) -> bytes:
        return f"pr-agent-vault:v1:{owner_id}:{record_uuid}:{fact_type}".encode()

    def encrypt(
        self,
        payload: dict[str, str | None],
        *,
        owner_id: int,
        record_uuid: str,
        fact_type: str,
    ) -> EncryptedValue:
        import os

        nonce = os.urandom(12)
        plaintext = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        ciphertext = AESGCM(self._keys[self.active_key_id]).encrypt(
            nonce,
            plaintext,
            self.associated_data(owner_id, record_uuid, fact_type),
        )
        return EncryptedValue(ciphertext, nonce, self.active_key_id)

    def decrypt(
        self,
        *,
        ciphertext: bytes,
        nonce: bytes,
        key_id: str,
        owner_id: int,
        record_uuid: str,
        fact_type: str,
    ) -> dict[str, str | None]:
        key = self._keys.get(key_id)
        if key is None:
            raise VaultDecryptionError("The encryption key is unavailable")
        try:
            plaintext = AESGCM(key).decrypt(
                nonce,
                ciphertext,
                self.associated_data(owner_id, record_uuid, fact_type),
            )
            payload = json.loads(plaintext.decode("utf-8"))
        except (InvalidTag, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise VaultDecryptionError("The encrypted value failed validation") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("value"), str):
            raise VaultDecryptionError("The encrypted value has an invalid format")
        return payload
