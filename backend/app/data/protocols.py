"""The seams strategies build against.

Everything downstream depends on these protocols, never on yfinance, requests or the parquet
cache. That is what lets a strategy be tested against a deterministic fake, and what lets the
provider be replaced without touching a strategy.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal, Protocol, runtime_checkable

from app.domain.instrument import Instrument
from app.domain.prices import Interval, PriceSeries


@runtime_checkable
class PriceSource(Protocol):
    """OHLCV history.

    ``history`` returns an empty series on any failure and never raises — the same rule the
    LLM gateway follows, for the same reason: one unavailable provider must not take down a
    whole scan.
    """

    def history(
        self,
        instrument: Instrument,
        *,
        interval: Interval = "1d",
        lookback_days: int = 400,
    ) -> PriceSeries: ...


@dataclass(frozen=True, slots=True)
class UniverseSnapshot:
    """The instruments in scope at a point in time, and how that list was obtained."""

    instruments: tuple[Instrument, ...]
    #: ``live`` came from the index source; ``fallback`` from the bundled list. A universe
    #: that silently shrank to the fallback is otherwise indistinguishable from a real
    #: index change.
    origin: Literal["live", "fallback"]
    index_name: str
    #: Blocklisted symbols removed from this snapshot, kept for the record.
    excluded: tuple[str, ...] = ()

    def __len__(self) -> int:
        return len(self.instruments)

    @property
    def symbols(self) -> tuple[str, ...]:
        return tuple(instrument.symbol for instrument in self.instruments)


@runtime_checkable
class UniverseSource(Protocol):
    """Which instruments exist."""

    def snapshot(self) -> UniverseSnapshot: ...


class CalendarNotCovered(LookupError):
    """The holiday data has nothing to say about this year.

    Raised rather than guessed at: warning and then returning "not a holiday"
    which silently turns every holiday in an uncovered year into a trading day.
    """

    def __init__(self, year: int, covered: tuple[int, ...]) -> None:
        span = f"{min(covered)}–{max(covered)}" if covered else "nothing"
        super().__init__(
            f"NSE holiday data does not cover {year} (covers {span}). "
            "Update app/data/resources/nse_holidays.json."
        )
        self.year = year
        self.covered = covered


@runtime_checkable
class MarketCalendar(Protocol):
    """NSE trading days and session hours."""

    def covers(self, year: int) -> bool: ...

    def is_trading_day(self, day: date) -> bool: ...

    def previous_trading_day(self, day: date) -> date: ...
