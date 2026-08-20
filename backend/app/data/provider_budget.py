"""A hard cap on requests to a metered data provider.

The same posture as `llm.budget.DailyBudget`, for the same reason and with one difference that
matters: model spend is money, and going over costs more than planned. A provider quota is a
*count*, and going over does not cost more — it stops the platform working for the rest of the
month. So this refuses earlier and more bluntly.

**Persisted, not in-process.** A monthly allowance that resets when uvicorn restarts is not an
allowance. The counter is a table, and the question it answers — "how many requests have I made
to this provider since the calendar month began, in IST" — is a single indexed count.

Refusal is an ordinary result. `IndianApiFinancialsSource` turns it into an empty answer with a
reason, exactly as it does for a missing key, and every caller already handles that.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.clock import now_ist, now_utc
from app.persistence.models import ProviderRequest

log = logging.getLogger(__name__)


def month_start_utc(moment: datetime | None = None) -> datetime:
    """First instant of the current IST calendar month, as UTC.

    IST because the operator reads their quota on an Indian billing cycle, and a month that
    turned over at 05:30 local would be a confusing thing to explain to someone who had just
    watched their allowance reset mid-morning.
    """
    ist = (moment or now_ist()).astimezone(now_ist().tzinfo)
    return ist.replace(day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(
        now_utc().tzinfo
    )


@dataclass(frozen=True, slots=True)
class BudgetState:
    provider: str
    used: int
    limit: int | None

    @property
    def remaining(self) -> int | None:
        return None if self.limit is None else max(0, self.limit - self.used)

    @property
    def exhausted(self) -> bool:
        return self.limit is not None and self.used >= self.limit

    def as_dict(self) -> dict[str, int | str | None]:
        return {
            "provider": self.provider,
            "used": self.used,
            "limit": self.limit,
            "remaining": self.remaining,
        }


class MonthlyRequestBudget:
    """Counts requests against a monthly cap, and refuses once it is reached."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        provider: str,
        limit: int | None,
    ) -> None:
        self._sessions = session_factory
        self._provider = provider
        self._limit = limit

    def used(self) -> int:
        with self._sessions() as session:
            return int(
                session.execute(
                    select(func.count(ProviderRequest.id)).where(
                        ProviderRequest.provider == self._provider,
                        ProviderRequest.requested_at >= month_start_utc(),
                    )
                ).scalar_one()
            )

    def state(self) -> BudgetState:
        return BudgetState(provider=self._provider, used=self.used(), limit=self._limit)

    def allow(self, detail: str = "") -> bool:
        """Reserve one request. Records it only when it is granted.

        Counted on the way *out*, before the call rather than after it: a request that was
        made and then failed still consumed the allowance, and a counter that only recorded
        successes would drift under exactly the conditions that make the allowance matter.
        """
        if self._limit is None:
            self._record(detail)
            return True

        if self.used() >= self._limit:
            return False

        self._record(detail)
        return True

    def _record(self, detail: str) -> None:
        with self._sessions() as session:
            session.add(
                ProviderRequest(
                    provider=self._provider,
                    detail=detail[:200] or None,
                    requested_at=now_utc(),
                )
            )
            session.commit()
