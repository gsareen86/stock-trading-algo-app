"""What something is trading at right now.

Deliberately **not** a bar. A `PriceSeries` is settled history that a strategy reasons over; a
quote is a reading taken at a moment, and the two must never be confused. A quote appended to a
series would make a verdict irreproducible — the same strategy over the same instrument would
answer differently a minute later, with nothing in the evidence to say why. `market-data`'s
"a live quote never enters a historical series" is that rule, and this type existing separately
is what makes it enforceable rather than merely intended.

So a quote marks a position, drives the market panel and timestamps freshness. It is never an
input to a stance.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Quote:
    """One reading, and enough context to know what it is worth.

    `previous_close` travels with it because a level on its own answers nothing a reader
    asked — "24,231" is not information until it is next to "from 24,078".
    """

    symbol: str
    last: float
    previous_close: float | None
    #: When the reading was taken, not when it was requested.
    observed_at: datetime
    #: Which provider said so. A cached reading says `cache`, exactly as `PriceSeries` does.
    source: str

    @property
    def change(self) -> float | None:
        if self.previous_close is None:
            return None
        return self.last - self.previous_close

    @property
    def change_pct(self) -> float | None:
        if not self.previous_close:
            return None
        return (self.last - self.previous_close) / self.previous_close * 100


@dataclass(frozen=True, slots=True)
class IndexQuote:
    """An index reading, with the extras the exchange publishes alongside it.

    The trailing-return and breadth fields are here because NSE returns them in the same
    payload as the level, and refetching what has already arrived would be a request spent for
    nothing. They are *reported*, not computed here — anything derived from them says so at
    the point it derives it.
    """

    quote: Quote
    #: The exchange's own name, e.g. ``NIFTY 500``.
    name: str
    change_30d_pct: float | None = None
    change_365d_pct: float | None = None
    #: Constituents up, down and flat today. Breadth is a property of an index that a level
    #: cannot express: an index up 0.6% on 39 advances reads differently from one up 0.6% on 8.
    advances: int | None = None
    declines: int | None = None
    unchanged: int | None = None
    year_high: float | None = None
    year_low: float | None = None

    @property
    def symbol(self) -> str:
        return self.quote.symbol
