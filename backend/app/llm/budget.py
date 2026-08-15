"""The daily spend guardrail.

A cap on what the platform may spend on paid providers within one **IST day** — the same day
boundary the market and every "as of" stamp use, so "today's spend" means the same thing in
the app as it does to the person reading it.

Three properties, each a decision rather than an accident:

* **Local models are exempt.** They cost nothing. A spend cap that disabled the one provider
  still able to answer for free would turn a budget breach into an outage.
* **It fails soft.** Over budget behaves like any other failure — the gateway returns ``None``
  and callers keep their non-LLM path. A spending limit, not a kill switch.
* **It is checked before dispatch.** A cap enforced after the money is spent is not a cap.

Spend is read from ``llm_calls`` once per IST day and then carried forward in memory,
incremented as calls complete. A ``SUM`` per request would put the database on the hot path of
every narrative the platform generates, to answer a question that changes by fractions of a
cent at a time.
"""

from __future__ import annotations

import logging
import threading
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.clock import now_ist
from app.persistence.models import LlmCall

log = logging.getLogger(__name__)


class DailyBudget:
    """Tracks spend against an optional daily cap. Thread-safe."""

    def __init__(
        self,
        session_factory: sessionmaker[Session] | None,
        cap_usd: float | None,
    ) -> None:
        self._session_factory = session_factory
        self._cap = cap_usd
        self._lock = threading.Lock()
        self._day: date | None = None
        self._spent: float = 0.0

    @property
    def cap_usd(self) -> float | None:
        return self._cap

    @property
    def enabled(self) -> bool:
        return self._cap is not None

    def spent_today(self) -> float:
        """Recorded spend for the current IST day."""
        with self._lock:
            self._refresh_if_new_day()
            return self._spent

    def remaining(self) -> float | None:
        """Headroom under the cap, or ``None`` when unlimited."""
        if self._cap is None:
            return None
        return max(0.0, self._cap - self.spent_today())

    def is_exhausted(self) -> bool:
        """Whether paid providers should be refused."""
        if self._cap is None:
            return False
        return self.spent_today() >= self._cap

    def add(self, cost_usd: float | None) -> None:
        """Record spend from a completed call.

        ``None`` means the provider reported no cost — a local model. It contributes nothing,
        which is exactly why local rungs stay usable after the cap is reached.
        """
        if not cost_usd:
            return
        with self._lock:
            self._refresh_if_new_day()
            self._spent += cost_usd

    # ── internals ─────────────────────────────────────────────────────────────
    def _refresh_if_new_day(self) -> None:
        """Reload from the database when the IST day rolls over. Caller holds the lock."""
        today = now_ist().date()
        if self._day == today:
            return
        self._day = today
        self._spent = self._load_spend(today)

    def _load_spend(self, day: date) -> float:
        if self._session_factory is None:
            return 0.0
        try:
            with self._session_factory() as session:
                # Filtering in Python on the IST date would mean loading the table; instead
                # bound the query by the UTC instants of the IST day.
                start_utc, end_utc = _ist_day_bounds_utc(day)
                total = session.execute(
                    select(func.coalesce(func.sum(LlmCall.cost_usd), 0.0)).where(
                        LlmCall.created_at >= start_utc,
                        LlmCall.created_at < end_utc,
                    )
                ).scalar_one()
                return float(total or 0.0)
        except Exception as exc:
            # Fail open: an unreadable ledger must not block every LLM call in the platform.
            # The alternative — treating "unknown spend" as "over budget" — turns a database
            # blip into a total outage of every explanation the app produces.
            log.warning("could not read today's LLM spend; treating as 0: %s", exc)
            return 0.0


def _ist_day_bounds_utc(day: date):
    """UTC instants bounding one IST calendar day."""
    from datetime import datetime, time

    from app.core.clock import IST, to_utc

    start_ist = datetime.combine(day, time.min, tzinfo=IST)
    end_ist = datetime.combine(day, time.max, tzinfo=IST)
    return to_utc(start_ist), to_utc(end_ist)
