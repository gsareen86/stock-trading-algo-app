"""Quarterly fundamentals — deliberately four fields wide.

`market-data-foundation` deferred fundamentals because porting them then would have meant
speculating about a shape no caller had fixed. `fun_tech_momentum` now fixes it: it needs
quarterly EPS and revenue, most recent first, and nothing else.

So this is that, and not the predecessor's 361-line module — which also computed growth
buckets and quality scores. Those are *decisions*, they get rewritten from spec in
`screening-universe-and-gates`, and importing them here would smuggle old scoring assumptions
into a new strategy.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol, runtime_checkable

from app.domain.instrument import Instrument

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class QuarterPoint:
    period_end: date
    value: float


@dataclass(frozen=True, slots=True)
class QuarterlyFundamentals:
    """Reported quarters, **most recent first**.

    The ordering is part of the contract: every comparison the strategy makes is "latest
    versus something older", and a caller reversing the list is exactly the off-by-one that
    silently inverts a growth test.
    """

    symbol: str
    eps: tuple[QuarterPoint, ...] = ()
    revenue: tuple[QuarterPoint, ...] = ()
    source_ref: str = ""

    @property
    def is_empty(self) -> bool:
        return not self.eps and not self.revenue

    def eps_at(self, index: int) -> float | None:
        return self.eps[index].value if len(self.eps) > index else None

    def revenue_at(self, index: int) -> float | None:
        return self.revenue[index].value if len(self.revenue) > index else None


def empty(symbol: str) -> QuarterlyFundamentals:
    return QuarterlyFundamentals(symbol=symbol)


@runtime_checkable
class FundamentalsSource(Protocol):
    """Quarterly reported figures.

    Returns an empty result rather than raising, the same rule the price source follows: one
    unavailable provider must not end a scan.
    """

    def quarterly(self, instrument: Instrument) -> QuarterlyFundamentals: ...


class YFinanceFundamentalsSource:
    """Quarterly income-statement lines from yfinance."""

    def __init__(self, lookup=None) -> None:
        """``lookup`` is injectable so tests replay a recorded frame offline."""
        self._lookup = lookup

    def _fetch(self, ticker: str):
        if self._lookup is not None:
            return self._lookup(ticker)

        import yfinance as yf

        return yf.Ticker(ticker).quarterly_income_stmt

    @staticmethod
    def _series(frame, *candidates: str) -> tuple[QuarterPoint, ...]:
        """Pull a labelled row out of the income statement, newest column first."""
        if frame is None or getattr(frame, "empty", True):
            return ()
        labels = {str(i).strip().lower(): i for i in frame.index}
        for candidate in candidates:
            key = labels.get(candidate.lower())
            if key is None:
                continue
            row = frame.loc[key]
            points = []
            for column, value in row.items():
                try:
                    period = (
                        column.date()
                        if hasattr(column, "date")
                        else date.fromisoformat(str(column)[:10])
                    )
                    points.append(QuarterPoint(period_end=period, value=float(value)))
                except (TypeError, ValueError):
                    continue
            # yfinance orders columns newest-first, but sorting makes that independent of it.
            return tuple(sorted(points, key=lambda p: p.period_end, reverse=True))
        return ()

    def quarterly(self, instrument: Instrument) -> QuarterlyFundamentals:
        ticker = instrument.yf_ticker
        try:
            frame = self._fetch(ticker)
        except Exception as exc:
            log.debug("fundamentals fetch failed for %s: %s", instrument.symbol, exc)
            return empty(instrument.symbol)

        eps = self._series(frame, "Basic EPS", "Diluted EPS")
        revenue = self._series(frame, "Total Revenue", "Operating Revenue")
        if not eps and not revenue:
            return empty(instrument.symbol)

        return QuarterlyFundamentals(
            symbol=instrument.symbol,
            eps=eps,
            revenue=revenue,
            source_ref=f"fundamentals://yfinance/{ticker}?statement=quarterly_income",
        )


@dataclass
class StaticFundamentalsSource:
    """Serves supplied quarters — for tests and for the four-verdict demonstration."""

    data: dict[str, QuarterlyFundamentals] = field(default_factory=dict)

    def quarterly(self, instrument: Instrument) -> QuarterlyFundamentals:
        return self.data.get(instrument.symbol, empty(instrument.symbol))
