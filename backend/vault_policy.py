"""Shared validation and masking rules for encrypted private facts."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

FactType = Literal[
    "aadhaar_last4",
    "phone",
    "bank_account",
    "ifsc",
    "academic_score",
    "other_permitted",
]


class VaultFactInput(BaseModel):
    """A private vault value before it is encrypted by trusted code."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    fact_type: FactType
    label: str = Field(min_length=1, max_length=160)
    value: str = Field(min_length=1, max_length=2_000)
    notes: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def value_matches_type(self):
        compact = re.sub(r"[\s-]", "", self.value)
        if self.fact_type == "aadhaar_last4" and not re.fullmatch(r"\d{4}", compact):
            raise ValueError("Only the last four Aadhaar digits are accepted")
        if self.fact_type == "ifsc":
            normalized = compact.upper()
            if not re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}", normalized):
                raise ValueError("Enter a valid 11-character IFSC code")
            self.value = normalized
        elif self.fact_type == "phone":
            if not re.fullmatch(r"\+?[0-9]{7,15}", compact):
                raise ValueError("Enter a phone number with 7 to 15 digits")
            self.value = compact
        elif self.fact_type == "bank_account":
            normalized = compact.upper()
            if not re.fullmatch(r"[A-Z0-9]{6,34}", normalized):
                raise ValueError(
                    "Enter a bank account identifier with 6 to 34 characters"
                )
            self.value = normalized
        return self


def mask_private_fact(fact_type: str, value: str) -> str:
    compact = re.sub(r"\s", "", value)
    if fact_type == "aadhaar_last4":
        return f"•••• •••• {compact[-4:]}"
    if fact_type == "ifsc":
        return f"{compact[:4]}0••••••"
    if fact_type in {"phone", "bank_account"}:
        return f"••••••{compact[-4:]}"
    if fact_type == "academic_score":
        return "Stored score"
    return "Stored securely"
