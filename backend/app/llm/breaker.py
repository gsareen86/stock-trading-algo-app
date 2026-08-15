"""Per-provider circuit breaker.

Carried over from the predecessor's ``llm/client.py``, which had this one genuinely good
idea: after repeated rate-limit failures, continuing to call the provider wastes seconds of
every cycle and burns whatever rate-limit budget remains. The breaker opens and calls
short-circuit until a cooldown elapses.

Only *rate-limit* failures trip it. A malformed prompt failing repeatedly is a bug to fix,
not a provider to back off from, and folding both into one counter would hide it.
"""

from __future__ import annotations

import logging
import threading
import time

log = logging.getLogger(__name__)


class CircuitBreaker:
    """Tracks consecutive rate-limit failures per provider. Thread-safe."""

    def __init__(self, threshold: int = 3, cooldown_seconds: float = 600.0) -> None:
        self._threshold = threshold
        self._cooldown = cooldown_seconds
        self._lock = threading.Lock()
        self._consecutive: dict[str, int] = {}
        self._open_until: dict[str, float] = {}

    def is_open(self, provider: str) -> bool:
        """True when calls to ``provider`` should short-circuit."""
        with self._lock:
            until = self._open_until.get(provider, 0.0)
            if until and time.monotonic() >= until:
                # Cooldown elapsed — close and let the next call probe the provider.
                self._open_until.pop(provider, None)
                self._consecutive[provider] = 0
                log.info("circuit breaker closed for %s after cooldown", provider)
                return False
            return bool(until)

    def record_rate_limit(self, provider: str) -> None:
        with self._lock:
            count = self._consecutive.get(provider, 0) + 1
            self._consecutive[provider] = count
            if count >= self._threshold and provider not in self._open_until:
                self._open_until[provider] = time.monotonic() + self._cooldown
                log.warning(
                    "circuit breaker opened for %s after %d consecutive rate limits; "
                    "cooling down %.0fs",
                    provider,
                    count,
                    self._cooldown,
                )

    def record_success(self, provider: str) -> None:
        with self._lock:
            self._consecutive[provider] = 0
            self._open_until.pop(provider, None)

    def reset(self) -> None:
        with self._lock:
            self._consecutive.clear()
            self._open_until.clear()
