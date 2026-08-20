"""A floor on how often something may be asked.

Two callers now need this and they need it for the same reason, which is why it moved here
rather than being written twice: both NSE and Screener are free services this platform reads
without an agreement, and the documented hazard with both is being blocked for asking too
often. A limiter in each module would be two places to get the threading wrong.

Deliberately a *minimum interval* rather than a token bucket. A bucket allows a burst, and a
burst is exactly the access pattern that gets an IP blocked — the platform has no need to go
fast, only to keep going.
"""

from __future__ import annotations

import threading
import time


class RateLimiter:
    """Blocks until at least ``min_interval`` has passed since the last call.

    Thread-safe because the sources that use it are shared objects and a scan may fan out.
    """

    def __init__(self, min_interval_seconds: float) -> None:
        self._min_interval = max(0.0, min_interval_seconds)
        self._lock = threading.Lock()
        self._last = 0.0

    def wait(self) -> None:
        if self._min_interval <= 0:
            return
        with self._lock:
            gap = time.monotonic() - self._last
            if gap < self._min_interval:
                time.sleep(self._min_interval - gap)
            self._last = time.monotonic()
