"""Sector Rotation (RRG) placement across NSE's verified sector indices.

Places every sector index on two measured axes against a named benchmark (``^CRSLDX`` Nifty 500
by default, or ``^NSEI`` Nifty 50):

* **Relative Strength (RS-Ratio):** blended 3- and 6-month sector return minus benchmark return,
  centered at ``100.0`` (above 100 means outperforming the benchmark).
* **Relative Momentum (RS-Momentum):** change in that relative strength over the trailing
  ~4 weeks (20 sessions), centered at ``100.0`` (above 100 means relative strength is rising).

Quadrants:
* ``Leading``   — strong (RS > 100) and rising (Momentum >= 100)
* ``Weakening`` — strong (RS > 100) and falling (Momentum < 100)
* ``Improving`` — weak (RS <= 100) and rising (Momentum >= 100)
* ``Lagging``   — weak (RS <= 100) and falling (Momentum < 100)
* ``unplaced``  — insufficient history; never defaulted into a quadrant.

Placement carries zero stance or conviction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import pandas as pd

from app.data.protocols import PriceSource
from app.data.sectors import SectorIndex, all_sector_indices, nse_names
from app.domain.instrument import Instrument
from app.strategies.indicators import window_return_pct

BENCHMARK_NIFTY500 = "^CRSLDX"
BENCHMARK_NIFTY50 = "^NSEI"

SHORT_RS_BARS = 63  # ~3 months
LONG_RS_BARS = 126  # ~6 months
MOMENTUM_DELTA_BARS = 20  # ~4 weeks
MIN_RRG_BARS = LONG_RS_BARS + MOMENTUM_DELTA_BARS + 5
TRAIL_STEPS = 4
TRAIL_STEP_BARS = 5  # ~1 week per point

Quadrant = Literal["Leading", "Weakening", "Lagging", "Improving", "unplaced"]


@dataclass(frozen=True, slots=True)
class TrailPoint:
    as_of: str
    rs_ratio: float
    rs_momentum: float
    quadrant: Quadrant

    def as_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of,
            "rs_ratio": self.rs_ratio,
            "rs_momentum": self.rs_momentum,
            "quadrant": self.quadrant,
        }


@dataclass(frozen=True, slots=True)
class SectorPlacement:
    key: str
    nse_name: str
    ticker: str
    benchmark: str
    quadrant: Quadrant
    rs_pct: float | None
    rs_momentum_pp: float | None
    rs_ratio: float | None
    rs_momentum: float | None
    window_bars: int = LONG_RS_BARS
    trail: tuple[TrailPoint, ...] = ()
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "nse_name": self.nse_name,
            "ticker": self.ticker,
            "benchmark": self.benchmark,
            "quadrant": self.quadrant,
            "rs_pct": self.rs_pct,
            "rs_momentum_pp": self.rs_momentum_pp,
            "rs_ratio": self.rs_ratio,
            "rs_momentum": self.rs_momentum,
            "window_bars": self.window_bars,
            "trail": [pt.as_dict() for pt in self.trail],
            "reason": self.reason,
        }


def _classify(rs_pct: float, momentum_pp: float) -> Quadrant:
    if rs_pct > 0 and momentum_pp >= 0:
        return "Leading"
    if rs_pct > 0 and momentum_pp < 0:
        return "Weakening"
    if rs_pct <= 0 and momentum_pp >= 0:
        return "Improving"
    return "Lagging"


def _blended_rs_pct(sector_frame: pd.DataFrame, bench_frame: pd.DataFrame) -> float | None:
    parts: list[float] = []
    for bars in (SHORT_RS_BARS, LONG_RS_BARS):
        own = window_return_pct(sector_frame, bars)
        base = window_return_pct(bench_frame, bars)
        if own is not None and base is not None:
            parts.append(own - base)
    if not parts:
        return None
    return round(sum(parts) / len(parts), 4)


def place_sector(
    sector: SectorIndex,
    sector_frame: pd.DataFrame,
    bench_frame: pd.DataFrame,
    *,
    benchmark: str = BENCHMARK_NIFTY500,
    display_name: str | None = None,
) -> SectorPlacement:
    """Place one sector index onto the RRG quadrants or mark it ``unplaced``."""
    label = display_name or sector.key
    if sector_frame.empty or bench_frame.empty:
        return SectorPlacement(
            key=sector.key,
            nse_name=label,
            ticker=sector.ticker,
            benchmark=benchmark,
            quadrant="unplaced",
            rs_pct=None,
            rs_momentum_pp=None,
            rs_ratio=None,
            rs_momentum=None,
            reason="price history unavailable",
        )

    n = min(len(sector_frame), len(bench_frame))
    if n < MIN_RRG_BARS:
        return SectorPlacement(
            key=sector.key,
            nse_name=label,
            ticker=sector.ticker,
            benchmark=benchmark,
            quadrant="unplaced",
            rs_pct=None,
            rs_momentum_pp=None,
            rs_ratio=None,
            rs_momentum=None,
            reason=f"only {n} bars available ({MIN_RRG_BARS} needed for RS momentum)",
        )

    def _point_at_offset(offset: int) -> tuple[float, float, Quadrant, str] | None:
        end_s = len(sector_frame) - offset
        end_b = len(bench_frame) - offset
        min_needed = LONG_RS_BARS + MOMENTUM_DELTA_BARS
        if end_s <= min_needed or end_b <= min_needed:
            return None
        cur_rs = _blended_rs_pct(sector_frame.iloc[:end_s], bench_frame.iloc[:end_b])
        prev_rs = _blended_rs_pct(
            sector_frame.iloc[: end_s - MOMENTUM_DELTA_BARS],
            bench_frame.iloc[: end_b - MOMENTUM_DELTA_BARS],
        )
        if cur_rs is None or prev_rs is None:
            return None
        momentum_pp = round(cur_rs - prev_rs, 4)
        idx_val = sector_frame.index[end_s - 1]
        as_of = idx_val.date().isoformat() if hasattr(idx_val, "date") else str(idx_val)[:10]
        return cur_rs, momentum_pp, _classify(cur_rs, momentum_pp), as_of

    latest = _point_at_offset(0)
    if latest is None:
        return SectorPlacement(
            key=sector.key,
            nse_name=label,
            ticker=sector.ticker,
            benchmark=benchmark,
            quadrant="unplaced",
            rs_pct=None,
            rs_momentum_pp=None,
            rs_ratio=None,
            rs_momentum=None,
            reason="unable to compute RS ratio and momentum over window",
        )

    rs_pct, momentum_pp, quadrant, _ = latest
    trail_points: list[TrailPoint] = []
    for step in range(TRAIL_STEPS - 1, -1, -1):
        pt = _point_at_offset(step * TRAIL_STEP_BARS)
        if pt is None:
            continue
        p_rs, p_mom, p_quad, p_date = pt
        trail_points.append(
            TrailPoint(
                as_of=p_date,
                rs_ratio=round(100.0 + p_rs, 2),
                rs_momentum=round(100.0 + p_mom, 2),
                quadrant=p_quad,
            )
        )

    return SectorPlacement(
        key=sector.key,
        nse_name=label,
        ticker=sector.ticker,
        benchmark=benchmark,
        quadrant=quadrant,
        rs_pct=round(rs_pct, 2),
        rs_momentum_pp=round(momentum_pp, 2),
        rs_ratio=round(100.0 + rs_pct, 2),
        rs_momentum=round(100.0 + momentum_pp, 2),
        trail=tuple(trail_points),
    )


def compute_sector_rrg(
    price_source: PriceSource,
    *,
    benchmark: str = BENCHMARK_NIFTY500,
    lookback_days: int = 400,
) -> list[SectorPlacement]:
    """Compute RRG placements for all 14 verified sector indices."""
    bench_symbol = benchmark.strip().upper()
    bench_series = price_source.history(
        Instrument(bench_symbol), interval="1d", lookback_days=lookback_days
    )
    bench_frame = bench_series.frame if not bench_series.is_empty else pd.DataFrame()
    labels = nse_names()

    placements: list[SectorPlacement] = []
    for sector in all_sector_indices():
        sec_series = price_source.history(
            sector.as_instrument(), interval="1d", lookback_days=lookback_days
        )
        sec_frame = sec_series.frame if not sec_series.is_empty else pd.DataFrame()
        placements.append(
            place_sector(
                sector,
                sec_frame,
                bench_frame,
                benchmark=bench_symbol,
                display_name=labels.get(sector.key, sector.key),
            )
        )

    order = {"Leading": 0, "Improving": 1, "Weakening": 2, "Lagging": 3, "unplaced": 4}
    placements.sort(
        key=lambda s: (
            order.get(s.quadrant, 4),
            -(s.rs_pct if s.rs_pct is not None else -9999.0),
            s.key,
        )
    )
    return placements


def detect_quadrant_shifts(
    current: list[SectorPlacement],
    previous_quadrants: dict[str, str],
) -> list[dict[str, Any]]:
    """Identify sectors whose RRG quadrant shifted since the previous snapshot."""
    shifts: list[dict[str, Any]] = []
    for item in current:
        prev = previous_quadrants.get(item.key)
        if not prev or prev == "unplaced" or item.quadrant == "unplaced":
            continue
        if prev != item.quadrant:
            shifts.append(
                {
                    "sector_key": item.key,
                    "nse_name": item.nse_name,
                    "from_quadrant": prev,
                    "to_quadrant": item.quadrant,
                    "rs_ratio": item.rs_ratio,
                    "rs_momentum": item.rs_momentum,
                    "benchmark": item.benchmark,
                }
            )
    return shifts
