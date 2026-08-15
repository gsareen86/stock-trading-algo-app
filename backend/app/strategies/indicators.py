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
