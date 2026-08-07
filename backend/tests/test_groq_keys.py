"""Rotation across several Groq credentials."""

from __future__ import annotations

import pytest

from config import settings
from groq_keys import (
    GroqKeyPool,
    configured_groq_keys,
    get_groq_key_pool,
    is_rate_limited,
)


class RateLimitError(Exception):
    def __init__(self, status_code=429, body=None):
        super().__init__("rate limited")
        self.status_code = status_code
        self.body = body


def test_a_single_key_is_always_returned():
    pool = GroqKeyPool(["key-one"])

    assert pool.acquire() == "key-one"
    assert pool.acquire() == "key-one"
    assert pool.size == 1


def test_requests_spread_across_keys():
    """Round-robin delays hitting any one key's rate limit."""
    pool = GroqKeyPool(["key-one", "key-two", "key-three"])

    seen = {pool.acquire() for _ in range(6)}

    assert seen == {"key-one", "key-two", "key-three"}


def test_blank_and_duplicate_keys_are_dropped():
    pool = GroqKeyPool(["key-one", "  ", "key-one", " key-two "])

    assert pool.size == 2
    assert {pool.acquire() for _ in range(4)} == {"key-one", "key-two"}


def test_an_empty_pool_is_rejected():
    with pytest.raises(ValueError):
        GroqKeyPool(["", "   "])


def test_a_rate_limited_key_is_skipped():
    pool = GroqKeyPool(["key-one", "key-two"])
    pool.penalise("key-one", seconds=60)

    assert {pool.acquire() for _ in range(4)} == {"key-two"}


def test_the_pool_never_refuses_when_all_keys_are_resting():
    """Failing closed here would be the outage this pool exists to prevent."""
    pool = GroqKeyPool(["key-one", "key-two"])
    pool.penalise("key-one", seconds=60)
    pool.penalise("key-two", seconds=60)

    assert pool.acquire() in {"key-one", "key-two"}


def test_a_cooldown_expires():
    pool = GroqKeyPool(["key-one", "key-two"])
    pool.penalise("key-one", seconds=-1)

    assert {pool.acquire() for _ in range(4)} == {"key-one", "key-two"}


def test_alternatives_exclude_the_failed_key():
    pool = GroqKeyPool(["key-one", "key-two", "key-three"])

    assert set(pool.alternatives("key-two")) == {"key-one", "key-three"}


def test_alternatives_put_the_soonest_free_key_first():
    pool = GroqKeyPool(["key-one", "key-two", "key-three"])
    pool.penalise("key-two", seconds=60)

    assert pool.alternatives("key-one") == ["key-three", "key-two"]


def test_rate_limit_detection_by_status_code():
    assert is_rate_limited(RateLimitError(status_code=429)) is True
    assert is_rate_limited(RateLimitError(status_code=500)) is False


def test_rate_limit_detection_by_error_body():
    exc = RateLimitError(
        status_code=400,
        body={"error": {"code": "rate_limit_exceeded"}},
    )

    assert is_rate_limited(exc) is True


def test_an_ordinary_failure_is_not_a_rate_limit():
    assert is_rate_limited(ValueError("bad request")) is False


def test_configuration_collects_primary_and_extra_keys(monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "primary")
    monkeypatch.setattr(settings, "groq_api_keys", "second, third ,")

    assert configured_groq_keys() == ["primary", "second", "third"]


def test_configuration_tolerates_an_empty_extra_list(monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "primary")
    monkeypatch.setattr(settings, "groq_api_keys", "")

    assert configured_groq_keys() == ["primary"]


def test_extra_keys_alone_are_enough(monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "")
    monkeypatch.setattr(settings, "groq_api_keys", "only-one")

    assert configured_groq_keys() == ["only-one"]


def test_the_shared_pool_rebuilds_when_configuration_changes(monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "primary")
    monkeypatch.setattr(settings, "groq_api_keys", "")
    assert get_groq_key_pool().size == 1

    monkeypatch.setattr(settings, "groq_api_keys", "second,third")

    assert get_groq_key_pool().size == 3
