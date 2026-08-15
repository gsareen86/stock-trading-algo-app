"""Price series, validated at the seam.

Strategies want pandas — VCP contractions, rolling relative strength and the Trend Template
are all window functions, and re-expressing them over typed candle objects would be slower
and far harder to read. But a bare DataFrame guarantees nothing, and the predecessor's
callers each re-checked for emptiness, MultiIndex columns and missing columns, or forgot to.

So: validate once here, keep pandas inside. Every strategy starts from the same guarantees.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

import pandas as pd

from app.core.clock import now_utc
from app.domain.instrument import Instrument

#: Intraday was dropped from this platform. The interval is a closed set rather than a free
#: string so an intraday request fails to typecheck rather than failing at runtime.
Interval = Literal["1d", "1wk"]
INTERVALS: tuple[Interval, ...] = ("1d", "1wk")

#: Lowercase by convention. yfinance's `Open`/`Close` capitalisation is an artefact of
#: yfinance, not a property of market data, and letting it set the convention would leak the
#: provider's shape into every strategy.
REQUIRED_COLUMNS: tuple[str, ...] = ("open", "high", "low", "close", "volume")

#: Where a series came from. Makes "did this come from cache?" answerable — which matters the
#: first time a backtest disagrees with a live run.
Source = Literal["yfinance", "cache", "fake", "empty"]


class PriceSeriesError(ValueError):
    """A frame that cannot be trusted as a price series."""


@dataclass(frozen=True, slots=True)
class PriceSeries:
    """OHLCV history for one instrument at one interval, with provenance."""

    instrument: Instrument
    interval: Interval
    frame: pd.DataFrame
    source: Source
    fetched_at: datetime = field(default_factory=now_utc)

    @property
    def is_empty(self) -> bool:
        return self.frame.empty

    def __len__(self) -> int:
        return len(self.frame)

    @property
    def last_close(self) -> float | None:
        if self.frame.empty:
            return None
        return float(self.frame["close"].iloc[-1])

    @property
    def last_bar_at(self) -> datetime | None:
        if self.frame.empty:
            return None
        return self.frame.index[-1].to_pydatetime()


def empty_series(
    instrument: Instrument, interval: Interval, source: Source = "empty"
) -> PriceSeries:
    """The 'no data' result. A failed fetch returns this rather than raising."""
    frame = pd.DataFrame(columns=list(REQUIRED_COLUMNS))
    frame.index = pd.DatetimeIndex([], tz="UTC")
    return PriceSeries(instrument=instrument, interval=interval, frame=frame, source=source)


def build_series(
    instrument: Instrument,
    interval: Interval,
    raw: pd.DataFrame,
    source: Source,
    fetched_at: datetime | None = None,
) -> PriceSeries:
    """Normalise a provider frame into a trustworthy :class:`PriceSeries`.

    Raises :class:`PriceSeriesError` when the frame cannot be repaired into the required
    shape — a missing column is a provider contract change, not a row-level defect, and
    silently returning a partial frame would push the failure into a strategy.
    """
    if interval not in INTERVALS:
        raise PriceSeriesError(
            f"unsupported interval {interval!r}; this platform has no intraday — "
            f"expected one of {INTERVALS}"
        )

    frame = raw.copy()

    # yfinance returns MultiIndex columns even for a single symbol.
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(0)

    frame.columns = [str(column).strip().lower() for column in frame.columns]

    missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise PriceSeriesError(
            f"price frame for {instrument.symbol} is missing column(s): {', '.join(missing)}"
        )

    frame = frame[list(REQUIRED_COLUMNS)]
    frame = frame.dropna()

    frame.index = _as_utc_index(frame.index)
    frame = frame[~frame.index.duplicated(keep="last")]
    frame = frame.sort_index()

    return PriceSeries(
        instrument=instrument,
        interval=interval,
        frame=frame,
        source=source,
        fetched_at=fetched_at or now_utc(),
    )


def _as_utc_index(index: pd.Index) -> pd.DatetimeIndex:
    """Coerce an index to timezone-aware UTC.

    Naive timestamps from a provider are read as UTC rather than guessed at — the alternative
    is a silent 5h30m shift on every Indian market bar, which nothing downstream would catch.
    """
    converted = pd.DatetimeIndex(pd.to_datetime(index, errors="coerce"))
    if converted.tz is None:
        return converted.tz_localize("UTC")
    return converted.tz_convert("UTC")
