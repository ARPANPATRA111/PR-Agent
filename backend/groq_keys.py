"""Shared rotation across several Groq credentials.

One API key serving every user is the tightest ceiling in the deployment: the
provider's per-organisation rate limits are shared, so a handful of concurrent
users can make every request fail at once. Adding keys raises that ceiling
without restricting anybody, which is the point — a refusal is a worse outcome
than a slower request.

The pool round-robins so no single key absorbs a burst, and briefly sidelines a
key that has just been rate-limited. It deliberately never runs out: if every
key is cooling down it returns the one that has been resting longest rather
than raising, because failing closed here would be exactly the "app is not
responding" behaviour this is meant to avoid.
"""

from __future__ import annotations

from itertools import cycle
import logging
from threading import Lock
import time

from config import settings

logger = logging.getLogger(__name__)

# How long a key rests after the provider reports rate limiting. Short enough
# that capacity returns quickly, long enough to let a burst drain.
RATE_LIMIT_COOLDOWN_SECONDS = 20.0


class GroqKeyPool:
    """Thread-safe rotation over one or more Groq credentials."""

    def __init__(self, keys: list[str]):
        deduplicated: list[str] = []
        for key in keys:
            cleaned = key.strip()
            if cleaned and cleaned not in deduplicated:
                deduplicated.append(cleaned)
        if not deduplicated:
            raise ValueError("At least one Groq credential is required")
        self._keys = deduplicated
        self._cycle = cycle(range(len(self._keys)))
        self._resting_until: dict[str, float] = {}
        self._lock = Lock()

    def __len__(self) -> int:
        return len(self._keys)

    @property
    def size(self) -> int:
        return len(self._keys)

    def acquire(self) -> str:
        """Return the next usable key, preferring one that is not resting."""
        now = time.monotonic()
        with self._lock:
            for _ in range(len(self._keys)):
                key = self._keys[next(self._cycle)]
                if self._resting_until.get(key, 0.0) <= now:
                    return key
            # Everything is cooling down. Use whichever rests soonest rather
            # than refusing the user outright.
            return min(self._keys, key=lambda key: self._resting_until.get(key, 0.0))

    def penalise(self, key: str, seconds: float = RATE_LIMIT_COOLDOWN_SECONDS) -> None:
        """Sideline a key that the provider has just rate-limited."""
        with self._lock:
            self._resting_until[key] = time.monotonic() + seconds
        logger.warning(
            "Groq credential rate limited; rotating",
            extra={"groq_pool_size": len(self._keys), "cooldown_seconds": seconds},
        )

    def alternatives(self, exclude: str) -> list[str]:
        """Other keys worth trying after `exclude` failed, soonest-free first."""
        with self._lock:
            others = [key for key in self._keys if key != exclude]
            return sorted(others, key=lambda key: self._resting_until.get(key, 0.0))


def configured_groq_keys() -> list[str]:
    """Collect every configured credential, primary first, in order."""
    keys = [settings.groq_api_key]
    keys.extend(settings.groq_api_keys.split(","))
    return [key.strip() for key in keys if key and key.strip()]


_pool: GroqKeyPool | None = None
_pool_signature: tuple[str, ...] = ()
_pool_lock = Lock()


def get_groq_key_pool() -> GroqKeyPool:
    """Return the process-wide pool, rebuilding it if configuration changed."""
    global _pool, _pool_signature
    keys = configured_groq_keys()
    signature = tuple(keys)
    with _pool_lock:
        if _pool is None or signature != _pool_signature:
            _pool = GroqKeyPool(keys)
            _pool_signature = signature
            logger.info(
                "Groq credential pool initialised",
                extra={"groq_pool_size": _pool.size},
            )
        return _pool


def is_rate_limited(exc: Exception) -> bool:
    """Identify a provider refusal that another credential could satisfy."""
    status_code = getattr(exc, "status_code", None)
    if status_code == 429:
        return True
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        error = body.get("error", body)
        if isinstance(error, dict):
            code = str(error.get("code") or error.get("type") or "").lower()
            if "rate_limit" in code or "quota" in code:
                return True
    return False
