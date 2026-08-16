"""Technical measurements.

Pure functions over a validated price frame. They compute; they do not judge — a strategy
decides what a number means, which is what keeps the decision in one auditable place.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


def sma(frame: pd.DataFrame, window: int, column: str = "close") -> float | None:
    """Simple moving average of the most recent ``window`` bars."""
    if len(frame) < window:
        return None
    return float(frame[column].tail(window).mean())


def sma_series(frame: pd.DataFrame, window: int, column: str = "close") -> pd.Series:
    return frame[column].rolling(window=window, min_periods=window).mean()


def is_rising(frame: pd.DataFrame, window: int, over_bars: int = 22) -> bool | None:
    """Whether a moving average is higher than it was ``over_bars`` ago.

    Minervini's criterion is that the 200-day average has been trending up for at least a
    month; a single endpoint comparison is the standard reading and is what the book's own
    charts show.
    """
    series = sma_series(frame, window).dropna()
    if len(series) < over_bars + 1:
        return None
    return bool(series.iloc[-1] > series.iloc[-(over_bars + 1)])


def fifty_two_week_range(frame: pd.DataFrame, bars: int = 252) -> tuple[float, float] | None:
    """(low, high) over the trailing year, from intraday extremes rather than closes."""
    window = frame.tail(bars)
    if window.empty:
        return None
    return float(window["low"].min()), float(window["high"].max())


def pct_above_low(price: float, low: float) -> float | None:
    if low <= 0:
        return None
    return round((price / low - 1) * 100, 4)


def pct_below_high(price: float, high: float) -> float | None:
    if high <= 0:
        return None
    return round((1 - price / high) * 100, 4)


def window_return_pct(frame: pd.DataFrame, bars: int, column: str = "close") -> float | None:
    """Percent change across the trailing ``bars``."""
    window = frame[column].tail(bars)
    if len(window) < 2:
        return None
    first, last = float(window.iloc[0]), float(window.iloc[-1])
    if first == 0:
        return None
    return round((last / first - 1) * 100, 4)


def relative_strength_pct(
    frame: pd.DataFrame, benchmark: pd.DataFrame, bars: int = 252
) -> float | None:
    """Return minus the benchmark's return over the same window, in percentage points.

    Deliberately **not** an IBD RS Rating. That is a cross-sectional percentile against every
    other stock and needs the whole universe ranked at once, which arrives with
    `screening-universe-and-gates`. A field named for a rating while holding something else
    would be believed by every reader afterwards.
    """
    own = window_return_pct(frame, bars)
    theirs = window_return_pct(benchmark, bars)
    if own is None or theirs is None:
        return None
    return round(own - theirs, 4)


@dataclass(frozen=True, slots=True)
class Contraction:
    """One pullback within a base: peak to trough, as a percentage of the peak."""

    high: float
    low: float
    depth_pct: float
    bars: int


def find_contractions(
    frame: pd.DataFrame, pivot_window: int = 5, max_lookback: int = 120, min_depth_pct: float = 3.0
) -> list[Contraction]:
    """Successive peak-to-trough pullbacks in the recent base, oldest first.

    Pivots are found with a rolling extremum: a bar is a swing high when it is the highest of
    the ``pivot_window`` bars either side. That finds the pivots that matter for a multi-week
    base but will disagree with a human chartist at the margins — a windowed detector cannot
    do otherwise, and pretending it is exact would overstate what the VCP reading means.

    Pullbacks shallower than ``min_depth_pct`` are noise, not contractions.
    """
    window = frame.tail(max_lookback)
    if len(window) < pivot_window * 2 + 2:
        return []

    highs = window["high"].reset_index(drop=True)
    lows = window["low"].reset_index(drop=True)
    span = pivot_window

    pivots: list[tuple[int, str, float]] = []
    for i in range(span, len(window) - span):
        neighbourhood_high = highs.iloc[i - span : i + span + 1]
        neighbourhood_low = lows.iloc[i - span : i + span + 1]
        if highs.iloc[i] == neighbourhood_high.max():
            pivots.append((i, "high", float(highs.iloc[i])))
        elif lows.iloc[i] == neighbourhood_low.min():
            pivots.append((i, "low", float(lows.iloc[i])))

    # Collapse consecutive pivots of the same kind, keeping the more extreme one — otherwise a
    # gently rounded top registers as several separate peaks.
    collapsed: list[tuple[int, str, float]] = []
    for pivot in pivots:
        if collapsed and collapsed[-1][1] == pivot[1]:
            better = max if pivot[1] == "high" else min
            if better(pivot[2], collapsed[-1][2]) == pivot[2]:
                collapsed[-1] = pivot
            continue
        collapsed.append(pivot)

    contractions: list[Contraction] = []
    for current, following in zip(collapsed, collapsed[1:], strict=False):
        if current[1] != "high" or following[1] != "low":
            continue
        high, low = current[2], following[2]
        if high <= 0 or low >= high:
            continue
        depth = round((1 - low / high) * 100, 4)
        if depth < min_depth_pct:
            continue
        contractions.append(
            Contraction(high=high, low=low, depth_pct=depth, bars=following[0] - current[0])
        )

    return contractions


def is_tightening(contractions: list[Contraction]) -> bool:
    """Whether each contraction is shallower than the one before — the VCP signature."""
    if len(contractions) < 2:
        return False
    return all(
        later.depth_pct < earlier.depth_pct
        for earlier, later in zip(contractions, contractions[1:], strict=False)
    )


def volume_dry_up_ratio(
    frame: pd.DataFrame, recent_bars: int = 10, base_bars: int = 50
) -> float | None:
    """Recent average volume as a fraction of the longer base average.

    Below 1.0 means supply is drying up, which is what Minervini looks for in the final
    contraction before a breakout.
    """
    if len(frame) < base_bars:
        return None
    recent = float(frame["volume"].tail(recent_bars).mean())
    base = float(frame["volume"].tail(base_bars).mean())
    if base <= 0:
        return None
    return round(recent / base, 4)


def to_weekly(frame: pd.DataFrame) -> pd.DataFrame:
    """Resample daily bars to weekly, aggregating OHLCV correctly.

    Resampled rather than fetched as `1wk`: the platform already holds daily bars, and a
    provider's weekly candles disagree at week boundaries (some anchor Friday, some Sunday),
    which would make a weekly moving average silently different from the daily one it is
    supposed to summarise.
    """
    if frame.empty:
        return frame
    weekly = frame.resample("W").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    )
    return weekly.dropna()


@dataclass(frozen=True, slots=True)
class RangeBreakout:
    """A horizontal base and whether price has emerged from it."""

    range_high: float
    range_low: float
    range_bars: int
    width_pct: float
    broke_out: bool
    close: float


def horizontal_range_breakout(
    frame: pd.DataFrame, min_bars: int, max_width_pct: float = 60.0, exclude_recent: int = 5
) -> RangeBreakout | None:
    """Whether the latest close has emerged above a long horizontal range.

    The range is measured **excluding the most recent bars**, so the breakout itself does not
    widen the range it is supposed to be breaking out of — that circularity would make every
    new high look like a breakout from a range that includes it.
    """
    if len(frame) < min_bars + exclude_recent:
        return None

    base = frame.iloc[-(min_bars + exclude_recent) : -exclude_recent]
    high = float(base["high"].max())
    low = float(base["low"].min())
    if high <= 0 or low <= 0:
        return None

    width = round((high / low - 1) * 100, 4)
    close = float(frame["close"].iloc[-1])
    return RangeBreakout(
        range_high=high,
        range_low=low,
        range_bars=len(base),
        width_pct=width,
        # A "range" wider than max_width_pct is a trend, not a base — calling a new high in an
        # ongoing advance a multi-year breakout would flatter every momentum name.
        broke_out=bool(close > high and width <= max_width_pct),
        close=close,
    )


def consolidation_tightness(frame: pd.DataFrame, bars: int) -> float | None:
    """High-to-low range over the last ``bars``, as a percentage of the low."""
    window = frame.tail(bars)
    if len(window) < 2:
        return None
    high, low = float(window["high"].max()), float(window["low"].min())
    if low <= 0:
        return None
    return round((high / low - 1) * 100, 4)


@dataclass(frozen=True, slots=True)
class ImpulseLeg:
    """A vertical advance: trough to peak over a compressed window."""

    start_index: int
    end_index: int
    low: float
    high: float
    gain_pct: float
    bars: int


def find_impulse_leg(
    frame: pd.DataFrame,
    min_gain_pct: float,
    max_gain_pct: float,
    min_bars: int,
    max_bars: int,
    search_window: int = 90,
) -> ImpulseLeg | None:
    """The most recent qualifying surge, or None.

    Scans backwards so the *latest* impulse wins — an older, larger one is not the leg this
    strategy is trading, and returning it would pair a stale impulse with a fresh pause.
    """
    window = frame.tail(search_window)
    if len(window) < min_bars + 1:
        return None

    lows = window["low"].reset_index(drop=True)
    highs = window["high"].reset_index(drop=True)
    n = len(window)

    for end in range(n - 1, min_bars - 1, -1):
        for span in range(min_bars, min(max_bars, end) + 1):
            start = end - span
            low = float(lows.iloc[start])
            high = float(highs.iloc[end])
            if low <= 0:
                continue
            gain = (high / low - 1) * 100
            if min_gain_pct <= gain <= max_gain_pct:
                return ImpulseLeg(
                    start_index=start,
                    end_index=end,
                    low=low,
                    high=high,
                    gain_pct=round(gain, 4),
                    bars=span,
                )
    return None


def fib_retracement_pct(
    impulse_low: float, impulse_high: float, current_low: float
) -> float | None:
    """How far a pullback has retraced the impulse, as a percentage of its height."""
    height = impulse_high - impulse_low
    if height <= 0:
        return None
    return round(max(0.0, (impulse_high - current_low) / height * 100), 4)
