"""Notable sector movers crossing declared price/volume/RS thresholds."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from app.data.protocols import PriceSource
from app.data.sectors import for_instrument
from app.domain.instrument import Instrument
from app.strategies.indicators import fifty_two_week_range, pct_below_high, relative_strength_pct

NEAR_HIGH_MAX_PCT = 5.0
VOLUME_SPIKE_MIN_MULTIPLE = 2.0
ONE_MONTH_RS_MIN_PP = 8.0
ONE_MONTH_BARS = 21


@dataclass(frozen=True, slots=True)
class MoverSignal:
    signal_id: str
    label: str
    observed: float
    threshold: float
    unit: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "label": self.label,
            "observed": self.observed,
            "threshold": self.threshold,
            "unit": self.unit,
        }


@dataclass(frozen=True, slots=True)
class NotableMover:
    symbol: str
    name: str | None
    sector_key: str
    close: float
    signals: tuple[MoverSignal, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "sector_key": self.sector_key,
            "close": self.close,
            "signals": [s.as_dict() for s in self.signals],
        }


def find_movers(
    sector_key: str,
    instruments: list[Instrument] | tuple[Instrument, ...],
    price_source: PriceSource,
    *,
    benchmark: str = "^CRSLDX",
    lookback_days: int = 300,
) -> list[NotableMover]:
    """Return sector constituents crossing declared breakout/volume/RS thresholds."""
    bench_series = price_source.history(
        Instrument(benchmark.strip().upper()), interval="1d", lookback_days=lookback_days
    )
    bench_frame = bench_series.frame if not bench_series.is_empty else pd.DataFrame()

    movers: list[NotableMover] = []
    for inst in instruments:
        resolved = for_instrument(inst)
        if resolved is None or resolved.key != sector_key:
            continue

        series = price_source.history(inst, interval="1d", lookback_days=lookback_days)
        if series.is_empty or len(series) < 25:
            continue

        frame = series.frame
        close = round(float(frame["close"].iloc[-1]), 2)
        signals: list[MoverSignal] = []

        # 1. Near 52-week high (<= 5% below 52W high)
        band = fifty_two_week_range(frame)
        if band is not None:
            below = pct_below_high(close, band[1])
            if below is not None and below <= NEAR_HIGH_MAX_PCT:
                signals.append(
                    MoverSignal(
                        signal_id="near_52w_high",
                        label=f"Within {NEAR_HIGH_MAX_PCT:.0f}% of 52-week high",
                        observed=round(below, 2),
                        threshold=NEAR_HIGH_MAX_PCT,
                        unit="%",
                    )
                )

        # 2. Volume expansion (>= 2.0x 20-day average)
        avg_vol = float(frame["volume"].tail(20).mean())
        last_vol = float(frame["volume"].iloc[-1])
        if avg_vol > 0:
            mult = round(last_vol / avg_vol, 2)
            if mult >= VOLUME_SPIKE_MIN_MULTIPLE:
                signals.append(
                    MoverSignal(
                        signal_id="volume_expansion",
                        label=f"Volume >= {VOLUME_SPIKE_MIN_MULTIPLE:.1f}x 20-day average",
                        observed=mult,
                        threshold=VOLUME_SPIKE_MIN_MULTIPLE,
                        unit="x",
                    )
                )

        # 3. 1-month RS surge (>= +8pp vs benchmark)
        if (
            not bench_frame.empty
            and len(frame) >= ONE_MONTH_BARS
            and len(bench_frame) >= ONE_MONTH_BARS
        ):
            rs_1m = relative_strength_pct(frame, bench_frame, bars=ONE_MONTH_BARS)
            if rs_1m is not None and rs_1m >= ONE_MONTH_RS_MIN_PP:
                signals.append(
                    MoverSignal(
                        signal_id="one_month_rs_surge",
                        label=f"1-month RS >= +{ONE_MONTH_RS_MIN_PP:.0f}pp vs {benchmark}",
                        observed=round(rs_1m, 2),
                        threshold=ONE_MONTH_RS_MIN_PP,
                        unit="pp",
                    )
                )

        if signals:
            movers.append(
                NotableMover(
                    symbol=inst.symbol,
                    name=inst.name,
                    sector_key=sector_key,
                    close=close,
                    signals=tuple(signals),
                )
            )

    movers.sort(key=lambda m: (-len(m.signals), m.symbol))
    return movers
