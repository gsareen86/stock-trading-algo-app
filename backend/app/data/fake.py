"""A deterministic price source.

Ships as part of the platform rather than as test-only scaffolding, because every strategy
increment from here needs a price series to test against, and each of them inventing its own
would guarantee they diverge — and that a "VCP detected" assertion in one test means something
different from the same assertion in another.

Generates a synthetic random walk from a seed derived from the symbol, so the same instrument
always produces the same bars, on any machine, with no network and no filesystem.
"""

from __future__ import annotations

import random
from datetime import timedelta

import pandas as pd

from app.core.clock import now_utc
from app.domain.instrument import Instrument
from app.domain.prices import Interval, PriceSeries, build_series, empty_series


class FakePriceSource:
    """Implements :class:`app.data.protocols.PriceSource` without touching anything."""

    def __init__(
        self,
        *,
        start_price: float = 1000.0,
        drift: float = 0.0004,
        volatility: float = 0.012,
        bars: int = 400,
        known: set[str] | None = None,
    ) -> None:
        self._start = start_price
        self._drift = drift
        self._volatility = volatility
        self._bars = bars
        #: When given, any symbol outside this set returns an empty series — so tests can
        #: exercise the "no data for this instrument" path deliberately.
        self._known = known

    def history(
        self,
        instrument: Instrument,
        *,
        interval: Interval = "1d",
        lookback_days: int = 400,
    ) -> PriceSeries:
        if self._known is not None and instrument.symbol not in self._known:
            return empty_series(instrument, interval)

        bars = min(self._bars, max(lookback_days, 1))
        # Seeded from the symbol: deterministic per instrument, different between them.
        rng = random.Random(f"{instrument.symbol}:{interval}")
        step = timedelta(days=7 if interval == "1wk" else 1)
        end = now_utc().replace(hour=0, minute=0, second=0, microsecond=0)

        rows, price = [], self._start
        for offset in range(bars, 0, -1):
            price *= 1 + self._drift + rng.gauss(0, self._volatility)
            price = max(price, 1.0)
            high = price * (1 + abs(rng.gauss(0, self._volatility / 2)))
            low = price * (1 - abs(rng.gauss(0, self._volatility / 2)))
            open_ = low + (high - low) * rng.random()
            rows.append(
                {
                    "timestamp": end - step * offset,
                    "open": round(open_, 2),
                    "high": round(max(high, open_, price), 2),
                    "low": round(min(low, open_, price), 2),
                    "close": round(price, 2),
                    "volume": rng.randint(50_000, 5_000_000),
                }
            )

        frame = pd.DataFrame(rows).set_index("timestamp")
        return build_series(instrument, interval, frame, source="fake")


class StaticPriceSource:
    """Serves frames supplied up front — for tests that need exact, hand-built bars."""

    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self._frames = frames

    def history(
        self,
        instrument: Instrument,
        *,
        interval: Interval = "1d",
        lookback_days: int = 400,
    ) -> PriceSeries:
        frame = self._frames.get(instrument.symbol)
        if frame is None:
            return empty_series(instrument, interval)
        return build_series(instrument, interval, frame, source="fake")
