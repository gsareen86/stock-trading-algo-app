"""The seams strategies build against.

Everything downstream depends on these protocols, never on yfinance, requests or the parquet
cache. That is what lets a strategy be tested against a deterministic fake, and what lets the
provider be replaced without touching a strategy.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal, Protocol, runtime_checkable

from app.domain.financials import CompanyFinancials
from app.domain.instrument import Instrument
from app.domain.prices import Interval, PriceSeries
from app.domain.quotes import Quote


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


@runtime_checkable
class QuoteSource(Protocol):
    """What something is trading at now.

    Separate from `PriceSource` on purpose, and the separation is load-bearing rather than
    tidy: a quote must never reach a strategy. Verdicts are required to be reproducible with
    the model switched off (`project.md`, principle 5), and a reading that changes between two
    evaluations of the same settled bars would break that silently — the stance would move and
    no evidence row would say why.

    Returns ``None`` rather than raising, and ``None`` for an instrument it cannot quote. Not
    every provider can quote everything: NSE serves index levels to a plain client and refuses
    per-stock ones, so "I cannot answer that" is an ordinary result here, not a failure.
    """

    def quote(self, instrument: Instrument) -> Quote | None: ...


@runtime_checkable
class CompanyFinancialsSource(Protocol):
    """What kind of business a company is — statements, ratios and ownership.

    **A second, wider seam, deliberately not a widening of the first.** `FundamentalsSource`
    stays four fields wide because `fun_tech_momentum` needs quarterly EPS and revenue and
    nothing else; putting a hundred mostly-null fields in front of that strategy would be the
    speculative shape `market-data-foundation` avoided by deferring fundamentals at all.

    Returns an empty result naming a reason rather than raising — an absent API key, an
    exhausted monthly allowance and a throttled provider are all ordinary states here, and a
    scan must survive every one of them.
    """

    def financials(self, instrument: Instrument) -> CompanyFinancials: ...


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
